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

STEPS = ("cervello", "voce", "telegram", "backup", "esterni", "fuori")
CODE_TTL = 600
CODE_TRIES = 5
# Modules that re-read their provider keys from their own .env without a restart: (path, key prefix).
LIVE = {"oracle": ("/api/llm/setup/reload-keys", "ORACLE_KEY_"),
        "echo": ("/api/voice/setup/reload-keys", "ECHO_KEY_")}
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
        data = self.hardware_raw()
        return {k: data.get(k) for k in ("os", "ram_gb", "gpu", "vram_gb", "free_gb", "lan_ip") if k in data}

    def role(self) -> str:
        """«tutto» (whole stack here), «centrale» (always-on core) or «satellite»: written by the installer."""
        return str(self.hardware_raw().get("role") or "tutto")

    def hardware_raw(self) -> dict[str, Any]:
        try:
            return json.loads((self.repo / ".hestia-install" / "hardware.json").read_text(encoding="utf-8-sig"))
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
            "voice": saved.get("voice", {}),
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
        """Write each secret into its .env, then make each affected container see it: Oracle and Echo re-read
        their provider keys in a second (``LIVE``); any other key, or a failed re-read, re-creates the
        container once with all of its values. ``applied`` = the container has the new values."""
        by_service: dict[str, dict[str, str]] = {}
        for key, value in values.items():
            target = secrets.set_secret(self.repo, key, value)
            for service in target.services:
                by_service.setdefault(service, {})[key] = secrets.validate(key, value)
        results = {}
        for service, updates in by_service.items():
            if self._reload_live(service, updates):
                results[service] = {"reloaded": True, "recreated": False, "applied": True, "healthy": True,
                                    "detail": ""}
                continue
            ok, detail = self.recreate(service, updates)
            healthy = ok and (self.health(service) if self.health else True)
            results[service] = {"reloaded": False, "recreated": ok, "applied": ok, "healthy": healthy,
                                "detail": "" if ok else detail}
        return {"keys": sorted(values), "services": results}

    def _reload_live(self, service: str, updates: dict[str, str]) -> bool:
        """The module re-reads its own .env (``POST …/setup/reload-keys``) and names the keys it now has."""
        live = LIVE.get(service)
        if not live or self.hub_call is None or not all(k.startswith(live[1]) for k in updates):
            return False
        try:
            answer = self.hub_call(service, live[0], method="POST", body={}, timeout=10)
            names = set((answer or {}).get("keys") or [])
        except Exception as exc:
            logger.warning("[🔄] event=setup_reload_keys_failed service=%s error=%s — re-creating", service,
                           str(exc)[:160])
            return False
        if not set(updates) <= names:
            logger.warning("[🔄] event=setup_reload_keys_missing service=%s — re-creating", service)
            return False
        logger.info("event=setup_keys_reloaded service=%s keys=%s", service, ",".join(sorted(updates)))
        return True

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
                    claude_token: str = "", local_provider: str = "ollama",
                    cloud_models: dict[str, list[str] | str] | None = None, embedding: dict[str, str] | None = None,
                    local_runtime: dict[str, str] | None = None,
                    modes: dict[str, dict[str, Any]] | None = None,
                    order: list[dict[str, str]] | None = None) -> dict[str, Any]:
        values = {f"ORACLE_KEY_{name.upper().replace('-', '_')}": key for name, key in keys.items() if key}
        if claude_token:
            values["CLAUDE_CODE_OAUTH_TOKEN"] = claude_token
        if values:
            done = self.set_secrets(values)
            oracle = done["services"].get("oracle", {})
            if not oracle.get("applied", True):
                return {"ok": False, "detail": "Non sono riuscito a riavviare il cervello con le chiavi nuove."}
            if oracle.get("recreated"):
                self._wait_oracle()
        local_provider = local_provider or "ollama"
        emb = {k: v for k, v in (embedding or {}).items() if v}
        result = self.oracle("POST", "/api/llm/setup/apply",
                             body={"recipe": recipe, "local_model": local_model, "local_provider": local_provider,
                                   "cloud": cloud, "cloud_models": cloud_models or {}, "embedding": emb,
                                   "local_runtime": local_runtime or {}, "modes": modes or {},
                                   "order": order or []})
        # Only Ollama downloads by itself; LM Studio, Jan… already have the model the user picked from their list.
        pulls = []
        if local_model and recipe != "cloud" and local_provider == "ollama":
            pulls.append(local_model)
        if (emb.get("provider") or "ollama") == "ollama" and (emb or (local_model and recipe != "cloud")):
            # The memory's model: the installer already pulls the default one, so this is usually «già presente».
            pulls.append(emb.get("model") or EMBEDDING_MODEL)
        for v in (modes or {}).values():
            for step in ([s for s in v.get("steps") or [] if isinstance(s, dict)] or [v]):
                if (step.get("provider") or "ollama") == "ollama" and step.get("model") and step["model"] not in pulls:
                    pulls.append(step["model"])
        for model in pulls:
            self.oracle("POST", "/api/llm/setup/pull", body={"model": model})
        self.mark("cervello", brain={"recipe": recipe, "local_model": local_model, "local_provider": local_provider,
                                     "cloud": cloud, "cloud_models": cloud_models or {},
                                     "embedding": emb, "modes": {k: {"provider": v.get("provider", ""), "model": v.get("model", ""),
                                                                      "steps": [{"provider": s.get("provider", ""),
                                                                                 "model": s.get("model", "")}
                                                                                for s in v.get("steps") or []
                                                                                if isinstance(s, dict)]}
                                                                  for k, v in (modes or {}).items()},
                                     "order": [{"provider": o.get("provider", ""), "model": o.get("model", "")}
                                               for o in (order or [])],
                                     "summary": result.get("detail", "")})
        return {"ok": True, "detail": result.get("detail", "")}

    def brain_hello(self) -> dict[str, Any]:
        """«I modelli sono pronti»: the assistant writes its first message with the models just chosen, so the user
        sees them answer (Oracle's general chain through the use case ``hephaestus.setup``)."""
        prompt = ("Sei Hestia, assistente personale. Primo messaggio all'utente, appena configurata. Italiano, 2 frasi "
                  "brevi e calde: sei pronta, chiedi da cosa iniziare. Niente emoji, niente elenchi.")
        try:
            out = self.oracle("POST", "/api/llm/generate", body={"prompt": prompt, "use_case": "hephaestus.setup"},
                              timeout=120)
        except Exception as exc:
            logger.warning("[🔄] event=setup_hello_failed error=%s", str(exc)[:200])
            return {"ok": False, "detail": "I modelli non hanno risposto. Controlla le chiavi o il programma locale."}
        text = str(out.get("response") or "").strip()
        if not text:
            return {"ok": False, "detail": str(out.get("detail") or "I modelli non hanno risposto.")[:300]}
        return {"ok": True, "text": text[:600], "model": out.get("model", ""), "provider": out.get("provider", "")}

    def echo(self, method: str, path: str, body: dict | None = None, timeout: float = 30,
             query: dict | None = None) -> dict:
        if self.hub_call is None:
            raise RuntimeError("hub not available")
        return self.hub_call("echo", path, method=method, body=body, query=query, timeout=timeout)

    def voice_key(self, provider: str, key: str) -> bool:
        """«Salva e prova» of a speech service: ``ECHO_KEY_<NAME>`` into Echo's .env, which Echo re-reads at once
        (re-created and waited for only when that fails)."""
        name = "ECHO_KEY_" + "".join(c if c.isalnum() else "_" for c in provider.upper())
        echo = self.set_secrets({name: key})["services"].get("echo", {})
        if not echo.get("applied"):
            return False
        if echo.get("reloaded"):
            return True
        deadline = time.time() + 90
        while time.time() < deadline:
            try:
                self.echo("GET", "/health", timeout=3)
                return True
            except Exception:
                time.sleep(2)
        logger.warning("[🔄] event=setup_echo_slow_restart waited=90")
        return True

    def _wait_oracle(self, timeout: float = 90) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                self.oracle("GET", "/health", timeout=3)
                return
            except Exception:
                time.sleep(2)
        logger.warning("[🔄] event=setup_oracle_slow_restart waited=%s", timeout)
