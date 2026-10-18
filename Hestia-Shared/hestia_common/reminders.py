"""Module reminders — one shape for every module (settings + Hermes event).

Rules (docs/ARCHITECTURE.md, Messaging): reminders are off until the user turns them on, at most
``max_per_week``, and only one stays live per thing — Hermes ``replaces`` supersedes the previous one and
counts the skips. The schedule is an agenda job (``agenda_client.job_rule``); the module decides whether
to send.

    from hestia_common.reminders import reminder_settings, reminder_event

    settings.declare([..., *reminder_settings("hercules", help="Solo se sei indietro con l'obiettivo.")])
    if settings.get("hercules.reminder.enabled"):
        hub.call("hermes", "POST", "api/events/ingest", body=reminder_event(
            module="hercules", domain="fitness", key="hercules.reminder", title="Allenamento",
            text=text, actions=actions, page="allenamento"))
"""
from __future__ import annotations

from typing import Any

from .settings_client import setting


def reminder_settings(module: str, *, group: str = "Promemoria", help: str = "", max_per_week: int = 2,
                      order: int = 0) -> list[dict]:
    """``<module>.reminder.enabled`` (off) and ``<module>.reminder.max_per_week``: the same two settings
    everywhere. Per-item choices (e.g. which routine) stay in the module's own data."""
    key = f"{module}.reminder.enabled"
    return [
        setting(key, "Promemoria", "bool", False, group=group, order=order,
                help=help or "Uno alla volta: il nuovo sostituisce il precedente e conta quante volte l'hai saltato."),
        setting(f"{module}.reminder.max_per_week", "Promemoria massimi a settimana", "int", max_per_week,
                group=group, min=1, max=7, order=order + 1, depends_on={"key": key, "equals": True}),
    ]


def reminder_event(*, module: str, domain: str, key: str, title: str, text: str, actions: list[dict],
                   page: str = "", level: str = "info", kind: str = "") -> dict[str, Any]:
    """Hermes ``/api/events/ingest`` body for a reminder or alert of ``module``.

    ``key`` is the thread (one live notification per key, Hermes ``replaces``); actions that end it carry
    ``resolves: true``; ``page`` opens the module's plugin page from the notification (``_link``).
    The envelope domain is ``system``: Hermes' standing owner subscription listens there; the module's
    own domain travels in the payload."""
    payload: dict[str, Any] = {
        "kind": kind or key, "service": module, "source": module, "domain": domain, "_source": module,
        "_title": title, "target": "owner", "replaces": key, "level": level, "_message": text,
        "_actions": list(actions or [])}
    if page:
        payload["_link"] = {"module": module, "page": page}
    return {"event_type": "service.action_required", "domain": "system", "entity_id": key, "payload": payload}
