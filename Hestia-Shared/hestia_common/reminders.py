"""Module reminders — one shape for every module (settings + Hermes event).

Rules (docs/ARCHITECTURE.md, Messaging): reminders are off until the user turns them on, at most
``max_per_week``, and only one stays live per thing — Hermes ``replaces`` supersedes the previous one and
counts the skips. The schedule is an agenda job (``agenda_client.job_rule``); the module decides whether
to send.

    from hestia_common.reminders import reminder_settings, reminder_event, voice_setting

    settings.declare([..., *reminder_settings("hercules", help="Solo se sei indietro con l'obiettivo."),
                      voice_setting("hercules", True)])
    if settings.get("hercules.reminder.enabled"):
        hub.call("hermes", "POST", "api/events/ingest", body=reminder_event(
            module="hercules", domain="fitness", key="hercules.reminder", title="Allenamento",
            text=text, actions=actions, page="allenamento", voice=settings.get("hercules.notifiche.voce")))
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


def voice_setting(module: str, default: bool, *, group: str = "Promemoria", help: str = "", order: int = 9) -> dict:
    """``<module>.notifiche.voce``: whether this module's notifications also arrive as a voice message
    (dossier docs/work/2026-10-20-modulo-voce §7.3). Each module picks its own default: on where a notification
    reads well aloud (reminders, recaps), off where it is a list or numbers. Pass the value to
    ``reminder_event(voice=...)``; the written notification never changes."""
    return setting(f"{module}.notifiche.voce", "Notifiche anche a voce", "bool", bool(default), group=group,
                   order=order, help=help or "Oltre al testo ricevi un vocale (Telegram) o un tasto play (sito).")


def reminder_event(*, module: str, domain: str, key: str, title: str, text: str, actions: list[dict],
                   page: str = "", level: str = "info", kind: str = "", voice: bool = False,
                   question: dict[str, Any] | None = None) -> dict[str, Any]:
    """Hermes ``/api/events/ingest`` body for a reminder or alert of ``module``.

    ``key`` is the thread (one live notification per key, Hermes ``replaces``); actions that end it carry
    ``resolves: true``; ``page`` opens the module's plugin page from the notification (``_link``).
    The envelope domain is ``system``: Hermes' standing owner subscription listens there; the module's
    own domain travels in the payload.
    ``question`` asks like the chat card (dossier docs/work/2026-10-30-domande-nelle-notifiche): ``{kind:
    confirm|single_choice|multi_choice|free_text, options, allow_other, service, path, method?, body?}``; the answer
    reaches ``path`` as ``{...body, answer, answers, client, notification_id}``."""
    payload: dict[str, Any] = {
        "kind": kind or key, "service": module, "source": module, "domain": domain, "_source": module,
        "_title": title, "target": "owner", "replaces": key, "level": level, "_message": text,
        "_actions": list(actions or [])}
    if page:
        payload["_link"] = {"module": module, "page": page}
    if voice:
        payload["_voice"] = True             # Hermes asks the voice module for an audio copy
    if question:
        payload["_question"] = dict(question)
    return {"event_type": "service.action_required", "domain": "system", "entity_id": key, "payload": payload}
