"""Backup of the whole database to Google Drive: run, retention, verification, rollback and undo.

SPEC docs/work/2026-10-20-backup-drive §3.3–3.4. Every job runs in the background, one at a time; its progress
and the last results live in ``state.json`` of the backup volume (not in the database: a rollback replaces it).
The history is the Drive folder itself. Problems reach Marko through Hermes, with generic words.
"""
from __future__ import annotations

import json
import logging
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from hestia_common.crypto import DecryptError

from .container import ContainerError, seal, sha256_file, unseal
from .pg import PgError
from .remote import RemoteError

logger = logging.getLogger("hestia_archive.backup")

FORMAT = 1
PENDING_MAX = 3
PROBLEM_KEY = "archive.backup.problem"
REAUTH_ACTION = {"text": "Ricollega Google", "command": "gateway_auth_initiate_google"}


class JobBusy(RuntimeError):
    pass


class BackupFailed(RuntimeError):
    def __init__(self, step: str, message: str):
        super().__init__(message)
        self.step = step


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dt(value: Any) -> datetime:
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)


def is_backup(f: dict) -> bool:
    return (f.get("app_properties") or {}).get("hestia") == "backup"


def created_at(f: dict) -> datetime:
    return _dt((f.get("app_properties") or {}).get("created_at") or f.get("created_at"))


def plan_retention(files: list[dict], keep_daily: int, keep_monthly: int, tz: ZoneInfo) -> tuple[set, set]:
    """``(kept_monthly_ids, trash_ids)``: the newest ``keep_daily`` backups stay, plus the first backup of each
    of the last ``keep_monthly`` months. The newest backup always stays."""
    backups = sorted((f for f in files if is_backup(f)), key=created_at, reverse=True)
    keep = {f["id"] for f in backups[:max(1, int(keep_daily))]}
    firsts: dict[str, dict] = {}
    for f in reversed(backups):                                   # oldest first: first of the month wins
        firsts.setdefault(created_at(f).astimezone(tz).strftime("%Y-%m"), f)
    monthly = {firsts[m]["id"] for m in sorted(firsts, reverse=True)[:max(0, int(keep_monthly))]}
    keep |= monthly
    return monthly, {f["id"] for f in backups if f["id"] not in keep}


class BackupService:
    def __init__(self, *, pg, remote, workdir: Path, passphrase: Callable[[], str], setting: Callable[[str, Any], Any],
                 notify: Callable[[dict], None], migrate: Callable[[str], None], before_swap: Callable[[], None],
                 after_swap: Callable[[], None], tz: str = "Europe/Rome"):
        self.pg, self.remote, self.workdir = pg, remote, Path(workdir)
        self.passphrase, self.setting, self.notify = passphrase, setting, notify
        self.migrate, self.before_swap, self.after_swap = migrate, before_swap, after_swap
        self.tz = ZoneInfo(tz)
        self._lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._job: dict | None = None
        self._thread: threading.Thread | None = None

    # ── names and paths ─────────────────────────────────────────────────────
    @property
    def live(self) -> str:
        return self.pg.dbname

    @property
    def scratch(self) -> str:
        return f"{self.live}_restore"

    @property
    def previous(self) -> str:
        return f"{self.live}_prev"

    CHECK_DB = "hestia_restore_check"

    @property
    def pending_dir(self) -> Path:
        return self.workdir / "pending"

    @property
    def tmp_dir(self) -> Path:
        return self.workdir / "tmp"

    # ── state ───────────────────────────────────────────────────────────────
    def state(self) -> dict:
        try:
            return json.loads((self.workdir / "state.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self, **changes) -> dict:
        with self._state_lock:
            st = self.state()
            st.update(changes)
            self.workdir.mkdir(parents=True, exist_ok=True)
            tmp = self.workdir / "state.json.tmp"
            tmp.write_text(json.dumps(st, indent=1, sort_keys=True), encoding="utf-8")
            tmp.replace(self.workdir / "state.json")
            return st

    # ── jobs ────────────────────────────────────────────────────────────────
    def job(self) -> dict | None:
        return dict(self._job) if self._job else None

    def _step(self, step: str) -> None:
        if self._job:
            self._job["step"] = step
        logger.info("event=backup_step kind=%s step=%s", (self._job or {}).get("kind"), step)

    def start(self, kind: str, fn: Callable[..., Any], *args, background: bool = True) -> dict:
        if not self._lock.acquire(blocking=False):
            raise JobBusy((self._job or {}).get("kind") or "job")
        self._job = {"kind": kind, "step": "start", "started_at": now_iso()}

        def body():
            try:
                fn(*args)
            except Exception as exc:                              # every path already reported
                logger.warning("event=backup_job_failed kind=%s error=%s", kind, str(exc)[:300])
            finally:
                self._job = None
                shutil.rmtree(self.tmp_dir, ignore_errors=True)
                self._lock.release()

        if not background:
            body()
            return {"started": kind, "done": True}
        self._thread = threading.Thread(target=body, daemon=True, name=f"backup-{kind}")
        self._thread.start()
        return {"started": kind}

    def wait(self, timeout: float = 600) -> None:
        if self._thread:
            self._thread.join(timeout)

    # ── problems (Hermes) ───────────────────────────────────────────────────
    def _problem(self, code: str, title: str, text: str, *, actions: list | None = None, level: str = "warning"):
        st = self.state()
        old = st.get("problem") or {}
        self._save(problem={"code": code, "title": title, "text": text, "since": old.get("since") or now_iso(),
                            "at": now_iso()})
        logger.warning("[🔄] event=backup_problem code=%s text=%s", code, text[:200])
        self.notify({"key": PROBLEM_KEY, "title": title, "text": text, "level": level, "actions": actions or []})

    def _resolved(self, *codes: str) -> None:
        """Close the live problem if it is one of ``codes`` (a good backup does not hide a failed verification)."""
        problem = self.state().get("problem") or {}
        if problem and problem.get("code") in codes:
            self._save(problem=None)
            self.notify({"key": PROBLEM_KEY, "closes": True, "title": "Backup di nuovo regolare",
                         "text": "Il backup è di nuovo regolare.", "level": "success"})

    def _secret(self) -> str:
        pw = (self.passphrase() or "").strip()
        if not pw:
            self._problem("passphrase", "Backup fermo", "Backup fermo: manca la passphrase "
                          "(HESTIA_BACKUP_PASSPHRASE nel file .env). Senza, non posso cifrare né aprire i backup.",
                          level="error")
            raise BackupFailed("passphrase", "passphrase missing")
        return pw

    # ── backup ──────────────────────────────────────────────────────────────
    def run(self) -> dict:
        started = time.monotonic()
        try:
            pw = self._secret()
            self.tmp_dir.mkdir(parents=True, exist_ok=True)
            self.pending_dir.mkdir(parents=True, exist_ok=True)
            self._step("dump")
            dump = self.tmp_dir / "backup.dump"
            counts = self.pg.dump(dump)
            created = now_iso()
            local = datetime.now(self.tz)
            name = f"hestia-backup-{local:%Y-%m-%d-%H%M}.enc"
            manifest = {"format": FORMAT, "created_at": created, "server_version": self.pg.server_version(),
                        "database": self.live, "counts": counts}
            self._step("encrypt")
            enc = self.pending_dir / name
            sha = seal(dump, manifest, enc, pw)
            dump.unlink(missing_ok=True)
            meta = {"hestia": "backup", "sha256": sha, "created_at": created, "format": str(FORMAT)}
            (self.pending_dir / f"{name}.json").write_text(json.dumps(meta), encoding="utf-8")
            last = {"name": name, "created_at": created, "size": enc.stat().st_size, "rows": sum(counts.values()),
                    "tables": len(counts)}
            self._save(last_backup={**last, "uploaded": False})
        except BackupFailed:
            raise
        except Exception as exc:
            self._problem("backup", "Backup non riuscito", f"Il backup non è riuscito ({_short(exc)}). "
                          "Riprovo al prossimo giro.", level="error")
            logger.error("event=backup_failed step=%s error=%s", (self._job or {}).get("step"), _short(exc))
            raise
        uploaded = self.flush_pending()
        if uploaded is not None:
            self._save(last_backup={**last, "uploaded": name in uploaded})
            self.retention()
            self._resolved("backup", "drive", "passphrase")
        logger.info("event=backup_done name=%s bytes=%d seconds=%d uploaded=%s", name, last["size"],
                    int(time.monotonic() - started), uploaded is not None and name in uploaded)
        return last

    def flush_pending(self) -> list[str] | None:
        """Upload local backups oldest first. ``None`` when Drive is unreachable (they stay, at most 3)."""
        files = sorted(p for p in self.pending_dir.glob("*.enc")) if self.pending_dir.is_dir() else []
        done: list[str] = []
        for i, path in enumerate(files):
            meta_path = path.with_name(path.name + ".json")
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                meta = {"hestia": "backup", "sha256": sha256_file(path), "created_at": now_iso()}
            self._step("upload")
            try:
                if i < len(files) - 1:
                    logger.info("[🔄] event=backup_upload_retry name=%s", path.name)
                self.remote.upload(path, path.name, meta)
            except RemoteError as exc:
                self._prune_pending()
                if exc.code in ("drive_scope_missing", "no_token", "drive_forbidden", "drive_api_disabled"):
                    self._problem("drive", "Backup in attesa", "Backup in attesa: Google Drive non collegato. "
                                  "La copia cifrata resta sul PC e la carico appena ricolleghi Google.",
                                  actions=[REAUTH_ACTION])
                else:
                    self._problem("drive", "Backup in attesa", f"Backup in attesa: Google Drive non raggiungibile "
                                  f"({_short(exc)}). La copia cifrata resta sul PC e riprovo al prossimo giro.")
                return None
            path.unlink(missing_ok=True)
            meta_path.unlink(missing_ok=True)
            done.append(path.name)
        return done

    def _prune_pending(self) -> None:
        files = sorted(self.pending_dir.glob("*.enc"))
        for old in files[:-PENDING_MAX]:
            old.unlink(missing_ok=True)
            old.with_name(old.name + ".json").unlink(missing_ok=True)
            logger.info("[🔄] event=backup_pending_dropped name=%s keep=%d", old.name, PENDING_MAX)

    def retention(self) -> list[str]:
        self._step("retention")
        files = self.remote.list()
        _, trash = plan_retention(files, int(self.setting("archive.backup.keep_daily", 3) or 3),
                                  int(self.setting("archive.backup.keep_monthly", 3) or 0), self.tz)
        gone = []
        for f in files:
            if f["id"] in trash:
                try:
                    self.remote.trash(f["id"])
                    gone.append(f["name"])
                except RemoteError as exc:
                    logger.warning("[🔄] event=backup_retention_failed name=%s error=%s", f["name"], exc)
        if gone:
            logger.info("event=backup_retention trashed=%s", ",".join(gone))
        return gone

    # ── history ─────────────────────────────────────────────────────────────
    def history(self) -> dict:
        try:
            files = [f for f in self.remote.list() if is_backup(f)]
            error = ""
        except RemoteError as exc:
            files, error = [], str(exc)
        monthly, _ = plan_retention(files, int(self.setting("archive.backup.keep_daily", 3) or 3),
                                    int(self.setting("archive.backup.keep_monthly", 3) or 0), self.tz)
        items = []
        for f in sorted(files, key=created_at, reverse=True):
            props = f.get("app_properties") or {}
            items.append({"id": f["id"], "name": f["name"], "size": f.get("size", 0),
                          "created_at": created_at(f).isoformat(), "monthly": f["id"] in monthly,
                          "verified_at": props.get("verified_at"), "verify": props.get("verify"),
                          "where": "drive"})
        pending = []
        for p in sorted(self.pending_dir.glob("*.enc"), reverse=True) if self.pending_dir.is_dir() else []:
            pending.append({"id": None, "name": p.name, "size": p.stat().st_size,
                            "created_at": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(),
                            "where": "local"})
        return {"items": items, "pending": pending, "error": error}

    # ── fetch + open a backup ───────────────────────────────────────────────
    def _fetch(self, file_id: str | None, pw: str) -> tuple[dict, dict, Path]:
        """Download (newest when ``file_id`` is None), check sha256, decrypt → (file, manifest, dump path)."""
        self._step("download")
        files = sorted((f for f in self.remote.list() if is_backup(f)), key=created_at, reverse=True)
        f = next((x for x in files if x["id"] == file_id), None) if file_id else (files[0] if files else None)
        if not f:
            raise BackupFailed("download", "backup non trovato su Google Drive")
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        enc = self.tmp_dir / "fetch.enc"
        self.remote.download(f["id"], enc)
        want = (f.get("app_properties") or {}).get("sha256")
        if want and sha256_file(enc) != want:
            raise BackupFailed("checksum", "il file su Drive è diverso da quello caricato (checksum)")
        self._step("decrypt")
        dump = self.tmp_dir / "fetch.dump"
        try:
            manifest = unseal(enc, dump, pw)
        except (DecryptError, ContainerError) as exc:
            raise BackupFailed("decrypt", f"non riesco ad aprirlo ({exc}): passphrase diversa o file rovinato")
        enc.unlink(missing_ok=True)
        return f, manifest, dump

    def _compare(self, dbname: str, manifest: dict) -> list[str]:
        got = self.pg.counts(dbname)
        return sorted(t for t, n in (manifest.get("counts") or {}).items() if got.get(t) != n)

    # ── verification ────────────────────────────────────────────────────────
    def verify(self, file_id: str | None = None) -> dict:
        f = None
        try:
            pw = self._secret()
            f, manifest, dump = self._fetch(file_id, pw)
            self._step("restore")
            try:
                self.pg.restore_into(self.CHECK_DB, dump)
                self._step("compare")
                bad = self._compare(self.CHECK_DB, manifest)
            finally:
                try:
                    self.pg.drop(self.CHECK_DB)
                except PgError as exc:
                    logger.warning("[🔄] event=backup_check_drop_failed error=%s", exc)
            if bad:
                raise BackupFailed("compare", "righe diverse in " + ", ".join(bad[:5]))
        except BackupFailed as exc:
            if exc.step != "passphrase":
                self._verify_failed(f, str(exc))
            raise
        except (RemoteError, PgError, OSError) as exc:
            self._verify_failed(f, _short(exc))
            raise
        result = {"name": f["name"], "created_at": created_at(f).isoformat(), "verified_at": now_iso(), "ok": True,
                  "tables": len(manifest.get("counts") or {}), "rows": sum((manifest.get("counts") or {}).values())}
        self._mark(f, "ok")
        self._save(last_verify=result)
        logger.info("event=backup_verify ok=true name=%s tables=%d mismatched=0", f["name"], result["tables"])
        self._resolved("verify", "passphrase")
        return result

    def _mark(self, f: dict | None, verdict: str) -> None:
        if not f:
            return
        try:
            self.remote.update(f["id"], {"verified_at": now_iso(), "verify": verdict})
        except RemoteError as exc:
            logger.warning("[🔄] event=backup_verify_mark_failed error=%s", exc)

    def _verify_failed(self, f: dict | None, why: str) -> None:
        self._mark(f, "fail")
        self._save(last_verify={"name": (f or {}).get("name"), "verified_at": now_iso(), "ok": False, "error": why})
        logger.error("event=backup_verify ok=false name=%s error=%s", (f or {}).get("name"), why)
        self._problem("verify", "Verifica del backup fallita", f"Verifica del backup fallita: {why}.", level="error")

    # ── rollback ────────────────────────────────────────────────────────────
    def restore(self, file_id: str) -> dict:
        pw = self._secret()
        try:
            f, manifest, dump = self._fetch(file_id, pw)
            self._step("restore")
            self.pg.restore_into(self.scratch, dump)
            dump.unlink(missing_ok=True)
            self._step("migrate")
            self.migrate(self.scratch)
            self._step("compare")
            bad = self._compare(self.scratch, manifest)
            if bad:
                raise BackupFailed("compare", "righe diverse in " + ", ".join(bad[:5]))
        except Exception as exc:
            self._drop_quietly(self.scratch)
            logger.error("event=backup_restore ok=false step=%s error=%s", (self._job or {}).get("step"),
                         _short(exc))
            self._save(last_restore={"ok": False, "at": now_iso(), "error": _short(exc)})
            raise
        self._step("swap")
        self._swap(lambda: self.pg.swap(self.live, self.scratch, self.previous))
        when = created_at(f)
        info = {"ok": True, "at": now_iso(), "name": f["name"], "backup_created_at": when.isoformat(),
                "undone": False}
        self._save(last_restore=info)
        logger.info("event=backup_restore ok=true step=done name=%s", f["name"])
        self.notify({"key": "archive.backup.restore", "title": "Dati ripristinati",
                     "text": f"Dati ripristinati al {when.astimezone(self.tz):%d/%m/%Y %H:%M}. Se non era quello che "
                             "volevi, nel pannello Backup delle impostazioni c'è «Annulla ripristino».",
                     "level": "success"})
        return info

    def undo(self) -> dict:
        if not self.pg.exists(self.previous):
            raise BackupFailed("undo", "non c'è un ripristino da annullare")
        self._step("swap")
        self._swap(lambda: self.pg.exchange(self.live, self.previous))
        st = self.state().get("last_restore") or {}
        info = {**st, "undone": not st.get("undone"), "undo_at": now_iso()}
        self._save(last_restore=info)
        logger.info("event=backup_restore_undo undone=%s", info["undone"])
        self.notify({"key": "archive.backup.restore", "title": "Ripristino annullato" if info["undone"]
                     else "Ripristino rifatto", "text": "I dati sono tornati com'erano prima del ripristino."
                     if info["undone"] else "I dati sono di nuovo quelli del backup ripristinato.", "level": "info"})
        return info

    def _swap(self, rename: Callable[[], None]) -> None:
        self.before_swap()
        try:
            rename()
        finally:
            self.after_swap()

    def _drop_quietly(self, name: str) -> None:
        try:
            self.pg.drop(name)
        except Exception as exc:
            logger.warning("[🔄] event=backup_scratch_drop_failed db=%s error=%s", name, exc)

    def undo_available(self) -> bool:
        try:
            return self.pg.exists(self.previous)
        except Exception:
            return False


def _short(exc: Exception) -> str:
    return (str(exc) or exc.__class__.__name__).strip().splitlines()[-1][:240] if str(exc) else exc.__class__.__name__
