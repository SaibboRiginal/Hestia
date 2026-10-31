"""Guided setup «Benvenuto» — the orchestration behind the WebUI screens (docs/work/2026-10-30-setup-un-click §4.2).

Hephaestus owns it because it already holds the repo (``/repo``, where the ``.env`` files live) and the Docker socket
(to re-create a container with a new secret). It never decides anything: every value comes from the person on the
setup screen. The brain itself is Oracle's (catalog, «Prova», chains, model downloads): this file only forwards.

State (``data/setup.json``): when the setup was completed, the steps left for later. Hardware: what the installer
detected (``/repo/.hestia-install/hardware.json``, git-ignored), so the screen can say «Scheda video da 16 GB».
"""
from __future__ import annotations

import json
import logging
import secrets as pysecrets
import threading
import time
from pathlib import Path
from typing import Any, Callable

from . import secrets

logger = logging.getLogger("hestia_hephaestus.setup")

STEPS = ("cervello", "telegram", "backup", "esterni")
CODE_TTL = 600
CODE_TRIES = 5
EMBEDDING_MODEL = "qwen3-embedding:0.6b"   # same as Oracle's llm_setup.EMBEDDING_MODEL


class SetupService:
    def __init__(self, repo: Path, data_dir: Path, hub_call: Callable[..., dict] | None = None,
                 recreate: Callable[..., tuple[bool, str]] | None = None, health: Callable[[str], bool] | None = None):
        self.repo = repo
        self.state_path = data_dir / "setup.json"
        self.hub_call = hub_call
        self.recreate = recreate or secrets.recreate_with_env
        self.health = health
        self._lock = threading.Lock()
        self._code: dict[str, Any] = {}

    # ── state ────────────────────────────────────────────────────────────
    def _load(self) -> dict[str, Any]:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save(self, data: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.state_path)

    def hardware(self) -> dict[str, Any]:
        try:
            data = json.loads((self.repo / ".hestia-install" / "hardware.json").read_text(encoding="utf-8-sig"))
            return {k: data.get(k) for k in ("os", "ram_gb", "gpu", "vram_gb", "free_gb") if k in data}
        except Exception:
            return {}

    def state(self) -> dict[str, Any]:
        saved = self._load()
        telegram = {"token": secrets.is_set(self.repo, "TELEGRAM_BOT_TOKEN"),
                    "owner": secrets.is_set(self.repo, "ALLOWED_USER_ID")}
        return {
            "completed": bool(saved.get("completed_at")),
            "completed_at": saved.get("completed_at"),
            "later": saved.get("later", []),
            "brain": saved.get("brain", {}),
            "hardware": self.hardware(),
            "telegram": {**telegram, "linked": telegram["token"] and telegram["owner"],
                         "code_active": self._code_active()},
            "backup": {"passphrase": secrets.is_set(self.repo, "HESTIA_BACKUP_PASSPHRASE")},
            "claude": {"token": secrets.is_set(self.repo, "CLAUDE_CODE_OAUTH_TOKEN")},
        }

    def mark(self, step: str = "", later: bool = False, completed: bool = False, **extra) -> dict[str, Any]:
        with self._lock:
            data = self._load()
            if step and later and step in STEPS:
                data["later"] = sorted(set(data.get("later", [])) | {step})
            elif step:
                data["later"] = [s for s in data.get("later", []) if s != step]
            if completed:
                data["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            data.update(extra)
            self._save(data)
        logger.info("event=setup_marked step=%s later=%s completed=%s", step or "-", later, completed)
        return self.state()

    # ── secrets ──────────────────────────────────────────────────────────
    def set_secrets(self, values: dict[str, str]) -> dict[str, Any]:
        """Write each secret into its .env, then re-create each affected container once with all of its values."""
        by_service: dict[str, dict[str, str]] = {}
        for key, value in values.items():
            target = secrets.set_secret(self.repo, key, value)
            for service in target.services:
                by_service.setdefault(service, {})[key] = secrets.validate(key, value)
        results = {}
        for service, updates in by_service.items():
            ok, detail = self.recreate(service, updates)
            healthy = ok and (self.health(service) if self.health else True)
            results[service] = {"recreated": ok, "healthy": healthy, "detail": "" if ok else detail}
        return {"keys": sorted(values), "services": results}

    # ── Telegram: link the owner with a one-time code ────────────────────────
    def _code_active(self) -> bool:
        return bool(self._code) and self._code.get("expires", 0) > time.time()

    def new_code(self) -> dict[str, Any]:
        with self._lock:
            self._code = {"code": f"{pysecrets.randbelow(10**6):06d}", "expires": time.time() + CODE_TTL, "tries": 0}
        logger.info("event=setup_telegram_code_issued ttl=%s", CODE_TTL)
        return {"code": self._code["code"], "expires_in": CODE_TTL}

    def claim(self, code: str, user_id: str) -> dict[str, Any]:
        """Called by Telegram (setup mode, no owner yet) with what someone wrote to the bot."""
        with self._lock:
            if not self._code_active():
                return {"ok": False, "reason": "no_code"}
            if not pysecrets.compare_digest(str(code).strip(), self._code["code"]):
                self._code["tries"] += 1
                if self._code["tries"] >= CODE_TRIES:
                    self._code = {}
                    logger.warning("event=setup_telegram_code_burned reason=too_many_tries")
                return {"ok": False, "reason": "wrong_code"}
            self._code = {}
        user_id = str(user_id).strip()
        secrets.set_secret(self.repo, "ALLOWED_USER_ID", user_id)
        logger.info("event=setup_telegram_owner_linked")
        # Telegram is answering this very request: re-create it a moment later, after its reply has left.
        threading.Timer(3.0, lambda: self.recreate("telegram", {"ALLOWED_USER_ID": user_id})).start()
        return {"ok": True}

    # ── Oracle (the brain) through the Hub ───────────────────────────────────
    def oracle(self, method: str, path: str, body: dict | None = None, query: dict | None = None,
               timeout: float = 30) -> dict:
        if self.hub_call is None:
            raise RuntimeError("hub not available")
        return self.hub_call("oracle", path, method=method, body=body, query=query, timeout=timeout)

    def apply_brain(self, recipe: str, local_model: str, cloud: list[str], keys: dict[str, str],
                    claude_token: str = "") -> dict[str, Any]:
        values = {f"ORACLE_KEY_{name.upper().replace('-', '_')}": key for name, key in keys.items() if key}
        if claude_token:
            values["CLAUDE_CODE_OAUTH_TOKEN"] = claude_token
        if values:
            done = self.set_secrets(values)
            if not done["services"].get("oracle", {}).get("recreated", True):
                return {"ok": False, "detail": "Non sono riuscito a riavviare il cervello con le chiavi nuove."}
            self._wait_oracle()
        result = self.oracle("POST", "/api/llm/setup/apply",
                             body={"recipe": recipe, "local_model": local_model, "cloud": cloud})
        if local_model and recipe != "cloud":
            # The memory's model too: the installer already pulls it, so this is usually a quick «già presente».
            for model in (local_model, EMBEDDING_MODEL):
                self.oracle("POST", "/api/llm/setup/pull", body={"model": model})
        self.mark("cervello", brain={"recipe": recipe, "local_model": local_model, "cloud": cloud,
                                     "summary": result.get("detail", "")})
        return {"ok": True, "detail": result.get("detail", "")}

    def _wait_oracle(self, timeout: float = 90) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                self.oracle("GET", "/health", timeout=3)
                return
            except Exception:
                time.sleep(2)
        logger.warning("[🔄] event=setup_oracle_slow_restart waited=%s", timeout)
