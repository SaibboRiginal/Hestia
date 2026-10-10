"""Themis core: values, scopes, state, history/undo, presets, proposals.

Archive stores (``/api/settings-store/*`` via Hub), modules declare (registry), Hermes
delivers anything addressed to the user. Themis never applies an assistant's
proposal by itself: only an answer from the user (any client) does.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any

from .hub import Hub, HubError
from .registry import Registry
from .validation import SettingValueError, validate

logger = logging.getLogger("hestia_themis.service")

USER_SCOPES = ("session", "client", "profile")          # resolution order for scope=user definitions
ACTORS_ASSISTANT = {"oracle", "athena"}
HISTORY_KEEP = 10
PROPOSAL_TTL_HOURS = 24
PROFILE_ID = "owner"


class ThemisError(Exception):
    def __init__(self, message: str, status: int = 400, detail: Any = None):
        super().__init__(message)
        self.status = status
        self.detail = detail


def _short(value: Any, limit: int = 80) -> str:
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


class Themis:
    def __init__(self, hub: Hub, registry: Registry):
        self.hub = hub
        self.registry = registry
        self._boot = int(time.time())
        self._counter = 0
        self._lock = threading.Lock()

    # ── revision ────────────────────────────────────────────────────────────
    @property
    def revision(self) -> str:
        return f"{self._boot}-{self._counter}"

    def _bump(self, reason: str) -> str:
        with self._lock:
            self._counter += 1
        logger.info("event=themis_revision revision=%s reason=%s", self.revision, reason)
        return self.revision

    # ── storage (Archive) ───────────────────────────────────────────────────
    def _stored(self, *, key: str | None = None, prefix: str | None = None, scope: str | None = None,
                scope_id: str | None = None) -> list[dict]:
        rows = self.hub.ok("archive", "GET", "api/settings-store/values",
                           query={"key": key, "prefix": prefix, "scope": scope, "scope_id": scope_id})
        return rows if isinstance(rows, list) else []

    def system_values(self, owner: str) -> dict[str, Any]:
        return {r["key"]: r.get("value") for r in self._stored(prefix=f"{owner}.", scope="system")}

    # ── registration ────────────────────────────────────────────────────────
    def register(self, owner: str, definitions: list[dict], presets: list[dict] | None,
                 effective: dict | None) -> dict:
        if not owner or not isinstance(definitions, list):
            raise ThemisError("owner e definitions obbligatori")
        if self.registry.register(owner, definitions, presets, effective):
            self._bump(f"schema:{owner}")
        try:
            values = self.system_values(owner)
        except Exception as exc:
            logger.warning("[🔄] event=themis_archive_unreachable owner=%s error=%s", owner, exc)
            raise ThemisError("archivio non raggiungibile", 503)
        return {"owner": owner, "values": values, "revision": self.revision}

    # ── module state ────────────────────────────────────────────────────────
    def _effective(self, owner: str) -> dict | None:
        try:
            status, payload = self.hub.call(owner, "GET", "api/settings/effective", timeout=3)
            if status < 400 and isinstance(payload, dict):
                self.registry.set_effective(owner, payload.get("values") or {})
                return payload
        except Exception:
            pass
        return None

    def _effective_many(self, owners: list[str]) -> dict[str, dict | None]:
        if not owners:
            return {}
        with ThreadPoolExecutor(max_workers=min(8, len(owners))) as pool:
            return dict(zip(owners, pool.map(self._effective, owners)))

    def _notify_reload(self, owner: str) -> None:
        """Push the owner's stored system values; it applies live ones at once."""
        def _run():
            try:
                self.hub.call(owner, "POST", "api/settings/reload",
                              body={"values": self.system_values(owner)}, timeout=5)
            except Exception as exc:
                logger.warning("[🔄] event=themis_reload_failed owner=%s error=%s "
                               "fallback=module_reregisters", owner, exc)
        threading.Thread(target=_run, daemon=True, name=f"themis-reload-{owner}").start()

    # ── listing ─────────────────────────────────────────────────────────────
    def _user_layers(self, keys: set[str], client: str, session: str) -> dict[str, dict[str, Any]]:
        layers: dict[str, dict[str, Any]] = {s: {} for s in USER_SCOPES}
        wanted = {"profile": PROFILE_ID, "client": client, "session": session}
        for scope, scope_id in wanted.items():
            if not scope_id:
                continue
            for row in self._stored(scope=scope, scope_id=scope_id):
                if row["key"] in keys:
                    layers[scope][row["key"]] = row.get("value")
        return layers

    def list(self, *, module: str | None = None, q: str = "", client: str = "", session: str = "",
             include_status: bool = True) -> dict:
        """Settings with their current value, where it comes from and its state."""
        defs = self.registry.definitions(module, q)
        system_rows = {r["key"]: r for r in self._stored(scope="system")}
        user_keys = {d["key"] for d in defs if d.get("scope") == "user"}
        layers = self._user_layers(user_keys, client, session) if user_keys else {}
        owners = sorted({d["module"] for d in defs if d.get("scope") != "user"})
        effective = self._effective_many(owners) if include_status else {}
        items = []
        for d in defs:
            item = dict(d)
            if d.get("scope") == "user":
                source, value = "default", d.get("default")
                for scope in ("profile", "client", "session")[::-1]:
                    if d["key"] in layers.get(scope, {}):
                        source, value = scope, layers[scope][d["key"]]
                        break
                item.update(value=value, source=source, status="ok")
            else:
                row = system_rows.get(d["key"])
                value = row.get("value") if row else d.get("default")
                item.update(value=value, source="stored" if row else "default",
                            updated_by=(row or {}).get("updated_by"), updated_at=(row or {}).get("updated_at"))
                if include_status:
                    eff = effective.get(d["module"])
                    if eff is None:
                        item["status"] = "offline"
                    elif d.get("apply") == "restart" and (eff.get("values") or {}).get(d["key"]) != value:
                        item["status"] = "restart_required"
                    else:
                        item["status"] = "ok"
            items.append(item)
        return {"revision": self.revision, "items": items, "presets": self.preset_states(module, items)}

    def preset_states(self, module: str | None, items: list[dict]) -> list[dict]:
        """Presets per group with the one matching the current values (else ``custom``)."""
        current = {i["key"]: i.get("value") for i in items}
        out = []
        for owner in ([module] if module else self.registry.modules()):
            by_group: dict[str, list[dict]] = {}
            for p in self.registry.presets(owner):
                by_group.setdefault(p.get("group", ""), []).append(p)
            for group, presets in by_group.items():
                active = next((p["id"] for p in presets
                               if all(current.get(k, object()) == v for k, v in (p.get("values") or {}).items())),
                              "custom")
                out.append({"module": owner, "group": group, "active": active,
                            "presets": [{k: p.get(k) for k in ("id", "label", "help", "values")} for p in presets]})
        return out

    def get(self, key: str, *, client: str = "", session: str = "") -> dict:
        d = self.registry.definition(key)
        if not d:
            raise ThemisError(f"impostazione {key} sconosciuta", 404)
        found = [i for i in self.list(module=d["module"], client=client, session=session)["items"]
                 if i["key"] == key]
        return found[0] if found else dict(d, value=d.get("default"), source="default")

    # ── writing ─────────────────────────────────────────────────────────────
    def _target(self, d: dict, scope: str | None, scope_id: str | None) -> tuple[str, str]:
        if d.get("scope") == "user":
            scope = scope or "profile"
            if scope not in USER_SCOPES:
                raise ThemisError("scope ammessi: profile, client, session")
            scope_id = PROFILE_ID if scope == "profile" else (scope_id or "")
            if not scope_id:
                raise ThemisError(f"scope_id obbligatorio per scope {scope}")
            return scope, scope_id
        if scope not in (None, "", "system"):
            raise ThemisError("questa impostazione vale per tutto il sistema (scope system)")
        return "system", ""

    def set(self, key: str, value: Any, *, scope: str | None = None, scope_id: str | None = None,
            actor: str = "user", reason: str = "") -> dict:
        d = self.registry.definition(key)
        if not d:
            raise ThemisError(f"impostazione {key} sconosciuta", 404)
        if actor in ACTORS_ASSISTANT:
            raise ThemisError("l'assistente può solo proporre modifiche", 403)
        try:
            value = validate(d, value)
        except SettingValueError as exc:
            raise ThemisError(f"{d.get('label') or key}: {exc}", 422)
        scope, scope_id = self._target(d, scope, scope_id)
        self.hub.ok("archive", "PUT", "api/settings-store/values", body={
            "key": key, "scope": scope, "scope_id": scope_id, "value": value, "actor": actor,
            "reason": reason or None, "history_keep": HISTORY_KEEP})
        logger.info("event=themis_setting_set key=%s scope=%s actor=%s", key, scope, actor)
        if scope == "system":
            self._notify_reload(d["module"])
        self._bump(f"set:{key}")
        return {"key": key, "scope": scope, "scope_id": scope_id, "value": value, "revision": self.revision}

    def reset(self, key: str, *, scope: str | None = None, scope_id: str | None = None,
              actor: str = "user") -> dict:
        d = self.registry.definition(key)
        if not d:
            raise ThemisError(f"impostazione {key} sconosciuta", 404)
        scope, scope_id = self._target(d, scope, scope_id)
        self.hub.ok("archive", "DELETE", "api/settings-store/values", query={
            "key": key, "scope": scope, "scope_id": scope_id, "actor": actor, "history_keep": HISTORY_KEEP})
        if scope == "system":
            self._notify_reload(d["module"])
        self._bump(f"reset:{key}")
        return {"key": key, "scope": scope, "value": d.get("default"), "revision": self.revision}

    def history(self, key: str, *, scope: str = "system", scope_id: str = "", limit: int = HISTORY_KEEP) -> list:
        rows = self.hub.ok("archive", "GET", "api/settings-store/history",
                           query={"key": key, "scope": scope, "scope_id": scope_id, "limit": limit})
        return rows if isinstance(rows, list) else []

    def undo(self, key: str, *, scope: str = "system", scope_id: str = "", actor: str = "user") -> dict:
        """Restore the value before the last change (as a new change, so undo is undoable)."""
        rows = self.history(key, scope=scope, scope_id=scope_id, limit=1)
        if not rows:
            raise ThemisError("niente da annullare", 404)
        old = rows[0].get("old_value")
        if old is None:
            return self.reset(key, scope=scope, scope_id=scope_id, actor=actor)
        return self.set(key, old, scope=scope, scope_id=scope_id, actor=actor, reason="annulla")

    def apply_preset(self, module: str, preset_id: str, *, actor: str = "user") -> dict:
        preset = next((p for p in self.registry.presets(module) if p.get("id") == preset_id), None)
        if not preset:
            raise ThemisError("preset sconosciuto", 404)
        applied = {}
        for key, value in (preset.get("values") or {}).items():
            applied[key] = self.set(key, value, actor=actor, reason=f"preset {preset.get('label')}")["value"]
        return {"module": module, "preset": preset_id, "applied": applied, "revision": self.revision}

    def init_session(self, session: str, client: str) -> dict:
        """New chat session: copy profile (+client) values of user settings into the session."""
        keys = {d["key"] for d in self.registry.definitions() if d.get("scope") == "user"}
        layers = self._user_layers(keys, client, "")
        merged = {**layers.get("profile", {}), **layers.get("client", {})}
        for key, value in merged.items():
            self.hub.ok("archive", "PUT", "api/settings-store/values", body={
                "key": key, "scope": "session", "scope_id": session, "value": value,
                "actor": client or "user", "reason": "nuova sessione", "history_keep": 1})
        if merged:
            self._bump(f"session:{session}")
        return {"session": session, "copied": sorted(merged), "revision": self.revision}

    # ── proposals (assistant → user's confirmation via Hermes) ─────────────
    def propose(self, key: str, value: Any, *, proposer: str, reason: str = "",
                scope: str | None = None, scope_id: str | None = None) -> dict:
        d = self.registry.definition(key)
        if not d:
            raise ThemisError(f"impostazione {key} sconosciuta", 404)
        if d.get("oracle", "propose") != "propose":
            raise ThemisError("questa impostazione può cambiarla solo l'utente", 403)
        try:
            value = validate(d, value)
        except SettingValueError as exc:
            raise ThemisError(f"{d.get('label') or key}: {exc}", 422)
        scope, scope_id = self._target(d, scope, scope_id)
        current = self.get(key).get("value")
        if current == value:
            return {"status": "unchanged", "key": key, "value": value}
        for p in self.proposals(status="pending"):
            if p.get("key") == key and p.get("value") == value:
                return {**p, "status": "already_pending"}
        proposal_id = uuid.uuid4().hex[:12]
        row = self.hub.ok("archive", "POST", "api/settings-store/proposals", body={
            "proposal_id": proposal_id, "key": key, "scope": scope, "scope_id": scope_id, "value": value,
            "reason": (reason or "")[:500], "proposer": proposer,
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=PROPOSAL_TTL_HOURS)).isoformat()})
        self._bump(f"proposal:{proposal_id}")
        self._notify_proposal(d, row or {}, current)
        logger.info("event=themis_proposal_created id=%s key=%s proposer=%s", proposal_id, key, proposer)
        return {"status": "pending", **(row or {}), "label": d.get("label"), "current": current}

    def proposals(self, status: str | None = None) -> list[dict]:
        rows = self.hub.ok("archive", "GET", "api/settings-store/proposals", query={"status": status, "limit": 200})
        rows = rows if isinstance(rows, list) else []
        now = datetime.now(timezone.utc)
        out = []
        for p in rows:   # lazy expiry: no timers
            exp = p.get("expires_at")
            if p.get("status") == "pending" and exp:
                try:
                    if datetime.fromisoformat(str(exp).replace("Z", "+00:00")) < now:
                        self._close(p, "expired", "themis", notify=True)
                        p = dict(p, status="expired")
                except (ValueError, ThemisError, HubError):
                    pass
            if status is None or p.get("status") == status:
                out.append(p)
        return out

    def _close(self, proposal: dict, status: str, by: str, notify: bool) -> dict:
        try:
            row = self.hub.ok("archive", "PATCH", f"api/settings-store/proposals/{proposal['proposal_id']}",
                              body={"status": status, "decided_by": by, "only_if_status": "pending"})
        except HubError as exc:
            if exc.status == 409:
                raise ThemisError("proposta già gestita", 409, {"status": "already_decided"})
            raise
        self._bump(f"proposal_{status}:{proposal['proposal_id']}")
        if notify:
            self._emit("settings.proposal_closed", f"settings-proposal-{proposal['proposal_id']}-closed",
                       {"proposal_id": proposal["proposal_id"], "decision": status, "key": proposal.get("key")})
        return row or {}

    def decide(self, proposal_id: str, approve: bool, *, by: str = "user") -> dict:
        found = [p for p in self.proposals() if p.get("proposal_id") == proposal_id]
        if not found:
            raise ThemisError("proposta sconosciuta", 404)
        proposal = found[0]
        if proposal.get("status") != "pending":
            raise ThemisError(f"proposta già {proposal.get('status')}", 409,
                              {"status": "already_decided", "decision": proposal.get("status")})
        if not approve:
            self._close(proposal, "rejected", by, notify=True)
            return {"status": "rejected", "proposal_id": proposal_id}
        self._close(proposal, "approved", by, notify=True)
        result = self._apply_approved(proposal, by)
        return {"status": "approved", "proposal_id": proposal_id, **result}

    def _apply_approved(self, proposal: dict, by: str) -> dict:
        """Write an approved proposal (actor = proposer, so history shows who suggested it)."""
        d = self.registry.definition(proposal["key"]) or {}
        self.hub.ok("archive", "PUT", "api/settings-store/values", body={
            "key": proposal["key"], "scope": proposal.get("scope") or "system",
            "scope_id": proposal.get("scope_id") or "", "value": proposal.get("value"),
            "actor": proposal.get("proposer") or "assistant",
            "reason": f"proposta approvata ({by}): {proposal.get('reason') or ''}"[:500],
            "history_keep": HISTORY_KEEP})
        if (proposal.get("scope") or "system") == "system" and d.get("module"):
            self._notify_reload(d["module"])
        self._bump(f"approved:{proposal['key']}")
        self._emit("settings.changed", f"settings-changed-{proposal['proposal_id']}",
                   {"key": proposal["key"], "label": d.get("label"), "value": proposal.get("value"),
                    "_message": f"✅ Impostazione cambiata: {d.get('label') or proposal['key']} → "
                                f"{_short(proposal.get('value'))}"})
        return {"key": proposal["key"], "value": proposal.get("value"), "revision": self.revision}

    # ── outbound: always through Hermes ─────────────────────────────────────
    def _emit(self, kind: str, entity_id: str, payload: dict) -> None:
        def _run():
            try:
                self.hub.call("hermes", "POST", "api/events/ingest", body={
                    "event_type": "service.action_required" if kind == "settings.proposal" else kind,
                    "domain": "system", "entity_id": entity_id,
                    "payload": {"kind": kind, "service": "themis", "target": "owner",
                                "dedupe_key": entity_id, **payload}}, timeout=8)
            except Exception as exc:
                logger.warning("[🔄] event=themis_hermes_emit_failed kind=%s error=%s "
                               "fallback=panel_banner", kind, exc)
        threading.Thread(target=_run, daemon=True, name="themis-hermes").start()

    def _notify_proposal(self, d: dict, row: dict, current: Any) -> None:
        pid = row.get("proposal_id", "")
        who = {"oracle": "Hestia (chat)", "athena": "Athena"}.get(row.get("proposer"), row.get("proposer"))
        text = (f"⚙️ {who} propone di cambiare «{d.get('label') or d.get('key')}» "
                f"({d.get('module')}): {_short(current)} → {_short(row.get('value'))}.")
        if row.get("reason"):
            text += f"\nMotivo: {row['reason']}"
        actions = [
            {"id": "approve", "label": "Approva", "text": "✅ Approva", "style": "primary", "service": "themis",
             "method": "POST", "path": f"/api/settings/proposals/{pid}/approve", "body": {}},
            {"id": "reject", "label": "Rifiuta", "text": "❌ Rifiuta", "style": "danger", "service": "themis",
             "method": "POST", "path": f"/api/settings/proposals/{pid}/reject", "body": {}},
        ]
        self._emit("settings.proposal", f"settings-proposal-{pid}",
                   {"proposal_id": pid, "key": d.get("key"), "title": "Proposta di modifica impostazione",
                    "_message": text, "_actions": actions})
