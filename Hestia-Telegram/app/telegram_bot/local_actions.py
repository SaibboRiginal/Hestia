"""Actions that belong to the Telegram client itself (docs/work/2026-10-23-telegram-da-zero §5.2): new conversation,
voice answers, help, WebUI access, saved documents, quick reminder/task, a new automatic alert.

They are ``catalog.Tool`` like every module tool (same flow, same confirm, same result card), with a ``handler``
instead of an MCP call. A handler returns a payload (rendered by ``render``) or a ready ``Rendered``.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

import requests

from telegram_bot import catalog, core, ui
from telegram_bot.render import Action, Rendered
from hestia_common.i18n import t as tr  # fixed texts in the owner's language

logger = logging.getLogger("hestia_telegram.local_actions")

S = {"type": "string"}


class ActionError(Exception):
    """A local action failed: the message is already a sentence for the user."""
    user_facing = True


def _schema(props: dict | None = None, required: list | None = None) -> dict:
    return {"type": "object", "properties": props or {}, "required": required or []}


# ── chat ─────────────────────────────────────────────────────────────────────

def _nuova(chat_id, args):
    old = core.get_session(str(chat_id))
    ok, _ = catalog.route("oracle", f"api/chat/{old}", "DELETE", timeout=8)
    if not ok:
        logger.info("[🔄] event=chat_history_purge_failed session=%s fallback=new_session_only", old)
    core.reset_session(str(chat_id))
    return Rendered(ui.outcome(tr("New conversation")) + "\n" + ui.note(tr("Let's start from scratch: write to me.")))


def _voce(chat_id, args, on: bool | None = None):
    from telegram_bot.services import voice_service
    value = (not voice_service.is_live(chat_id)) if on is None else on
    voice_service.set_live(chat_id, value)
    text = (tr("I also answer your voice messages aloud.") if value
            else tr("I answer only in text; under each answer there is «Listen»."))
    return Rendered(ui.card(tr("Voice replies: ") + (tr("yes") if value else "no"), [ui.esc(text)]),
                    rows=[[ui.button(tr("Turn off") if value else tr("Turn on"), "n:voice")]])


def _aiuto(chat_id, args):
    from telegram_bot.menu import model
    menu = model.current()
    lines = [
        tr("Write to me like to a person: I understand sentences, voice messages, photos and files."),
        tr("• <b>Today</b>: your day"),
        tr("• <b>Areas</b>: everything I can do, by topic"),
        tr("• <b>Notifications</b>: what waits for an answer"),
        tr("• <b>Settings</b>: chat, menu, voice"),
        ui.note(tr("Reply to one of my messages to talk about exactly that.")),
    ]
    shortcuts = "\n".join(f"/{t.command} — {ui.esc(menu.label(t.name))}"
                          for t in sorted(catalog.all_tools(), key=lambda t: t.command) if t.name in menu.tool_area)
    return Rendered(ui.card(tr("How to use it"), lines, detail=tr("<b>Shortcuts to type</b>\n{0}", shortcuts)),
                    rows=[[ui.button(tr("Areas"), "n:areas"), ui.button(tr("Settings"), "n:imp")]])


# ── WebUI access (Telegram → WebUI admin API: the one guarded exception to Hub-only) ──

def _webui_url() -> str:
    return os.getenv("WEBUI_API_URL", "http://hestia_webui:19015").rstrip("/")


def _webui_headers() -> dict:
    secret = os.getenv("WEBUI_ADMIN_SECRET", "").strip()
    return {"X-WebUI-Admin-Secret": secret} if secret else {}


def _webui(method: str, path: str) -> dict:
    try:
        resp = requests.request(method, f"{_webui_url()}/api/webui/admin/{path}", headers=_webui_headers(),
                                timeout=10)
        resp.raise_for_status()
        return resp.json() if resp.content else {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("event=webui_admin_failed path=%s error=%s", path, exc)
        raise ActionError(tr("The web page does not answer, try again shortly.")) from exc


def public_webui_url() -> str:
    url = os.getenv("WEBUI_PUBLIC_URL", "").rstrip("/")
    if url:
        return url
    try:
        return str(_webui("GET", "public-url").get("public_url") or "").rstrip("/")
    except ActionError:
        return ""


def _webui_token(chat_id, args):
    data = _webui("POST", "generate-token")
    token = str(data.get("token") or "")
    try:
        hours = int(float(data.get("lifetime_hours") or 72))
    except (TypeError, ValueError):
        hours = 72
    base = os.getenv("WEBUI_PUBLIC_URL", "").rstrip("/") or str(data.get("public_url") or "").rstrip("/") \
        or public_webui_url()
    lines = [tr("Valid {0} hours; the previous code no longer works.", hours)]
    rows = []
    if base:
        rows.append([ui.button(tr("Open the web page"), url=f"{base}?token={token}")])
    else:
        lines.append(ui.note(tr("Public address not active: open the page from your home computer.")))
    rows.append([ui.button(tr("Copy the code"), copy=token)])
    logger.info("event=webui_token_generated chat_id=%s", chat_id)
    return Rendered(ui.card(tr("Access to the web page"), [ui.esc(lines[0]), *lines[1:]]), rows=rows)


def _webui_revoke(chat_id, args):
    _webui("POST", "revoke-token")
    logger.info("event=webui_token_revoked chat_id=%s", chat_id)
    return Rendered(ui.outcome(tr("Access revoked")) + "\n" + ui.note(tr("To get in again you need a new code.")))


def _webui_status(chat_id, args):
    data = _webui("GET", "token-status")
    active = bool(data.get("active"))
    lines = [f"{ui.tone_dot('success' if active else 'warning')} {tr('Active') if active else tr('No active access')}"]
    if active and data.get("remaining_hours") is not None:
        lines.append(tr("Expires in {0} hours", ui.esc(data.get('remaining_hours'))))
    return Rendered(ui.card(tr("Access to the web page"), lines),
                    actions=[Action(tr("New code"), "webui_token")] + ([Action(tr("Revoke"), "webui_revoke",
                                                                              style="danger")] if active else []))


# ── documents saved in memory ────────────────────────────────────────────────

def _documenti(chat_id, args):
    ok, docs = catalog.route("archive", "api/documents", query={"chat_id": str(chat_id), "limit": 20}, timeout=10)
    if not ok:
        raise ActionError(tr("I can't read the documents right now."))
    docs = docs if isinstance(docs, list) else (docs or {}).get("items", []) if isinstance(docs, dict) else []
    if not docs:
        return Rendered(ui.card(tr("Saved documents"), [ui.note(tr("No documents: send me a file to save it."))]))
    lines, actions = [], []
    for d in docs[:12]:
        title = d.get("title") or d.get("filename") or tr("Document")
        meta = ["pinned" if d.get("is_permanent") else "", str(d.get("created_at") or "")[:10]]
        lines.append(ui.item(title, [m for m in meta if m]))
        actions.append(Action(tr("Delete {0}", ui.label(title, 14)), "document_delete",
                              {"document_id": str(d.get("document_id"))}))
        if not d.get("is_permanent"):
            actions.append(Action(tr("Keep {0}", ui.label(title, 14)), "document_pin",
                                  {"document_id": str(d.get("document_id"))}))
    return Rendered(ui.card(tr("Saved documents"), lines, subtitle=tr("{0} in memory", len(docs))), actions=actions[:12])


def _documento_fissa(chat_id, args):
    doc_id = str(args.get("document_id") or "")
    ok, _ = catalog.route("archive", f"api/documents/{doc_id}/permanent", "PATCH", body={"is_permanent": True})
    if not ok:
        raise ActionError(tr("I couldn't keep it."))
    return Rendered(ui.outcome(tr("I keep it forever")), actions=[Action(tr("Documents"), "documents")])


def _documento_elimina(chat_id, args):
    doc_id = str(args.get("document_id") or "")
    ok, _ = catalog.route("archive", f"api/documents/{doc_id}", "DELETE")
    if not ok:
        raise ActionError(tr("I couldn't delete it."))
    return Rendered(ui.outcome(tr("Document deleted")), actions=[Action(tr("Documents"), "documents")])


# ── quick reminder / task / alert ────────────────────────────────────────────

def _calendar_item(kind: str, args: dict) -> dict:
    when = str(args.get("start_at") or args.get("due") or "")
    if when and "T" not in when:
        when = f"{when}T09:00:00"
    start = datetime.fromisoformat(when) if when else datetime.now()
    body = {"external_id": None, "source": "hestia", "kind": kind, "title": str(args.get("title") or "").strip(),
            "description": str(args.get("note") or "").strip() or None, "start_at": start.isoformat(),
            "end_at": (start + timedelta(hours=1)).isoformat(), "all_day": not args.get("start_at"),
            "location": None, "status": "confirmed", "nag_enabled": True}
    ok, result = catalog.route("archive", "api/calendar/items", "POST", body=body)
    if not ok:
        raise ActionError(tr("I couldn't save it, try again shortly."))
    return result if isinstance(result, dict) else {}


def _nuovo_promemoria(chat_id, args):
    _calendar_item("reminder", args)
    from telegram_bot.inputs import human_datetime
    return Rendered(ui.outcome(tr("Reminder saved")) + "\n" + ui.item(
        str(args.get("title") or ""), [human_datetime(str(args.get("start_at") or ""))]))


def _nuova_attivita(chat_id, args):
    _calendar_item("task", args)
    return Rendered(ui.outcome(tr("Task saved")) + "\n" + ui.item(str(args.get("title") or "")))


def _nuovo_avviso(chat_id, args):
    ok, payload = catalog.route("oracle", "api/subscriptions/compile", "POST", body={
        "message": str(args.get("request") or ""), "session_id": core.get_session(str(chat_id)),
        "notify_target": str(chat_id)}, timeout=30)
    if not ok:
        raise ActionError(tr("I couldn't create the alert, try again shortly."))
    text = str((payload or {}).get("message") or tr("Alert created.")) if isinstance(payload, dict) else tr("Alert created.")
    return Rendered(ui.outcome(tr("Automatic alert")) + "\n" + ui.esc(ui.strip_emoji(text)),
                    actions=[Action(tr("Active alerts"), "notifications_active")])


def _pausa_voto(chat_id, args):
    until = core.snooze_feedback(str(chat_id))
    if not until:
        raise ActionError(tr("I couldn't, try again shortly."))
    return Rendered(ui.outcome(tr("No rating requests")) + "\n" + ui.note(tr("Until {0}.", until[:10])))


def tools() -> list[catalog.Tool]:
    T = catalog.Tool
    dt = {"type": "string", "format": "date-time", "title": "When"}
    return [
        T("new", "New conversation", "Starts from scratch: the previous chat is forgotten", group="system",
          hints={"section": "Chat"}, writes=True, handler=_nuova),
        T("voice", "Voice replies", "Turns voice replies to voice messages on or off", group="system",
          hints={"section": "Chat"}, handler=_voce),
        T("voice_on", "Turn on voice replies", "", group="system", hints={"section": "interno"},
          handler=lambda c, a: _voce(c, a, on=True)),
        T("voice_off", "Turn off voice replies", "", group="system", hints={"section": "interno"},
          handler=lambda c, a: _voce(c, a, on=False)),
        T("aiuto", "How to use it", "Quick guide and shortcuts", group="system", hints={"section": "Chat"},
          handler=_aiuto),
        T("webui_token", "Access to the web page", "A code to enter the web page", group="system",
          hints={"section": "Web page", "primary": 3, "label": "Web access"}, writes=False,
          handler=_webui_token),
        T("webui_status", "Web access status", "", group="system", hints={"section": "Web page"},
          handler=_webui_status),
        T("webui_revoke", "Revoke web access", "Closes access to the web page", group="system",
          hints={"section": "Web page"}, writes=True, destructive=True, handler=_webui_revoke),
        T("documents", "Saved documents", "The files you sent me that I remember", group="memory",
          hints={"section": "Documents", "primary": 4}, handler=_documenti),
        T("document_pin", "Keep a document", "", group="memory", hints={"section": "Documents"},
          schema=_schema({"document_id": {**S, "title": "Document"}}, ["document_id"]), writes=True,
          handler=_documento_fissa),
        T("document_delete", "Delete a document", "", group="memory", hints={"section": "Documents"},
          schema=_schema({"document_id": {**S, "title": "Document"}}, ["document_id"]), writes=True,
          destructive=True, handler=_documento_elimina),
        T("new_reminder", "New reminder", "I'll remind you at the right time", group="day",
          hints={"section": "Reminders and tasks", "primary": 5},
          schema=_schema({"title": {**S, "title": "About what"}, "start_at": dt,
                          "note": {**S, "title": "Note"}}, ["title", "start_at"]),
          writes=True, handler=_nuovo_promemoria),
        T("new_activity", "New task", "Something to do, with or without a deadline", group="day",
          hints={"section": "Reminders and tasks"},
          schema=_schema({"title": {**S, "title": "What"}, "due": {"type": "string", "format": "date",
                                                                   "title": "By when"},
                          "note": {**S, "title": "Note"}}, ["title"]),
          writes=True, handler=_nuova_attivita),
        T("new_alert", "New automatic alert", "Tell me what to keep an eye on and when to alert you",
          group="notifications", hints={"section": "Automatic alerts", "primary": 1},
          schema=_schema({"request": {**S, "title": "What should I keep an eye on?",
                                      "examples": ["houses in Udine under €150,000"]}}, ["request"]),
          writes=True, handler=_nuovo_avviso),
        T("rating_paused", "No more rating requests", "For a few days I won't ask you to rate answers",
          group="system", hints={"section": "Chat"}, writes=True, handler=_pausa_voto),
        *transfer_tools(),
    ]


def transfer_tools() -> list[catalog.Tool]:
    from telegram_bot import transfer_actions
    return transfer_actions.tools()
