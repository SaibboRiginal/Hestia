"""Export / import of the assistant's long-term memory (hestia_common.transfer, dossier 2026-10-20-import-export).

Archive rows have integer ids that mean nothing on another Hestia, so a memory is matched by its class and its
fact text. Conversation history (``conversational_history``) never travels: chats and sessions stay where they
happened (Marko 2026-10-20).
"""
from __future__ import annotations

import hashlib
from typing import Callable

from hestia_common.transfer import Section

SKIP_CLASSES = {"conversational_history"}
CLASS_LABELS = {"durable_user_preference": "Preferenza", "domain_fact_entity": "Fatto", "skill": "Abilità",
                "assistant_commitment": "Impegno", "task_goal_state": "Obiettivo"}


def memory_key(memory_class: str | None, fact: str) -> str:
    norm = " ".join(str(fact or "").lower().split())
    return hashlib.sha1(f"{memory_class or ''}|{norm}".encode()).hexdigest()[:16]


class MemorySection(Section):
    """``route(method, endpoint, body=None, query=None)`` = MemoryService._route_archive (``/memory…`` paths)."""

    def __init__(self, route: Callable[..., object]):
        super().__init__("memorie", "Memorie", icon="memory",
                         help="Quello che l'assistente ricorda di te (preferenze, fatti, abilità). Non le chat.")
        self.route = route

    def _rows(self) -> list[dict]:
        rows = self.route("GET", "/memory/active", query={"limit": 5000})
        if not isinstance(rows, list):
            raise RuntimeError("archivio non raggiungibile")
        return [r for r in rows if isinstance(r, dict) and r.get("memory_class") not in SKIP_CLASSES]

    def records(self, *, deleted: bool = False) -> list[dict]:
        out = []
        for r in self._rows():
            out.append({"key": memory_key(r.get("memory_class"), r.get("fact")), "row_id": r.get("id"),
                        "fact": r.get("fact"), "domain": r.get("domain") or "general",
                        "domains": r.get("domains") or None, "memory_class": r.get("memory_class"),
                        "weight": r.get("weight", 1.0), "extra_data": r.get("extra_data") or None,
                        "updated_at": r.get("updated_at") or r.get("created_at")})
        return out

    def refs(self, rec: dict) -> set[str]:
        return set()

    def title(self, rec: dict) -> str:
        return str(rec.get("fact") or "")[:140]

    def subtitle(self, rec: dict) -> str:
        return " · ".join(x for x in (CLASS_LABELS.get(rec.get("memory_class") or "", rec.get("memory_class") or ""),
                                      rec.get("domain")) if x)

    def same(self, a: dict, b: dict) -> bool:
        keys = ("weight", "extra_data")        # same key = same class and fact (normalized)
        return all((a.get(k) or None) == (b.get(k) or None) for k in keys)

    def write(self, records: list[dict], deletes: list[dict], *, mode: str) -> None:
        current = {r["key"]: r for r in self.records()}
        for r in records:
            have = current.get(r["key"])
            if have and have.get("row_id") is not None:
                ok = self.route("PATCH", f"/memory/{have['row_id']}", body={
                    "is_active": True, "weight": r.get("weight"), "extra_data": r.get("extra_data") or None})
            else:
                ok = self.route("POST", "/memory", body={
                    "fact": r.get("fact"), "domain": r.get("domain") or "general", "weight": r.get("weight", 1.0),
                    "memory_class": r.get("memory_class"), "domains": r.get("domains"),
                    "extra_data": {**(r.get("extra_data") or {}), "imported": True}})
            if ok is None:
                raise RuntimeError("archivio non raggiungibile")
        for d in deletes:
            if d.get("row_id") is not None and self.route("PATCH", f"/memory/{d['row_id']}",
                                                          body={"is_active": False}) is None:
                raise RuntimeError("archivio non raggiungibile")
