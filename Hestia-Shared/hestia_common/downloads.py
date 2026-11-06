"""Downloads that keep track of themselves (docs/work/2026-10-30-setup-un-click §4.3).

Every module downloads its own things (Oracle its models, Echo its voices): this gives them one job format and one
door, so the WebUI page «Download» can show them all through the Hub.

    downloads = Downloads("echo", state_path=DATA / "downloads.json", hub=Hub(HUB_API_URL))
    downloads.file("piper:it_IT-paola-medium", "Voce Paola", url, dest, size_hint=63_000_000)
    downloads.source("ollama", lambda job: run_ollama_pull)      # a custom source: run(job) reports job.progress()
    app.include_router(downloads.router())                       # GET /api/downloads, POST /api/downloads/<id>/<op>
    caps.update(downloads.capabilities())                        # Hub registration → the WebUI finds it

Job: ``{id, what, source, size, done, speed, eta_s, state, error, module, updated_at}``; states ``in_coda ·
in_corso · in_pausa · fatto · errore``. Built-in source ``http``: resumes from the ``.part`` file (HTTP Range),
checks the free disk **before** starting, verifies an optional sha256, retries 3 times (2/4/8 s). Jobs survive a
restart (``state_path``): one that was running comes back paused («Riprendi»). Finished big downloads and every
failure go to Notifiche through Hermes (the only one who writes to the user).
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("hestia_common.downloads")

ACTIVE = ("in_coda", "in_corso")
RETRY_DELAYS = (2, 4, 8)
NOTIFY_DONE_BYTES = 200_000_000      # a finished download is worth a notice only when it was a long wait
CHUNK = 1 << 20
GB = 1e9


class Stopped(Exception):
    """Raised inside a run when the user paused or cancelled the job."""


class DownloadError(RuntimeError):
    """A failure with a reason a person understands (no retry when ``final``)."""

    def __init__(self, message: str, final: bool = False):
        super().__init__(message)
        self.final = final


def gb(n: float) -> str:
    return f"{n / GB:.1f}".replace(".", ",")


class Job:
    def __init__(self, data: dict[str, Any], manager: "Downloads"):
        self.data = data
        self._manager = manager
        self._stop = threading.Event()
        self._last = (time.monotonic(), int(data.get("done") or 0))

    @property
    def id(self) -> str:
        return self.data["id"]

    @property
    def params(self) -> dict[str, Any]:
        return self.data.get("params") or {}

    def progress(self, done: int, size: int | None = None) -> None:
        """Report bytes done (and the total when known); raises ``Stopped`` when paused or cancelled."""
        now = time.monotonic()
        then, before = self._last
        with self._manager._lock:
            if size:
                self.data["size"] = int(size)
            self.data["done"] = int(done)
            if now - then >= 1.0:
                speed = max(0.0, (done - before) / (now - then))
                self.data["speed"] = int(speed)
                left = (self.data.get("size") or 0) - done
                self.data["eta_s"] = int(left / speed) if speed > 0 and left > 0 else None
                self._last = (now, done)
            self.data["updated_at"] = time.time()
        self.check()

    def check(self) -> None:
        if self._stop.is_set():
            raise Stopped()


class Downloads:
    def __init__(self, module: str, state_path: Path | str | None = None, hub: Any = None, page: str = "",
                 workers: int = 1):
        self.module = module
        self.state_path = Path(state_path) if state_path else None
        self.hub = hub
        self.page = page
        self._lock = threading.RLock()
        self._jobs: dict[str, Job] = {}
        self._sources: dict[str, Callable[[Job], None]] = {"http": self._run_http}
        self._removers: dict[str, Callable[[Job], None]] = {}
        self._done = threading.Condition(self._lock)
        self._queue: list[str] = []
        self._wake = threading.Event()
        self._load()
        for i in range(max(1, workers)):
            threading.Thread(target=self._worker, name=f"{module}-downloads-{i}", daemon=True).start()

    # ── registering work ─────────────────────────────────────────────────────
    def source(self, name: str, run: Callable[[Job], None], remove: Callable[[Job], None] | None = None) -> None:
        """A custom source: ``run(job)`` downloads ``job.params`` and calls ``job.progress``; ``remove`` frees it."""
        self._sources[name] = run
        if remove:
            self._removers[name] = remove

    def add(self, job_id: str, what: str, source: str, params: dict[str, Any] | None = None,
            size_hint: int = 0) -> dict[str, Any]:
        """Queue a job (idempotent: an active or finished job with the same id is returned as it is)."""
        if source not in self._sources:
            raise ValueError(f"unknown download source {source}")
        with self._lock:
            job = self._jobs.get(job_id)
            if job and job.data["state"] in (*ACTIVE, "fatto"):
                return dict(job.data)
            data = {"id": job_id, "what": what, "source": source, "params": dict(params or {}),
                    "module": self.module, "size": int(size_hint or 0), "done": 0, "speed": 0, "eta_s": None,
                    "state": "in_coda", "error": "", "attempts": 0, "updated_at": time.time()}
            self._jobs[job_id] = Job(data, self)
            self._enqueue(job_id)
        logger.info("event=download_queued module=%s id=%s source=%s", self.module, job_id, source)
        return dict(data)

    def file(self, job_id: str, what: str, url: str, dest: Path | str, size_hint: int = 0, sha256: str = "",
             headers: dict[str, str] | None = None) -> dict[str, Any]:
        return self.add(job_id, what, "http", {"url": url, "dest": str(dest), "sha256": sha256,
                                               "headers": headers or {}}, size_hint)

    def wait(self, job_id: str, timeout: float = 900) -> dict[str, Any]:
        """Block until the job ends (for a caller that needs the file now, e.g. the first spoken sentence)."""
        deadline = time.monotonic() + timeout
        with self._done:
            while True:
                job = self._jobs.get(job_id)
                if not job or job.data["state"] not in ACTIVE:
                    return dict(job.data) if job else {}
                left = deadline - time.monotonic()
                if left <= 0:
                    return dict(job.data)
                self._done.wait(min(left, 5))

    # ── user actions ─────────────────────────────────────────────────────────
    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._public(j.data) for j in self._jobs.values()]

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return self._public(job.data) if job else None

    def pause(self, job_id: str) -> dict[str, Any]:
        return self._stop_job(job_id, "in_pausa")

    def cancel(self, job_id: str) -> dict[str, Any]:
        """Stop and forget the job; a partial file is deleted."""
        out = self._stop_job(job_id, "annullato")
        job = self._jobs.get(job_id)
        if job and job.data["source"] == "http":
            Path(job.params["dest"] + ".part").unlink(missing_ok=True)
        with self._lock:
            self._jobs.pop(job_id, None)
            self._save()
        return out

    def resume(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._require(job_id)
            if job.data["state"] in ("in_pausa", "errore"):
                job.data.update(state="in_coda", error="", attempts=0)
                self._enqueue(job_id)      # a run still stopping ends on its own stop flag; the next one gets a new one
            return self._public(job.data)

    retry = resume

    def remove(self, job_id: str) -> dict[str, Any]:
        """Delete what a finished job downloaded, to free space («Elimina»)."""
        with self._lock:
            job = self._require(job_id)
            if job.data["state"] in ACTIVE:
                raise DownloadError("Prima ferma il download.", final=True)
        if job.data["source"] == "http":
            Path(job.params["dest"]).unlink(missing_ok=True)
        elif job.data["source"] in self._removers:
            self._removers[job.data["source"]](job)
        with self._lock:
            self._jobs.pop(job_id, None)
            self._save()
        logger.info("event=download_removed module=%s id=%s", self.module, job_id)
        return {"id": job_id, "removed": True}

    def _stop_job(self, job_id: str, state: str) -> dict[str, Any]:
        with self._lock:
            job = self._require(job_id)
            if job.data["state"] in ACTIVE:
                job._stop.set()
                if job_id in self._queue:
                    self._queue.remove(job_id)
                job.data["state"] = state
                job.data["speed"], job.data["eta_s"] = 0, None
                self._save()
            return self._public(job.data)

    def _require(self, job_id: str) -> Job:
        job = self._jobs.get(job_id)
        if not job:
            raise DownloadError("Download non trovato.", final=True)
        return job

    # ── worker ───────────────────────────────────────────────────────────────
    def _enqueue(self, job_id: str) -> None:
        if job_id not in self._queue:
            self._queue.append(job_id)
        self._save()
        self._wake.set()

    def _next(self) -> Job | None:
        with self._lock:
            while self._queue:
                job = self._jobs.get(self._queue.pop(0))
                if job and job.data["state"] == "in_coda":
                    job.data["state"] = "in_corso"
                    job._stop = threading.Event()
                    return job
            self._wake.clear()
            return None

    def _worker(self) -> None:
        while True:
            job = self._next()
            if job is None:
                self._wake.wait(30)
                continue
            self._run(job)

    def _run(self, job: Job) -> None:
        run = self._sources.get(job.data["source"])
        while True:
            try:
                job.data["attempts"] = int(job.data.get("attempts") or 0) + 1
                if run is None:
                    raise DownloadError("Questo download non si può più riprendere.", final=True)
                run(job)
                self._finish(job, "fatto")
                return
            except Stopped:
                logger.info("event=download_stopped module=%s id=%s state=%s", self.module, job.id, job.data["state"])
                self._finish(job, None)
                return
            except Exception as exc:
                final = isinstance(exc, DownloadError) and exc.final
                attempt = job.data["attempts"]
                if final or attempt > len(RETRY_DELAYS):
                    job.data["error"] = str(exc) if isinstance(exc, DownloadError) else "Download non riuscito."
                    logger.warning("event=download_failed module=%s id=%s attempts=%s error=%s", self.module,
                                   job.id, attempt, str(exc)[:200])
                    self._finish(job, "errore")
                    return
                delay = RETRY_DELAYS[attempt - 1]
                logger.warning("[🔄] event=download_retry module=%s id=%s attempt=%s in=%ss error=%s", self.module,
                               job.id, attempt, delay, str(exc)[:200])
                if job._stop.wait(delay):
                    self._finish(job, None)
                    return

    def _finish(self, job: Job, state: str | None) -> None:
        with self._done:
            if state:
                job.data["state"] = state
            job.data["speed"], job.data["eta_s"] = 0, None
            job.data["updated_at"] = time.time()
            if state == "fatto" and job.data.get("size"):
                job.data["done"] = job.data["size"]
            self._save()
            self._done.notify_all()
        if state == "fatto":
            logger.info("event=download_done module=%s id=%s bytes=%s", self.module, job.id, job.data.get("size"))
            if (job.data.get("size") or 0) >= NOTIFY_DONE_BYTES:
                self._notify(job, f"{job.data['what']} è pronto.", "info")
        elif state == "errore":
            self._notify(job, f"{job.data['what']}: {job.data['error']}", "warning")

    def _notify(self, job: Job, text: str, level: str) -> None:
        if self.hub is None:
            return
        try:
            from .reminders import reminder_event
            if level != "info":
                text += " Puoi riprovare dalla pagina Download."
            self.hub.call("hermes", "POST", "api/events/ingest", body=reminder_event(
                module=self.module, domain="system", key=f"download.{self.module}.{job.id}",
                title="Download" if level == "info" else "Download non riuscito", text=text, actions=[],
                page=self.page, level=level), timeout=8)
        except Exception as exc:
            logger.warning("[🔄] event=download_notify_failed module=%s id=%s error=%s", self.module, job.id, exc)

    # ── built-in source: HTTP with resume ─────────────────────────────────────
    def _run_http(self, job: Job) -> None:
        import requests
        p = job.params
        dest = Path(p["dest"])
        part = Path(p["dest"] + ".part")
        dest.parent.mkdir(parents=True, exist_ok=True)
        have = part.stat().st_size if part.exists() else 0
        headers = dict(p.get("headers") or {})
        if have:
            headers["Range"] = f"bytes={have}-"
        with requests.get(p["url"], headers=headers, stream=True, timeout=(15, 120), allow_redirects=True) as resp:
            if resp.status_code == 416:                 # the part file is already complete
                resp.close()
            elif resp.status_code in (401, 403):
                raise DownloadError("Il file è riservato: serve un token di Hugging Face.", final=True)
            elif resp.status_code == 404:
                raise DownloadError("Il file non esiste più a quell'indirizzo.", final=True)
            elif resp.status_code >= 400:
                raise DownloadError(f"Il server ha risposto {resp.status_code}.")
            else:
                if resp.status_code == 200 and have:    # no Range support: start again
                    have = 0
                length = int(resp.headers.get("Content-Length") or 0)
                total = have + length if length else int(job.data.get("size") or 0)
                check_space(dest.parent, max(0, total - have))
                job.progress(have, total or None)
                with open(part, "ab" if have else "wb") as fh:
                    done = have
                    for chunk in resp.iter_content(CHUNK):
                        if chunk:
                            fh.write(chunk)
                            done += len(chunk)
                            job.progress(done)
        if p.get("sha256") and file_sha256(part) != p["sha256"].lower():
            part.unlink(missing_ok=True)
            raise DownloadError("Il file scaricato è rovinato: lo riscarico.")
        part.replace(dest)

    # ── persistence ──────────────────────────────────────────────────────────
    def _load(self) -> None:
        if not self.state_path or not self.state_path.exists():
            return
        try:
            rows = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("[🔄] event=downloads_state_unreadable module=%s error=%s fallback=empty", self.module, exc)
            return
        for data in rows if isinstance(rows, list) else []:
            if data.get("state") in ACTIVE:              # interrupted by a restart: the user resumes it
                data.update(state="in_pausa", speed=0, eta_s=None)
            self._jobs[data["id"]] = Job(data, self)

    def _save(self) -> None:
        if not self.state_path:
            return
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps([j.data for j in self._jobs.values()], ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.state_path)
        except Exception as exc:
            logger.warning("[🔄] event=downloads_state_not_saved module=%s error=%s", self.module, exc)

    @staticmethod
    def _public(data: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in data.items() if k not in ("params",)}

    # ── HTTP door ────────────────────────────────────────────────────────────
    def capabilities(self) -> dict[str, Any]:
        return {"downloads": {"endpoint": "/api/downloads"}}

    def router(self):
        from fastapi import APIRouter, HTTPException

        router = APIRouter(prefix="/api/downloads", tags=["downloads"])
        ops = {"pause": self.pause, "resume": self.resume, "retry": self.retry, "cancel": self.cancel,
               "remove": self.remove}

        @router.get("")
        def downloads_list():
            return {"module": self.module, "downloads": self.list()}

        @router.post("/{job_id:path}/{op}")
        def downloads_op(job_id: str, op: str):
            if op not in ops:
                raise HTTPException(status_code=404, detail="unknown operation")
            try:
                return ops[op](job_id)
            except DownloadError as exc:
                raise HTTPException(status_code=409 if exc.final and "ferma" in str(exc) else 404, detail=str(exc))

        return router


def check_space(folder: Path, need: int, margin: int = 500_000_000) -> None:
    """Refuse before starting when the disk cannot take it (a full disk breaks every module)."""
    try:
        free = shutil.disk_usage(folder).free
    except OSError:
        return
    if need and free < need + margin:
        raise DownloadError(f"Servono {gb(need)} GB, ne hai {gb(free)}: libera spazio o scegli qualcosa di più "
                            f"piccolo.", final=True)


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()
