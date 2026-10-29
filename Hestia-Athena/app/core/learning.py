"""What the assistant learned, with undo (Cindy 8 + 18, dossier docs/work/2026-10-24-tutto-brainstorm-cindy W3).

- **Learning log**: every change the nightly consolidation makes to the memory (new fact, fact retired by a
  conflict, reinforced pattern, weight decay) is a row of Archive ``/api/athena-store`` (kind ``learning``) with
  ``before`` / ``after`` and, for a new fact, the owner's exact words it comes from (``quote``). «Annulla» restores
  ``before``, but only while the memory is still as the assistant left it: an edit of the owner wins (409).
- **«Rivedi cosa sai di me»** (``memory_rivedi``): exact duplicates are found without a model; then one model call
  (use case ``athena.strategia``) looks for contradictions, near duplicates and stale facts. Nothing is changed:
  each finding is a proposal (kind ``memory_proposal``) sent as a Hermes card «Applica» / «Lascia».
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import requests

logger = logging.getLogger("hestia_athena.learning")

_STORE = "api/athena-store/records"
ACTIONS = ("add", "retire", "reinforce", "decay", "merge")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(text: str) -> str:
    return re.sub(r"[^\w]+", " ", str(text or "").lower()).strip()


def quote_found(quote: str, user_texts: list[str]) -> bool:
    """Cindy 8: a new memory must cite the owner's exact words (normalized: case, punctuation, spaces)."""
    q = _norm(quote)
    if len(q) < 4:
        return False
    return any(q in _norm(t) for t in user_texts)


class Learning:
    def __init__(self, hub_api_url: str):
        self.hub = hub_api_url.rstrip("/")

    # ── transport ───────────────────────────────────────────────────────────
    def _route(self, service: str, method: str, path: str, body: Any = None, query: dict | None = None,
               timeout: float = 10) -> tuple[int, Any]:
        try:
            resp = requests.post(f"{self.hub}/route/{service}/{path.lstrip('/')}",
                                 json={"method": method, "headers": {}, "query": query or {}, "body": body,
                                       "timeout_seconds": timeout}, timeout=timeout + 3)
            routed = resp.json() if resp.content else {}
            return int(routed.get("status_code", resp.status_code)), routed.get("payload")
        except Exception as exc:  # noqa: BLE001
            logger.warning("[🔄] event=athena_learning_route_failed service=%s path=%s error=%s", service, path, exc)
            return 0, None

    def _put(self, kind: str, row_id: str, data: dict, *, ref_id: str | None = None) -> None:
        row = {"kind": kind, "id": row_id, "ref_id": ref_id, "at": data.get("at") or _now(), "data": data,
               "updated_at": _now(), "deleted": False}
        status, _ = self._route("archive", "PUT", _STORE, {"rows": [row]})
        if not status or status >= 400:
            logger.warning("[🔄] event=athena_learning_write_failed kind=%s id=%s", kind, row_id)

    def _rows(self, kind: str, limit: int = 200) -> list[dict]:
        status, payload = self._route("archive", "GET", _STORE, query={"kind": kind, "order": "-at", "limit": limit})
        return [r for r in (payload or {}).get("rows") or [] if isinstance(r, dict)] if status == 200 else []

    def memory(self, memory_id: Any) -> dict | None:
        status, payload = self._route("archive", "GET", f"api/memory/{memory_id}")
        return payload if status == 200 and isinstance(payload, dict) else None

    def _patch_memory(self, memory_id: Any, changes: dict) -> bool:
        status, _ = self._route("archive", "PATCH", f"api/memory/{memory_id}", changes)
        return bool(status) and status < 400

    # ── log ─────────────────────────────────────────────────────────────────
    def record(self, action: str, memory_id: Any, *, before: dict | None, after: dict | None, quote: str = "",
               session_id: str = "", fact: str = "") -> str:
        entry_id = uuid.uuid4().hex[:12]
        self._put("learning", entry_id, {"id": entry_id, "action": action, "memory_id": memory_id,
                                         "fact": fact[:500], "before": before, "after": after,
                                         "quote": quote[:500] or None, "session_id": session_id or None,
                                         "at": _now(), "undone": None}, ref_id=str(memory_id))
        logger.info("event=athena_learned action=%s memory_id=%s quoted=%s", action, memory_id, bool(quote))
        return entry_id

    def log(self, limit: int = 50) -> list[dict]:
        return [r.get("data") or {} for r in self._rows("learning", limit)]

    def undo(self, entry_id: str, by: str = "user") -> tuple[int, dict]:
        entry = next((e for e in self.log(500) if e.get("id") == entry_id), None)
        if not entry:
            return 404, {"status": "not_found"}
        if entry.get("undone"):
            return 409, {"status": "already_undone"}
        current = self.memory(entry["memory_id"])
        after = entry.get("after") or {}
        if current is None:
            return 404, {"status": "memory_gone"}
        changed = {k: v for k, v in after.items() if k in ("is_active", "weight") and current.get(k) != v}
        if changed:
            # The owner (or something else) changed it after the assistant: their edit wins.
            return 409, {"status": "changed_since", "detail": "La memoria è stata cambiata dopo: resta com'è."}
        before = entry.get("before") or {"is_active": False}
        if not self._patch_memory(entry["memory_id"], {k: v for k, v in before.items() if k in ("is_active", "weight")}):
            return 502, {"status": "error", "detail": "archivio non disponibile"}
        entry["undone"] = {"by": by, "at": _now()}
        self._put("learning", entry_id, entry, ref_id=str(entry["memory_id"]))
        logger.info("event=athena_learning_undone entry=%s action=%s by=%s", entry_id, entry["action"], by)
        return 200, {"status": "ok", "entry": entry, "message": "Annullato"}

    # ── memory review (proposals only) ──────────────────────────────────────
    def _active(self) -> list[dict]:
        status, payload = self._route("archive", "GET", "api/memory/active")
        return [m for m in payload or [] if isinstance(m, dict)] if status == 200 and isinstance(payload, list) else []

    @staticmethod
    def exact_duplicates(memories: list[dict]) -> list[dict]:
        seen: dict[str, dict] = {}
        out = []
        for m in sorted(memories, key=lambda m: str(m.get("created_at") or "")):
            key = _norm(m.get("fact"))
            if not key:
                continue
            if key in seen:
                out.append({"kind": "doppione", "keep": seen[key]["id"], "retire": [m["id"]],
                            "why": "Stessa cosa scritta due volte.", "facts": [seen[key]["fact"], m["fact"]]})
            else:
                seen[key] = m
        return out

    def _model_findings(self, memories: list[dict]) -> list[dict]:
        listing = "\n".join(f"[{m['id']}] {str(m.get('fact'))[:200]} (aggiornata {str(m.get('updated_at') or m.get('created_at'))[:10]})"
                            for m in memories[:150])
        prompt = ("Rivedi queste memorie su una persona. Trova SOLO: contraddizioni, doppioni con parole diverse, "
                  "cose probabilmente vecchie. Non inventare. Rispondi SOLO JSON: {\"findings\": [{\"kind\": "
                  "\"contraddizione\"|\"doppione\"|\"vecchia\", \"keep\": id da tenere o null, \"retire\": [id da "
                  "togliere], \"merged\": \"testo unito se doppione, altrimenti vuoto\", \"why\": \"una riga\"}]}\n\n"
                  + listing)
        status, payload = self._route("oracle", "POST", "api/llm/generate",
                                      {"prompt": prompt, "use_case": "athena.strategia"}, timeout=180)
        text = str((payload or {}).get("response") or "") if isinstance(payload, dict) else str(payload or "")
        match = re.search(r"\{.*\}", text, re.S)
        try:
            data = json.loads(match.group(0)) if match else {}
        except ValueError:
            data = {}
        ids = {m["id"] for m in memories}
        out = []
        for f in data.get("findings") or []:
            retire = [i for i in f.get("retire") or [] if i in ids] if isinstance(f, dict) else []
            if retire:
                out.append({"kind": f.get("kind") or "vecchia", "keep": f.get("keep") if f.get("keep") in ids else None,
                            "retire": retire, "merged": str(f.get("merged") or "")[:500],
                            "why": str(f.get("why") or "")[:300],
                            "facts": [next(m["fact"] for m in memories if m["id"] == i) for i in retire]})
        return out

    def review(self, publish) -> dict:
        """Find what to clean up and propose it (``publish(event_type, entity_id, payload)`` → Hermes)."""
        memories = self._active()
        findings = self.exact_duplicates(memories)
        dup_ids = {i for f in findings for i in f["retire"]}
        if len(memories) >= 2:
            findings += [f for f in self._model_findings([m for m in memories if m["id"] not in dup_ids])
                         if not set(f["retire"]) & dup_ids]
        for f in findings[:10]:
            pid = uuid.uuid4().hex[:10]
            self._put("memory_proposal", pid, {**f, "id": pid, "at": _now(), "status": "pending"})
            label = {"doppione": "Doppione", "contraddizione": "Contraddizione"}.get(f["kind"], "Forse vecchia")
            lines = "\n".join(f"• {str(t)[:160]}" for t in f["facts"][:4])
            publish("service.action_required", f"memory.proposal.{pid}", {
                "_title": f"Memoria · {label}", "_source": "Memoria", "_level": "info",
                "_message": f"{f['why']}\n{lines}" + (f"\nDiventa: <i>{f['merged'][:200]}</i>" if f.get("merged") else ""),
                "dedupe_key": f"memory.proposal:{','.join(map(str, sorted(f['retire'])))}",
                "_actions": [{"id": "apply", "label": "Applica", "style": "primary", "service": "athena",
                              "method": "POST", "path": f"/api/athena/memory/proposals/{pid}/apply"},
                             {"id": "keep", "label": "Lascia", "service": "athena", "method": "POST",
                              "path": f"/api/athena/memory/proposals/{pid}/dismiss"}],
                "_link": {"module": "athena", "page": "imparato"}})
        logger.info("event=athena_memory_review memories=%d proposals=%d", len(memories), min(10, len(findings)))
        return {"memories": len(memories), "proposals": min(10, len(findings))}

    def pending_proposals(self) -> list[dict]:
        rows = [r.get("data") or {} for r in self._rows("memory_proposal", 200)]
        return [p for p in rows if p.get("status") == "pending"]

    def _proposal(self, pid: str) -> dict | None:
        return next((r.get("data") for r in self._rows("memory_proposal", 500) if r.get("id") == pid), None)

    def apply(self, pid: str, by: str = "user") -> tuple[int, dict]:
        p = self._proposal(pid)
        if not p:
            return 404, {"status": "not_found"}
        if p.get("status") != "pending":
            return 409, {"status": "already_handled"}
        if p.get("merged") and p.get("keep") is None:
            status, created = self._route("archive", "POST", "api/memory",
                                          {"fact": p["merged"], "memory_class": "durable_user_preference"})
            if status and status < 400 and isinstance(created, dict):
                self.record("merge", created.get("id"), before={"is_active": False}, after={"is_active": True},
                            fact=p["merged"])
        for mid in p["retire"]:
            if self._patch_memory(mid, {"is_active": False}):
                self.record("retire", mid, before={"is_active": True}, after={"is_active": False},
                            fact=f"rivista: {p.get('why') or ''}")
        p.update({"status": "applied", "by": by, "decided_at": _now()})
        self._put("memory_proposal", pid, p)
        return 200, {"status": "ok", "message": "Fatto: memoria sistemata"}

    def dismiss(self, pid: str, by: str = "user") -> tuple[int, dict]:
        p = self._proposal(pid)
        if not p:
            return 404, {"status": "not_found"}
        p.update({"status": "dismissed", "by": by, "decided_at": _now()})
        self._put("memory_proposal", pid, p)
        return 200, {"status": "ok", "message": "Lasciata com'è"}
