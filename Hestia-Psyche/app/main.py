"""Hestia-Psyche — how the owner feels over time («Umore», port 19029, dossier docs/work/2026-10-30-diario-umore).

Data in Archive (``/api/mood-store``), check-ins from a tap, a tool or Oracle's quiet capture from chat
(capability ``mood_capture_endpoint``: no confirmation, merged within ``psyche.capture.merge_minutes``, undone by
«non segnarlo»), trend and insights computed here, reflection signals and weekly metrics for Athena, a recap piece,
the evening check-in as an agenda job, tools for the assistant and Telegram, a WebUI plugin.
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import Body

try:
    import hestia_common  # noqa: F401
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Hestia-Shared"))

from hestia_common import recap
from hestia_common.agenda_client import job_rule
from hestia_common.display import action, display, item
from hestia_common.mcp_helpers import MCPTool, undo
from hestia_common.module_kit import ModuleKit
from hestia_common.plugin_client import page, quick_action, widget
from hestia_common.reminders import reminder_event, reminder_settings
from hestia_common.settings_client import setting
from hestia_common.signals_client import Signals, signals_rule
from hestia_common.transfer import StoreSection, Transfer

from .core.service import CAUSES, LABELS, MOOD_WORDS, Psyche, mood_word

API = "/api/mood"
DOMAIN = "mood"

kit = ModuleKit("psyche", port=19029, api=API, domain=DOMAIN, title="Umore", store="mood-store",
                tags=("context",),
                when_to_use="umore: come si sente l'utente, energia, stress, giornate buone e no, andamento",
                manual="Umore (mood_today, mood_history, mood_insights): come sta l'utente nel tempo. mood_log quando "
                       "chiede di segnare come si sente (mood 1-5, energy, stress, labels, causes). Le frasi in chat "
                       "come «oggi sono stanco» sono già segnate da sole dopo la risposta: non chiamare mood_log per "
                       "quelle e non dire di averle segnate. mood_delete per togliere una voce.")
app = kit.app
kit.settings.declare([
    setting("psyche.capture.merge_minutes", "Unisci frasi vicine", "int", 120, group="Umore", min=0, max=720, order=0,
            unit="minuti", help="Se in chat dici come ti senti più volte a poca distanza, resta una voce sola."),
    setting("psyche.insights.min_days", "Giorni per l'andamento", "int", 7, group="Umore", min=3, max=60, order=1,
            unit="giorni", help="Quanti giorni con l'umore segnato servono prima di mostrare l'andamento."),
    *reminder_settings("psyche", help="La sera, solo se oggi non hai ancora detto come stai: una domanda, tre "
                                      "tasti.", max_per_week=7, order=10),
])
psyche = Psyche(kit.store, kit.settings.get, tz_name=kit.tz)
signals = Signals("psyche", DOMAIN, evaluate=psyche.signals, hub_api_url=kit.hub_url)


def _changed(out):
    signals.changed()
    return out


# ── REST (WebUI plugin, Hermes actions, Oracle capture, agenda jobs) ─────────
@app.get(API)
def list_moods(days: int = 30):
    return psyche.history(days)


@app.post(API)
def add_mood(body: dict = Body(...)):
    return _changed(psyche.log(body))


@app.post(f"{API}/tap")
def tap(body: dict = Body(...)):
    """One tap (Home quick action, widget): only the mood, no model."""
    return _changed(psyche.log({**body, "source": "tap"}))


@app.get(f"{API}/today")
def today():
    return psyche.today_view()


@app.get(f"{API}/history")
def history(days: int = 30):
    return psyche.history(days)


@app.get(f"{API}/insights")
def insights():
    return psyche.insights()


@app.get(f"{API}/options")
def options():
    return {"labels": list(LABELS), "causes": list(CAUSES),
            "levels": [{"value": k, "label": v} for k, v in MOOD_WORDS.items()]}


@app.post(f"{API}/capture")
def capture(body: dict = Body(...)):
    """Oracle's quiet capture (capability ``mood_capture_endpoint``): no confirmation, merged when recent."""
    return _changed(psyche.capture(body))


@app.post(f"{API}/capture/undo")
def capture_undo():
    """«Non segnarlo»: today's last chat capture goes away."""
    return _changed(psyche.undo_capture())


@app.post(f"{API}/signals/run")
def signals_run():
    """Agenda job ``psyche.signals``."""
    return signals.run()


@app.post(f"{API}/checkin")
def checkin():
    """Agenda job ``psyche.checkin``: one question in the evening, only if today has nothing and reminders are on."""
    if not kit.settings.get("psyche.reminder.enabled", False):
        return {"sent": False, "reason": "reminders_off"}
    ask = psyche.checkin()
    if not ask:
        return {"sent": False, "reason": "already_logged"}
    sent = kit.hub.notify(reminder_event(module="psyche", domain=DOMAIN, key=ask["key"], title="Umore",
                                         text=ask["text"], actions=ask["actions"], page="umore"))
    return {"sent": sent}


@app.get("/api/module/context")
def module_context(budget: int = 400, topic: str = ""):
    """Assistant/Athena context contract (tag ``context``): the last 7 days in one line, or the insights."""
    if topic in ("insights", "andamento", "mood_drop", "low_streak", "energy_low", "good_streak"):
        text = " ".join(psyche.insights()["sentences"])
    else:
        text = psyche.context_text(budget)
    return {"module": "psyche", "domain": DOMAIN, "text": text[:max(80, int(budget))]}


@app.put(f"{API}/{{mid}}")
def update_mood(mid: str, body: dict = Body(...)):
    return _changed(psyche.update(mid, body))


@app.delete(f"{API}/{{mid}}")
def delete_mood(mid: str):
    return _changed(psyche.delete(mid))


app.include_router(recap.recap_router("psyche", lambda d, n: recap.piece("psyche", "Umore", icon="smile", order=28,
                                                                         **psyche.recap(d, n)),
                                      today=psyche.today))


# ── tools ────────────────────────────────────────────────────────────────────
def _line(r: dict) -> list[str]:
    meta = [f"{r['mood']}/5 {r['mood_word']}"]
    if r.get("energy"):
        meta.append(f"energia {r['energy']}/5")
    if r.get("labels"):
        meta.append(", ".join(r["labels"][:3]))
    return meta


def _tone(mood: int) -> str:
    return "success" if mood >= 4 else "warning" if mood <= 2 else ""


def _log(mood: int, energy: int | None = None, stress: int | None = None, labels: list | None = None,
         causes: list | None = None, note: str = "", date: str = "", source: str = "") -> dict:
    r = _changed(psyche.log({"mood": mood, "energy": energy, "stress": stress, "labels": labels or [],
                             "causes": causes or [], "note": note, "date": date, "source": source or "telegram"}))
    return {"saved": True, "id": r["id"], "mood": r["mood"], "undo": undo("mood_delete", id=r["id"]),
            "display": display("Umore segnato", lines=[" · ".join(_line(r))],
                               actions=[action("Andamento", "mood_insights")])}


def _today() -> dict:
    t = psyche.today_view()
    s = t["summary"]
    return {**t, "display": display("Umore di oggi",
                                    subtitle=f"{s['mood']}/5 · {s['mood_word']}" if s else "",
                                    items=[item(str(r.get("at", ""))[11:16] or r["date"], _line(r),
                                                tone=_tone(r["mood"])) for r in t["items"][:10]],
                                    lines=[] if s else ["Oggi non hai ancora detto come stai."],
                                    actions=[action("Come stai?", "mood_log", style="primary")])}


def _history(days: int = 30) -> dict:
    h = psyche.history(days)
    st = h["stats"]
    sub = (f"media {st['mood_avg']:.1f}/5 · {st['good_days']} giorni buoni · {st['bad_days']} no"
           if st["mood_avg"] is not None else "")
    return {"days": h["days"], "stats": st,
            "display": display(f"Umore, ultimi {days} giorni", subtitle=sub,
                               items=[item(f"{d['date'][8:10]}/{d['date'][5:7]}", [f"{d['mood']}/5 {d['mood_word']}",
                                                                                 ", ".join(d["labels"][:3])],
                                           tone=_tone(d["mood"])) for d in reversed(h["days"][-20:])],
                               lines=[] if h["days"] else ["Nessun dato in questo periodo."])}


def _insights() -> dict:
    out = psyche.insights()
    return {**out, "display": display("Andamento dell'umore", lines=out["sentences"])}


def _delete(id: str = "", last: bool = False) -> dict:
    if not id and last:
        rows = psyche.entries(psyche.today(), psyche.today())
        if not rows:
            return {"deleted": False, "error": "oggi non c'è niente da togliere"}
        id = rows[-1]["id"]
    return _changed(psyche.delete(id))


S, I, B = {"type": "string"}, {"type": "integer"}, {"type": "boolean"}
LV = {"type": "integer", "minimum": 1, "maximum": 5}
G = "umore"
kit.tools([
    MCPTool(name="mood_log", description="Segna come si sente l'utente: mood 1-5 (1 a terra, 3 così così, 5 "
            "benissimo), energy e stress 1-5, labels, causes, note, date (AAAA-MM-GG o ieri). Solo se lo chiede.",
            summary="Segna come stai.",
            parameters={"type": "object", "properties": {
                "mood": LV, "energy": LV, "stress": LV,
                "labels": {"type": "array", "items": {"type": "string", "enum": list(LABELS)}},
                "causes": {"type": "array", "items": {"type": "string", "enum": list(CAUSES)}},
                "note": S, "date": S}, "required": ["mood"]},
            handler=_log, title="Come stai?", method="POST", clients=["telegram", "ui", "external"], telegram_group=G,
            telegram={"section": "Umore", "primary": 1, "label": "Come stai?"}),
    MCPTool(name="mood_today", description="L'umore di oggi: le voci e il riassunto.", summary="L'umore di oggi.",
            parameters={"type": "object", "properties": {}}, handler=_today, title="Umore di oggi",
            clients=["telegram", "ui", "external"], telegram_group=G, telegram={"section": "Umore", "primary": 2}),
    MCPTool(name="mood_history", description="L'umore degli ultimi giorni (days, default 30): un riassunto per "
            "giorno, medie, giorni buoni e no.", summary="Com'è andato l'umore negli ultimi giorni.",
            parameters={"type": "object", "properties": {"days": I}}, handler=_history, title="Storico umore",
            clients=["telegram", "ui", "external"], telegram_group=G, telegram={"section": "Umore", "primary": 3}),
    MCPTool(name="mood_insights", description="Andamento dell'umore in frasi semplici: media, confronto col mese "
            "prima, giorno della settimana, parole e cause più frequenti.", summary="L'andamento in poche frasi.",
            parameters={"type": "object", "properties": {}}, handler=_insights, title="Andamento",
            clients=["telegram", "ui", "external"], telegram_group=G, telegram={"section": "Umore", "primary": 4}),
    MCPTool(name="mood_delete", description="Togli una voce dell'umore (id) o l'ultima di oggi (last=true).",
            summary="Togli una voce dell'umore.",
            parameters={"type": "object", "properties": {"id": S, "last": B}}, handler=_delete,
            title="Togli voce", method="POST", clients=["telegram", "ui", "external"], telegram_group=G,
            telegram={"section": "Umore"}),
], prefix="mood_")

transfer = Transfer("psyche", kit.hub, sections=[
    StoreSection("umore", "Umore", kit.store, ["mood"], icon="smile",
                 title=lambda r: f"{r['data'].get('date', '')} · {mood_word(r['data'].get('mood'))}"),
])
app.include_router(transfer.router())
kit.caps.update({"mood_capture_endpoint": f"{API}/capture", **recap.capabilities()})
kit.capabilities(transfer.capabilities)
kit.agenda_rules(lambda: [
    job_rule("psyche.checkin", "Umore: com'è andata oggi", service="psyche", path=f"{API}/checkin",
             recurrence="FREQ=DAILY", start_at="2026-01-01T20:30:00", tz=kit.tz,
             description="La sera, se oggi non hai detto come stai e i promemoria dell'umore sono accesi."),
    signals_rule("psyche", "Umore", path=f"{API}/signals/run", tz=kit.tz),
])
kit.on_warm(signals.changed)
kit.webui(icon="smile", color="yellow", description="Come stai nel tempo: giornate, energia, andamento.",
          pages=[page("umore", "Umore", element="psyche-mood", icon="smile", order=240,
                      help="Come ti senti giorno per giorno. Quando in chat dici come stai («oggi sono stanco») "
                           "l'assistente lo segna da solo; qui lo vedi, lo correggi o lo togli.")],
          widgets=[widget("umore", "Umore", element="psyche-widget", sizes=["s", "m"], size="s", auto=True,
                          open_page="umore", icon="smile")],
          quick_actions=[quick_action("come-stai", "Come stai?", "POST", f"{API}/tap", icon="smile", group="Umore",
                                      params={"mood": {"type": "int", "label": "Umore 1-5", "min": 1, "max": 5}},
                                      order=240)])
kit.finish()
