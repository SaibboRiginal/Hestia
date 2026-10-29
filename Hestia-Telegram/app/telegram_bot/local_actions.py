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
    return Rendered(ui.outcome("Nuova conversazione") + "\n" + ui.note("Ripartiamo da zero: scrivimi pure."))


def _voce(chat_id, args, on: bool | None = None):
    from telegram_bot.services import voice_service
    value = (not voice_service.is_live(chat_id)) if on is None else on
    voice_service.set_live(chat_id, value)
    text = ("Ai tuoi vocali rispondo anche a voce." if value
            else "Rispondo solo in testo; sotto ogni risposta c'è «Ascolta».")
    return Rendered(ui.card("Risposte a voce: " + ("sì" if value else "no"), [ui.esc(text)]),
                    rows=[[ui.button("Spegni" if value else "Accendi", "n:voce")]])


def _aiuto(chat_id, args):
    from telegram_bot.menu import model
    menu = model.current()
    lines = [
        "Scrivimi come a una persona: capisco frasi, vocali, foto e file.",
        "• <b>Oggi</b>: la tua giornata",
        "• <b>Aree</b>: ogni cosa che so fare, divisa per argomento",
        "• <b>Notifiche</b>: cosa aspetta una risposta",
        "• <b>Impostazioni</b>: chat, menu, voce",
        ui.note("Rispondi a un mio messaggio per parlarmi proprio di quello."),
    ]
    shortcuts = "\n".join(f"/{t.command} — {ui.esc(menu.label(t.name))}"
                          for t in sorted(catalog.all_tools(), key=lambda t: t.command) if t.name in menu.tool_area)
    return Rendered(ui.card("Come si usa", lines, detail=f"<b>Scorciatoie da scrivere</b>\n{shortcuts}"),
                    rows=[[ui.button("Aree", "n:aree"), ui.button("Impostazioni", "n:imp")]])


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
        raise ActionError("La pagina web non risponde, riprova tra poco.") from exc


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
    lines = [f"Valido {hours} ore; il codice precedente non vale più."]
    rows = []
    if base:
        rows.append([ui.button("Apri la pagina web", url=f"{base}?token={token}")])
    else:
        lines.append(ui.note("Indirizzo pubblico non attivo: apri la pagina dal computer di casa."))
    rows.append([ui.button("Copia il codice", copy=token)])
    logger.info("event=webui_token_generated chat_id=%s", chat_id)
    return Rendered(ui.card("Accesso alla pagina web", [ui.esc(lines[0]), *lines[1:]]), rows=rows)


def _webui_revoke(chat_id, args):
    _webui("POST", "revoke-token")
    logger.info("event=webui_token_revoked chat_id=%s", chat_id)
    return Rendered(ui.outcome("Accesso revocato") + "\n" + ui.note("Per entrare di nuovo serve un codice nuovo."))


def _webui_status(chat_id, args):
    data = _webui("GET", "token-status")
    active = bool(data.get("active"))
    lines = [f"{ui.tone_dot('success' if active else 'warning')} {'Attivo' if active else 'Nessun accesso attivo'}"]
    if active and data.get("remaining_hours") is not None:
        lines.append(f"Scade tra {ui.esc(data.get('remaining_hours'))} ore")
    return Rendered(ui.card("Accesso alla pagina web", lines),
                    actions=[Action("Nuovo codice", "webui_token")] + ([Action("Revoca", "webui_revoke",
                                                                              style="danger")] if active else []))


# ── documents saved in memory ────────────────────────────────────────────────

def _documenti(chat_id, args):
    ok, docs = catalog.route("archive", "api/documents", query={"chat_id": str(chat_id), "limit": 20}, timeout=10)
    if not ok:
        raise ActionError("Non riesco a leggere i documenti adesso.")
    docs = docs if isinstance(docs, list) else (docs or {}).get("items", []) if isinstance(docs, dict) else []
    if not docs:
        return Rendered(ui.card("Documenti salvati", [ui.note("Nessun documento: mandami un file per salvarlo.")]))
    lines, actions = [], []
    for d in docs[:12]:
        title = d.get("title") or d.get("filename") or "Documento"
        meta = ["fisso" if d.get("is_permanent") else "", str(d.get("created_at") or "")[:10]]
        lines.append(ui.item(title, [m for m in meta if m]))
        actions.append(Action(f"Elimina {ui.label(title, 14)}", "documento_elimina",
                              {"document_id": str(d.get("document_id"))}))
        if not d.get("is_permanent"):
            actions.append(Action(f"Tieni {ui.label(title, 14)}", "documento_fissa",
                                  {"document_id": str(d.get("document_id"))}))
    return Rendered(ui.card("Documenti salvati", lines, subtitle=f"{len(docs)} in memoria"), actions=actions[:12])


def _documento_fissa(chat_id, args):
    doc_id = str(args.get("document_id") or "")
    ok, _ = catalog.route("archive", f"api/documents/{doc_id}/permanent", "PATCH", body={"is_permanent": True})
    if not ok:
        raise ActionError("Non sono riuscita a tenerlo.")
    return Rendered(ui.outcome("Lo tengo per sempre"), actions=[Action("Documenti", "documenti")])


def _documento_elimina(chat_id, args):
    doc_id = str(args.get("document_id") or "")
    ok, _ = catalog.route("archive", f"api/documents/{doc_id}", "DELETE")
    if not ok:
        raise ActionError("Non sono riuscita a eliminarlo.")
    return Rendered(ui.outcome("Documento eliminato"), actions=[Action("Documenti", "documenti")])


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
        raise ActionError("Non sono riuscita a salvarlo, riprova tra poco.")
    return result if isinstance(result, dict) else {}


def _nuovo_promemoria(chat_id, args):
    _calendar_item("reminder", args)
    from telegram_bot.inputs import human_datetime
    return Rendered(ui.outcome("Promemoria salvato") + "\n" + ui.item(
        str(args.get("title") or ""), [human_datetime(str(args.get("start_at") or ""))]))


def _nuova_attivita(chat_id, args):
    _calendar_item("task", args)
    return Rendered(ui.outcome("Attività salvata") + "\n" + ui.item(str(args.get("title") or "")))


def _nuovo_avviso(chat_id, args):
    ok, payload = catalog.route("oracle", "api/subscriptions/compile", "POST", body={
        "message": str(args.get("request") or ""), "session_id": core.get_session(str(chat_id)),
        "notify_target": str(chat_id)}, timeout=30)
    if not ok:
        raise ActionError("Non sono riuscita a creare l'avviso, riprova tra poco.")
    text = str((payload or {}).get("message") or "Avviso creato.") if isinstance(payload, dict) else "Avviso creato."
    return Rendered(ui.outcome("Avviso automatico") + "\n" + ui.esc(ui.strip_emoji(text)),
                    actions=[Action("Avvisi attivi", "notifiche_attive")])


def _pausa_voto(chat_id, args):
    until = core.snooze_feedback(str(chat_id))
    if not until:
        raise ActionError("Non sono riuscita, riprova tra poco.")
    return Rendered(ui.outcome("Niente richieste di voto") + "\n" + ui.note(f"Fino al {until[:10]}."))


def tools() -> list[catalog.Tool]:
    T = catalog.Tool
    dt = {"type": "string", "format": "date-time", "title": "Quando"}
    return [
        T("nuova", "Nuova conversazione", "Riparte da zero: la chat di prima viene dimenticata", group="sistema",
          hints={"section": "Chat"}, writes=True, handler=_nuova),
        T("voce", "Risposte a voce", "Accende o spegne le risposte a voce ai vocali", group="sistema",
          hints={"section": "Chat"}, handler=_voce),
        T("voce_on", "Accendi risposte a voce", "", group="sistema", hints={"section": "interno"},
          handler=lambda c, a: _voce(c, a, on=True)),
        T("voce_off", "Spegni risposte a voce", "", group="sistema", hints={"section": "interno"},
          handler=lambda c, a: _voce(c, a, on=False)),
        T("aiuto", "Come si usa", "Guida rapida e scorciatoie", group="sistema", hints={"section": "Chat"},
          handler=_aiuto),
        T("webui_token", "Accesso alla pagina web", "Un codice per entrare nella pagina web", group="sistema",
          hints={"section": "Pagina web", "primary": 3, "label": "Accesso web"}, writes=False,
          handler=_webui_token),
        T("webui_status", "Stato accesso web", "", group="sistema", hints={"section": "Pagina web"},
          handler=_webui_status),
        T("webui_revoke", "Revoca accesso web", "Chiude l'accesso alla pagina web", group="sistema",
          hints={"section": "Pagina web"}, writes=True, destructive=True, handler=_webui_revoke),
        T("documenti", "Documenti salvati", "I file che mi hai mandato e che ricordo", group="memoria",
          hints={"section": "Documenti", "primary": 4}, handler=_documenti),
        T("documento_fissa", "Tieni un documento", "", group="memoria", hints={"section": "Documenti"},
          schema=_schema({"document_id": {**S, "title": "Documento"}}, ["document_id"]), writes=True,
          handler=_documento_fissa),
        T("documento_elimina", "Elimina un documento", "", group="memoria", hints={"section": "Documenti"},
          schema=_schema({"document_id": {**S, "title": "Documento"}}, ["document_id"]), writes=True,
          destructive=True, handler=_documento_elimina),
        T("nuovo_promemoria", "Nuovo promemoria", "Ti avviso al momento giusto", group="giornata",
          hints={"section": "Promemoria e attività", "primary": 5},
          schema=_schema({"title": {**S, "title": "Di cosa"}, "start_at": dt,
                          "note": {**S, "title": "Nota"}}, ["title", "start_at"]),
          writes=True, handler=_nuovo_promemoria),
        T("nuova_attivita", "Nuova attività", "Una cosa da fare, con o senza scadenza", group="giornata",
          hints={"section": "Promemoria e attività"},
          schema=_schema({"title": {**S, "title": "Cosa"}, "due": {"type": "string", "format": "date",
                                                                   "title": "Entro quando"},
                          "note": {**S, "title": "Nota"}}, ["title"]),
          writes=True, handler=_nuova_attivita),
        T("nuovo_avviso", "Nuovo avviso automatico", "Dimmi cosa tenere d'occhio e quando avvisarti",
          group="notifiche", hints={"section": "Avvisi automatici", "primary": 1},
          schema=_schema({"request": {**S, "title": "Cosa devo tenere d'occhio?",
                                      "examples": ["case a Udine sotto 150.000 €"]}}, ["request"]),
          writes=True, handler=_nuovo_avviso),
        T("pausa_voto", "Basta richieste di voto", "Per qualche giorno non ti chiedo di votare le risposte",
          group="sistema", hints={"section": "Chat"}, writes=True, handler=_pausa_voto),
        *transfer_tools(),
    ]


def transfer_tools() -> list[catalog.Tool]:
    from telegram_bot import transfer_actions
    return transfer_actions.tools()
