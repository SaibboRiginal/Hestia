"""Export / import of the user's own agenda (hestia_common.transfer, dossier 2026-10-20-import-export).

What travels: items the user created, and module rules the user changed (moved, edited, paused, cancelled) —
the user's decisions. Module defaults left as they are do not travel: every Hestia registers its own.
Run state (last run, attempts, run log) stays where it happened.
"""
from __future__ import annotations

from hestia_common.transfer import Section

from services import agenda

FIELDS = ("type", "owner", "title", "description", "start_at", "end_at", "recurrence", "tz", "status", "action",
          "params", "skips", "overrides", "parent", "created_by", "user_modified")
TYPE_LABELS = {"event": "Evento", "task": "Attività", "job": "Regola ricorrente", "window": "Finestra"}


def _mine(item: dict) -> bool:
    return item.get("created_by") == "user" or bool(item.get("user_modified"))


class AgendaSection(Section):
    def __init__(self):
        super().__init__("agenda", "Agenda", icon="calendar",
                         help="Le voci create da te e le regole dei moduli che hai cambiato (orari, pause, annullate).")

    def records(self, *, deleted: bool = False) -> list[dict]:
        out = []
        for row in agenda._raw_items():
            item = agenda._to_item(row)
            if not item.get("key") or not _mine(item):
                continue
            out.append({"key": item["key"], **{f: item.get(f) for f in FIELDS},
                        "updated_at": row.get("updated_at") or row.get("created_at")})
        return out

    def refs(self, rec: dict) -> set[str]:
        return set()

    def title(self, rec: dict) -> str:
        return str(rec.get("title") or rec["key"])

    def subtitle(self, rec: dict) -> str:
        parts = [TYPE_LABELS.get(rec.get("type") or "", rec.get("type") or ""), str(rec.get("start_at") or "")[:16]]
        if rec.get("status") == "cancelled":
            parts.append("annullata")
        return " · ".join(p for p in parts if p)

    def same(self, a: dict, b: dict) -> bool:
        return all(a.get(f) == b.get(f) for f in FIELDS)

    def write(self, records: list[dict], deletes: list[dict], *, mode: str) -> None:
        current = {i["key"]: i for i in agenda.list_items(include_cancelled=True)}
        with agenda._lock:
            for r in records:
                item = dict(current.get(r["key"]) or {"last_fired": None, "last_result": None, "runs": [],
                                                      "attempts": 0})
                item.update({f: r.get(f) for f in FIELDS})
                item["key"] = r["key"]
                if item.get("created_by") != "user":
                    item["user_modified"] = True     # a module must not overwrite what came from the user
                agenda._save(item)
        for d in deletes:
            if d.get("created_by") == "user" and d.get("status") != "cancelled":
                agenda.cancel(d["key"], by="import")
