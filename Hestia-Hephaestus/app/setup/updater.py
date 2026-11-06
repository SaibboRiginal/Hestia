"""«Aggiorna Hestia» — Hestia updates itself to the next version (docs/work/2026-10-30-setup-un-click §4.4, P6).

Single responsibility: know the installed version, find a newer one, move ``/repo`` to it and apply it to the
running containers, with an automatic way back.

- Versions = git tags ``vX.Y.Z`` (the GitHub releases, `images.yml`). Channel (Themis ``hephaestus.update.channel``):
  ``stabile`` = the newest tag · ``novita`` = ``origin/main``.
- Check: ``git fetch`` + compare; what's new = the root ``CHANGELOG.md`` lines added between the two versions.
  Daily agenda job; a newer version → Hermes asks «Installo?» (the answer comes back to ``/api/setup/update/answer``).
- Apply (background thread, state in ``data/update.json``): refuse when the repo has local changes or commits
  (Forge work is never overwritten), ``git checkout`` the target, then per service touched by the diff
  (``forge.deployer.plan``): code-only → restart (the code is mounted); image change (Dockerfile, requirements, the
  WebUI) → ready-made image of the new version when this install uses them, else a local build, then re-create the
  container on it. Only running containers are touched (a «Casa centrale» keeps voice/training off). Health check
  through the Hub; anything unhealthy → back to the previous version and the previous images, the same way.
- Hephaestus itself restarts last; an image change of Hephaestus itself is left to the installer's ``--update``.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable

from ..forge import deployer, git_ops
from . import secrets

logger = logging.getLogger("hestia_hephaestus.setup.updater")

TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
IMAGES = "ghcr.io/saibboriginal/hestia"
NOTES_MAX = 12
ANSWER_PATH = "/api/setup/update/answer"


def parse(tag: str) -> tuple[int, int, int] | None:
    m = TAG_RE.match(tag or "")
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def changelog_notes(diff: str) -> list[str]:
    """Lines added to the root CHANGELOG between two versions → plain sentences (no dossier links, no tags)."""
    out = []
    for line in diff.splitlines():
        if not line.startswith("+- "):
            continue
        text = re.sub(r"\s*→\s*`[^`]*`.*$", "", line[3:]).strip()
        text = re.sub(r"\s*\[(ext-chat|ai|forge:[^\]]*)\]\s*$", "", text).strip()
        if text:
            out.append(text if len(text) <= 300 else text[:297].rstrip() + "…")
    return out


class Updater:
    def __init__(self, repo: Path, data_dir: Path, *, channel: Callable[[], str],
                 notify: Callable[[dict], None] | None = None,
                 translate: Callable[[list[str]], list[str] | None] | None = None,
                 unhealthy: Callable[[list[str]], list[str]] | None = None,
                 docker_client: Callable[[], Any] | None = None):
        self.repo = Path(repo)
        self.path = Path(data_dir) / "update.json"
        self.channel = channel
        self.notify = notify
        self.translate = translate
        self.unhealthy = unhealthy or (lambda services: [])
        self._docker = docker_client
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    # ── state ────────────────────────────────────────────────────────────────
    def _load(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except Exception as exc:
            logger.warning("[🔄] event=update_state_unreadable error=%s fallback=empty", exc)
            return {}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def _patch(self, **changes) -> dict[str, Any]:
        with self._lock:
            data = self._load()
            data.update(changes)
            self._save(data)
            return data

    def _git(self, *args: str, timeout: int = 120, check: bool = True) -> str:
        return git_ops.git(self.repo, *args, timeout=timeout, check=check)

    # ── what is installed ────────────────────────────────────────────────────
    def installed(self) -> dict[str, Any]:
        commit = self._git("rev-parse", "--short=7", "HEAD", check=False)
        tag = self._git("describe", "--tags", "--exact-match", "--match", "v*.*.*", check=False)
        tag = tag if parse(tag) else ""
        return {"version": tag[1:] if tag else "", "tag": tag, "commit": commit,
                "label": tag[1:] if tag else f"sviluppo {commit}"}

    def blocked(self) -> str:
        """Why an update cannot start now (empty = it can)."""
        if not git_ops.is_repo(self.repo):
            return "Questa installazione non ha la cartella git di Hestia: aggiorna rilanciando l'installer."
        if self._git("status", "--porcelain", "--untracked-files=no", check=False):
            return "Ci sono modifiche locali al codice: le tengo, quindi non aggiorno da solo. Salvale o annullale, poi riprova."
        if self.channel() == "novita":
            ahead = self._git("rev-list", "--count", "origin/main..HEAD", check=False) or "0"
            if ahead.isdigit() and int(ahead):
                return (f"Il codice ha {ahead} modifiche fatte qui (sviluppo) che non sono su GitHub: "
                        "pubblicale o annullale, poi riprova.")
        elif not self.installed()["tag"]:
            head = self._git("rev-parse", "HEAD", check=False)
            if self._git("branch", "-r", "--contains", head, check=False) == "":
                return "Il codice ha modifiche fatte qui (sviluppo) che non sono su GitHub: non le sovrascrivo."
        return ""

    # ── what is available ────────────────────────────────────────────────────
    def check(self, notify: bool = False) -> dict[str, Any]:
        channel = self.channel()
        try:
            self._git("fetch", "--tags", "--prune", "origin", timeout=180)
        except git_ops.GitError as exc:
            logger.warning("[🔄] event=update_fetch_failed error=%s", str(exc)[:200])
            return self._patch(checked_at=time.time(), available=None,
                               check_error="Non riesco a raggiungere GitHub: riprovo più tardi.")
        current = self.installed()
        available = None
        if channel == "novita":
            behind = self._git("rev-list", "--count", "HEAD..origin/main", check=False) or "0"
            if behind.isdigit() and int(behind):
                target = self._git("rev-parse", "--short=7", "origin/main")
                available = {"ref": "origin/main", "label": f"sviluppo {target}", "commits": int(behind)}
        else:
            tags = [t for t in self._git("tag", "-l", "v*.*.*", "--sort=-v:refname").splitlines() if parse(t)]
            newest = tags[0] if tags else ""
            mine = parse(current["tag"]) or (0, 0, 0)
            if newest and parse(newest) > mine:
                available = {"ref": newest, "label": newest[1:],
                             "major": bool(current["tag"]) and parse(newest)[0] > mine[0]}
        if available:
            diff = self._git("diff", "HEAD", available["ref"], "--", "CHANGELOG.md", check=False)
            notes = changelog_notes(diff)[:NOTES_MAX]
            same = self._load().get("available") or {}
            if same.get("ref") == available["ref"] and same.get("notes_source") == notes:
                available["notes"] = same.get("notes") or notes     # already in Italian: no new model call
            else:
                available["notes"] = self._italian(notes)
            available["notes_source"] = notes
        data = self._patch(checked_at=time.time(), available=available, check_error="")
        logger.info("event=update_checked channel=%s current=%s available=%s", channel, current["label"],
                    (available or {}).get("label", "-"))
        if available and notify and self.notify and data.get("notified") != available["label"]:
            self._ask(current, available)
            self._patch(notified=available["label"])
        return data

    def _italian(self, notes: list[str]) -> list[str]:
        """The CHANGELOG is written in English: the brain rewrites the lines in plain Italian (same count, same
        order); brain off or a wrong answer → the lines as they are."""
        if not notes or not self.translate:
            return notes
        try:
            out = self.translate(notes)
        except Exception as exc:
            logger.warning("[🔄] event=update_notes_translate_failed error=%s fallback=english", str(exc)[:120])
            return notes
        return out if out and len(out) == len(notes) else notes

    def _ask(self, current: dict, available: dict) -> None:
        notes = available.get("notes") or []
        text = (f"È uscita Hestia {available['label']}" if available["ref"] != "origin/main"
                else f"Ci sono {available.get('commits', 0)} novità di sviluppo")
        text += f" (ora hai {current['label']})."
        if notes:
            text += " Novità:\n" + "\n".join(f"• {n}" for n in notes[:5])
            if len(notes) > 5:
                text += f"\n…e altre {len(notes) - 5}."
        if available.get("major"):
            text += "\nVersione grande: se dopo serve qualcosa sul computer, te lo dico io."
        text += "\nInstallo adesso? Se qualcosa non va, torno da solo alla versione di prima."
        try:
            self.notify({"key": "hephaestus.update", "title": "Aggiornamento", "text": text,
                         "question": {"kind": "confirm", "service": "hephaestus", "path": ANSWER_PATH}})
        except Exception as exc:
            logger.warning("[🔄] event=update_notice_failed error=%s", exc)

    # ── apply ────────────────────────────────────────────────────────────────
    def status(self) -> dict[str, Any]:
        data = self._load()
        return {"installed": self.installed(), "channel": self.channel(), "available": data.get("available"),
                "checked_at": data.get("checked_at"), "check_error": data.get("check_error", ""),
                "job": data.get("job") or {"state": "idle"}, "history": (data.get("history") or [])[-20:],
                "previous": data.get("previous") or "", "blocked": self.blocked()}

    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def apply(self, ref: str = "", *, back: bool = False) -> dict[str, Any]:
        if self.running():
            raise UpdateRefused("Un aggiornamento è già in corso.")
        why = self.blocked()
        if why:
            raise UpdateRefused(why)
        data = self._load()
        ref = ref or (data.get("available") or {}).get("ref") or ""
        if back:
            ref = data.get("previous") or ""
        if not ref:
            raise UpdateRefused("Non c'è una versione da installare: sei già all'ultima.")
        self._patch(job={"state": "in_corso", "step": "Preparo", "target": ref, "started_at": time.time()})
        self._thread = threading.Thread(target=self._run, args=(ref, back), daemon=True, name="hestia-update")
        self._thread.start()
        return self.status()

    def _step(self, text: str) -> None:
        with self._lock:
            data = self._load()
            data.setdefault("job", {})["step"] = text
            self._save(data)
        logger.info("event=update_step step=%s", text)

    def _run(self, ref: str, back: bool) -> None:
        before = self._git("rev-parse", "HEAD")
        before_label = self.installed()["label"]
        branch = self._git("rev-parse", "--abbrev-ref", "HEAD")
        images: dict[str, str] = {}
        touched: list[str] = []
        restart_self = False
        try:
            self._step("Scarico il codice nuovo")
            self._checkout(ref)
            after_label = self.installed()["label"]
            files = [f for f in self._git("diff", "--name-only", before, "HEAD").splitlines() if f]
            plan = deployer.plan(self.repo, files)
            client = self._client()
            running = self._running(client)
            rebuild = [s for s in plan.rebuild if s in running and s != "hephaestus"]
            restart = [s for s in plan.restart if s in running]
            note = ("Hestia stessa ha un cambio che serve il computer: rilancia l'installer con --update."
                    if "hephaestus" in plan.rebuild else "")
            touched = rebuild + restart
            for svc in rebuild:
                self._step(f"Preparo la nuova versione di {svc}")
                images[svc] = self._new_image(client, svc, ref)
            if restart:
                self._step("Riavvio le parti cambiate")
                self._restart(client, restart)
            self._step("Controllo che tutto risponda")
            bad = self.unhealthy(touched) if touched else []
            if bad:
                raise UpdateFailed(f"non rispondono: {', '.join(bad)}")
            restart_self = plan.restart_self and "hephaestus" in running
            self._finish(before, before_label, after_label, ok=True, back=back, detail=note)
        except Exception as exc:
            logger.warning("[🔄] event=update_failed target=%s error=%s — back to %s", ref, str(exc)[:300], before[:8])
            self._undo(before, branch, images, touched)
            self._finish(before, before_label, before_label, ok=False, back=back,
                         detail=f"Non è andato ({str(exc)[:160]}): sono tornato a {before_label}.")
        if restart_self:
            time.sleep(2)
            try:
                self._client().containers.get("hestia_hephaestus").restart(timeout=20)
            except Exception as exc:
                logger.warning("[🔄] event=update_self_restart_failed error=%s", exc)

    def _checkout(self, ref: str) -> None:
        if ref == "origin/main":
            if self._git("rev-parse", "--abbrev-ref", "HEAD") != "main":
                self._git("checkout", "--quiet", "main")
            self._git("merge", "--ff-only", "--quiet", "origin/main")
        else:
            self._git("-c", "advice.detachedHead=false", "checkout", "--quiet", ref)

    def _undo(self, before: str, branch: str, images: dict[str, str], touched: list[str]) -> None:
        try:
            if branch and branch != "HEAD":
                self._git("checkout", "--quiet", branch)
                self._git("reset", "--hard", "--quiet", before)
            else:
                self._git("-c", "advice.detachedHead=false", "checkout", "--quiet", before)
        except Exception as exc:
            logger.error("event=update_undo_git_failed error=%s", exc)
        try:
            client = self._client()
            for svc, old in images.items():
                secrets.recreate_with_env(svc, {}, client=client, image=old)
            self._restart(client, [s for s in touched if s not in images])
        except Exception as exc:
            logger.error("event=update_undo_containers_failed error=%s", exc)

    def _finish(self, before: str, frm: str, to: str, *, ok: bool, back: bool, detail: str) -> None:
        with self._lock:
            data = self._load()
            data["job"] = {"state": "fatto" if ok else "errore", "step": "", "detail": detail, "ended_at": time.time()}
            data.setdefault("history", []).append({"at": time.time(), "from": frm, "to": to, "ok": ok,
                                                  "back": back, "detail": detail})
            data["history"] = data["history"][-50:]
            if ok:
                data["previous"] = before
                data["available"] = None
            self._save(data)
        logger.info("event=update_done ok=%s from=%s to=%s", ok, frm, to)
        if self.notify:
            text = (f"Hestia è aggiornata a {to}." if ok and not back else
                    f"Sono tornato a {to}." if ok else detail)
            if ok and detail:
                text += " " + detail
            try:
                self.notify({"key": "hephaestus.update", "title": "Aggiornamento", "text": text,
                             "level": "info" if ok else "warning"})
            except Exception as exc:
                logger.warning("[🔄] event=update_notice_failed error=%s", exc)

    # ── containers ───────────────────────────────────────────────────────────
    def _client(self):
        if self._docker:
            return self._docker()
        import docker
        return docker.from_env()

    @staticmethod
    def _running(client) -> set[str]:
        return {c.name[len("hestia_"):] for c in client.containers.list(filters={"name": "hestia_"})
                if c.name.startswith("hestia_")}

    @staticmethod
    def _restart(client, services: list[str]) -> None:
        for svc in services:
            client.containers.get(f"hestia_{svc}").restart(timeout=30)

    def _new_image(self, client, svc: str, ref: str) -> str:
        """The new image for ``svc``, the container re-created on it. Returns the previous image id (for the undo)."""
        box = client.containers.get(f"hestia_{svc}")
        old_id = box.image.id
        current = (box.attrs.get("Config") or {}).get("Image") or ""
        version = ref[1:] if parse(ref) else ""
        if current.startswith(IMAGES) and version:
            image = f"{IMAGES}:{svc}-{version}"
            client.images.pull(image)
        else:
            image = current or f"hestia-{svc}"
            build = _compose_build(self.repo, svc)
            if not build:
                raise UpdateFailed(f"non so come costruire {svc}")
            client.images.build(path=str(self.repo / build[0]), dockerfile=build[1], tag=image, rm=True)
        ok, detail = secrets.recreate_with_env(svc, {}, client=client, image=image)
        if not ok:
            raise UpdateFailed(f"{svc}: {detail}")
        return old_id


def _compose_build(repo: Path, svc: str) -> tuple[str, str] | None:
    """``services.<svc>.build`` of the global compose → (context, dockerfile relative to it). Read as text (no YAML
    dependency): the file keeps one service per two-space block with ``context:`` / ``dockerfile:`` lines."""
    try:
        text = (repo / "docker-compose.global.yml").read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(rf"^  {re.escape(svc)}:\n(.*?)(?=^  [a-z_][a-z0-9_]*:\n|^\S|\Z)", text, re.M | re.S)
    if not m or not re.search(r"^    build:", m[1], re.M):
        return None
    context = re.search(r"^      context:\s*(\S+)", m[1], re.M)
    dockerfile = re.search(r"^      dockerfile:\s*(\S+)", m[1], re.M)
    return (context[1] if context else "."), (dockerfile[1] if dockerfile else "Dockerfile")


class UpdateRefused(Exception):
    pass


class UpdateFailed(Exception):
    pass
