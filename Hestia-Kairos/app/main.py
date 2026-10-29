"""Hestia-Kairos — deadlines with advice («Scadenze», port 19028, dossier docs/work/2026-10-24-tutto-brainstorm-cindy W5 B7).

Data in Archive (``/api/deadlines-store``), each open deadline in the calendar (agenda events), mails by push from
Iris (subscription ``kairos:mail``: only proposals the owner confirms), notices through Hermes, the daily check in
the agenda, a better advice from Oracle (use case ``kairos.consiglio``), tools for the assistant and Telegram.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

from fastapi import Body

try:
    import hestia_common  # noqa: F401
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Hestia-Shared"))

from hestia_common import recap
from hestia_common.agenda_client import AgendaClient, job_rule
from hestia_common.display import action, display, item
from hestia_common.mail_client import MailClient, mail_rule
from hestia_common.mcp_helpers import MCPTool, undo
from hestia_common.plugin_client import page, widget
from hestia_common.module_kit import ModuleKit, StoreUnavailable
from hestia_common.oracle_usecases import capabilities as llm_capabilities, usecase
from hestia_common.settings_client import setting
from hestia_common.transfer import StoreSection, Transfer

from .core.service import CATEGORIES, RECURRENCES, Deadlines

API = "/api/deadlines"
DOMAIN = "deadlines"
MAIL_KEY = "mail"
ADVICE_USE = "kairos.consiglio"
DEFAULT_MAIL_WORDS = ["scadenza", "scade", "bolletta", "fattura", "rinnovo", "bollo", "revisione", "polizza",
                      "pagamento"]

kit = ModuleKit("kairos", port=19028, api=API, domain=DOMAIN, title="Scadenze", store="deadlines-store",
                when_to_use="scadenze: bollette, assicurazioni, bollo, revisione, tagliando, documenti, abbonamenti",
                manual="Scadenze (scadenze_list): titolo, data, importo, ricorrenza, preavviso e un consiglio. "
                       "scadenze_add per una nuova, scadenze_done quando è pagata/fatta (le ricorrenti passano da "
                       "sole alla prossima). Le email con una scadenza diventano proposte che l'utente conferma.")
app = kit.app
kit.settings.declare([
    setting("kairos.mail.words", "Parole delle email con scadenze", "list", list(DEFAULT_MAIL_WORDS), group="Email",
            order=0, help="Le email con una di queste parole nell'oggetto arrivano a Scadenze, che propone la "
                          "scadenza solo se c'è una data chiara."),
])
agenda = AgendaClient("kairos", kit.hub_url)
deadlines = Deadlines(kit.store, kit.settings.get, tz_name=kit.tz, hub=kit.hub, agenda=agenda)
mail = MailClient("kairos", kit.hub_url)
_mail_lock = threading.Lock()


# ── REST (WebUI plugin, Hermes actions, Iris push) ───────────────────────────
@app.get(API)
def list_deadlines(status: str = "open", days: int | None = None, category: str = ""):
    return {"items": deadlines.list(status, days, category)}


@app.post(API)
def add_deadline(body: dict = Body(...)):
    return deadlines.save(body)


@app.get(f"{API}/categories")
def categories():
    return {"categories": [{"key": k, "label": v[0], "lead_days": v[1], "advice": v[2]} for k, v in CATEGORIES.items()],
            "recurrences": list(RECURRENCES)}


@app.post(f"{API}/daily")
def daily():
    """Agenda job ``kairos.daily``."""
    return deadlines.daily()


@app.post(f"{API}/mail")
def mail_delivered(body: dict = Body(default={})):
    """Iris rang: mails are waiting in Archive → proposals (async)."""
    threading.Thread(target=process_pending_mail, daemon=True, name="kairos-mail").start()
    return {"status": "started"}


@app.get(f"{API}/{{did}}")
def get_deadline(did: str):
    return deadlines.view(deadlines.find(did))


@app.put(f"{API}/{{did}}")
def update_deadline(did: str, body: dict = Body(...)):
    return deadlines.save(body, did)


@app.delete(f"{API}/{{did}}")
def delete_deadline(did: str):
    return deadlines.delete(did)


@app.post(f"{API}/{{did}}/done")
def done(did: str):
    return deadlines.done(did)


@app.post(f"{API}/{{did}}/snooze")
def snooze(did: str, body: dict = Body(default={})):
    return deadlines.snooze(did, int(body.get("days") or 3))


@app.post(f"{API}/{{did}}/confirm")
def confirm(did: str):
    return deadlines.confirm(did)


@app.post(f"{API}/{{did}}/dismiss")
def dismiss(did: str):
    return deadlines.dismiss(did)


app.include_router(recap.recap_router("kairos", lambda d, n: recap.piece("kairos", "Scadenze", icon="clock", order=15,
                                                                         **deadlines.recap(d, n)),
                                      today=deadlines.today))


def process_pending_mail() -> dict:
    """Pending ``deadlines`` mail records in Archive (stored by Iris) → proposals; mark evaluated."""
    if not _mail_lock.acquire(blocking=False):
        return {"status": "busy"}
    try:
        try:
            pending = kit.hub.ok("archive", "GET", f"api/archive/{DOMAIN}/unevaluated", timeout=15) or []
        except Exception as exc:
            kit.logger.warning("[🔄] event=kairos_mail_pending_failed error=%s fallback=next_ring", exc)
            return {"status": "error"}
        proposed = 0
        for record in pending if isinstance(pending, list) else []:
            try:
                out = deadlines.from_mail(record)
                proposed += out.get("status") == "proposed"
                kit.hub.ok("archive", "PATCH", f"api/archive/{record['id']}", body={"evaluation": out}, timeout=10)
            except StoreUnavailable as exc:
                kit.logger.warning("[🔄] event=kairos_mail_store_down error=%s fallback=next_ring", exc)
                break
            except Exception as exc:
                kit.logger.warning("[🔄] event=kairos_mail_record_failed id=%s error=%s", record.get("id"), exc)
        return {"status": "ok", "processed": len(pending or []), "proposed": proposed}
    finally:
        _mail_lock.release()


def _mail_rules() -> list[dict]:
    words = kit.settings.get("kairos.mail.words", DEFAULT_MAIL_WORDS) or DEFAULT_MAIL_WORDS
    return [mail_rule(MAIL_KEY, "Email con scadenze", path=f"{API}/mail", domain=DOMAIN, subject_contains=words,
                      description="Bollette, rinnovi, avvisi: Scadenze propone la scadenza, tu confermi.")]


def _settings_changed(changed: dict) -> None:
    if "kairos.mail.words" in changed:
        mail.refresh()


kit.settings.on_change(_settings_changed)


# ── tools ────────────────────────────────────────────────────────────────────
def _when(d: dict) -> str:
    return "scaduta" if d["in_days"] < 0 else "oggi" if d["in_days"] == 0 else f"tra {d['in_days']} g"


def _card(d: dict) -> dict:
    lines = [f"{d['category_label']} · {d['due'][8:10]}/{d['due'][5:7]}/{d['due'][:4]} ({_when(d)})"]
    if d.get("amount"):
        lines.append(f"Importo: {d['amount']:.2f} €")
    if d.get("recurrence") and d["recurrence"] != "none":
        lines.append(f"Ricorrenza: {d['recurrence']}")
    if d.get("advice"):
        lines.append(d["advice"])
    return display(d["title"], lines=lines,
                   actions=[action("Fatto", "scadenze_done", {"deadline": d["id"]}, style="primary"),
                            action("Fra 3 giorni", "scadenze_snooze", {"deadline": d["id"], "days": 3}),
                            action("Consiglio", "scadenze_consiglio", {"deadline": d["id"]})])


def _list(days: int | None = None, category: str = "", status: str = "open") -> dict:
    items = deadlines.list(status, days, category)
    return {"count": len(items), "items": [{"id": d["id"], "title": d["title"], "due": d["due"], "in_days": d["in_days"],
                                            "amount": d.get("amount"), "status": d["status"]} for d in items],
            "display": display("Scadenze", items=[item(d["title"], [_when(d)] + ([f"{d['amount']:.2f} €"]
                                                                               if d.get("amount") else []))
                                                  for d in items[:30]],
                               lines=[] if items else ["Nessuna scadenza."],
                               actions=[action("Aggiungi", "scadenze_add", style="primary")])}


def _add(title: str, due: str, category: str = "", amount: float | None = None, recurrence: str = "none",
         lead_days: int | None = None, notes: str = "") -> dict:
    d = deadlines.save({"title": title, "due": due, "category": category, "amount": amount, "recurrence": recurrence,
                        "lead_days": lead_days, "notes": notes})
    return {"saved": True, "id": d["id"], "undo": undo("scadenze_delete", deadline=d["id"]), "display": _card(d)}


def _update(deadline: str, title: str = "", due: str = "", amount: float | None = None, recurrence: str = "",
            lead_days: int | None = None, notes: str = "") -> dict:
    body = {k: v for k, v in {"title": title, "due": due, "amount": amount, "recurrence": recurrence,
                              "lead_days": lead_days, "notes": notes}.items() if v not in (None, "")}
    d = deadlines.save(body, deadlines.find(deadline)["id"])
    return {"saved": True, "display": _card(d)}


def _advice(deadline: str) -> dict:
    """Oracle writes a short, practical advice for this deadline; the category one stays when it is offline."""
    d = deadlines.view(deadlines.find(deadline))
    text = kit.hub.llm(f"Scadenza: {d['title']} ({d['category_label']}), il {d['due']}"
                       + (f", {d['amount']:.2f} €" if d.get("amount") else "")
                       + (f". Note: {d['notes']}" if d.get("notes") else "")
                       + ". Dai 1-2 consigli pratici, italiano, max 300 caratteri, niente premesse.",
                       use_case=ADVICE_USE, max_tokens=200)
    if not text or not text.strip():
        return {"saved": False, "advice": d["advice"], "display": _card(d)}
    d = deadlines.set_advice(d["id"], text.strip())
    return {"saved": True, "advice": d["advice"], "display": _card(d)}


S, I, N = {"type": "string"}, {"type": "integer"}, {"type": "number"}
D = {"type": "string", "description": "id o parte del titolo della scadenza"}
CAT = {"type": "string", "enum": list(CATEGORIES)}
REC = {"type": "string", "enum": list(RECURRENCES)}
G = "scadenze"
kit.tools([
    MCPTool(name="scadenze_list", description="Le scadenze aperte (days = entro quanti giorni; category; "
            "status open|proposed|done).",
            parameters={"type": "object", "properties": {"days": I, "category": CAT, "status": S}}, handler=_list,
            title="Scadenze", clients=["telegram", "ui"], telegram_group=G, telegram={"section": "Scadenze", "primary": 1}),
    MCPTool(name="scadenze_get", description="Una scadenza con consiglio e importo.",
            parameters={"type": "object", "properties": {"deadline": D}, "required": ["deadline"]},
            handler=lambda deadline: (lambda d: {**d, "display": _card(d)})(deadlines.view(deadlines.find(deadline))),
            title="Scadenza", clients=["telegram", "ui"], telegram_group=G, telegram={"section": "Scadenze"}),
    MCPTool(name="scadenze_add", description="Nuova scadenza: title, due AAAA-MM-GG, category, amount €, recurrence "
            "(monthly, yearly…), lead_days di preavviso. Va nel calendario.",
            parameters={"type": "object", "properties": {"title": S, "due": S, "category": CAT, "amount": N,
                                                         "recurrence": REC, "lead_days": I, "notes": S},
                        "required": ["title", "due"]},
            handler=_add, title="Nuova scadenza", method="POST", clients=["telegram", "ui"], telegram_group=G,
            telegram={"section": "Scadenze", "primary": 2}),
    MCPTool(name="scadenze_update", description="Modifica una scadenza.",
            parameters={"type": "object", "properties": {"deadline": D, "title": S, "due": S, "amount": N,
                                                         "recurrence": REC, "lead_days": I, "notes": S},
                        "required": ["deadline"]},
            handler=_update, title="Modifica scadenza", method="POST", clients=["telegram", "ui"], telegram_group=G,
            telegram={"section": "Scadenze"}),
    MCPTool(name="scadenze_done", description="Segna pagata/fatta: le ricorrenti passano alla prossima data.",
            parameters={"type": "object", "properties": {"deadline": D}, "required": ["deadline"]},
            handler=lambda deadline: (lambda d: {"saved": True, "status": d["status"], "next_due": d["due"],
                                                 "display": _card(d)})(deadlines.done(deadline)),
            title="Fatto", method="POST", clients=["telegram", "ui"], telegram_group=G,
            telegram={"section": "Scadenze", "primary": 3}),
    MCPTool(name="scadenze_snooze", description="Rimanda l'avviso di qualche giorno (days, default 3).",
            parameters={"type": "object", "properties": {"deadline": D, "days": I}, "required": ["deadline"]},
            handler=lambda deadline, days=3: {"saved": True, "until": deadlines.snooze(deadline, days)["snoozed_until"]},
            title="Rimanda avviso", method="POST", clients=["telegram", "ui"], telegram_group=G,
            telegram={"section": "Scadenze"}),
    MCPTool(name="scadenze_delete", description="Elimina una scadenza (e dal calendario).",
            parameters={"type": "object", "properties": {"deadline": D}, "required": ["deadline"]},
            handler=lambda deadline: deadlines.delete(deadline), title="Elimina scadenza", method="POST",
            clients=["telegram", "ui"], telegram_group=G, telegram={"section": "Scadenze"}),
    MCPTool(name="scadenze_consiglio", description="Un consiglio pratico su questa scadenza (lo salva sulla scheda).",
            parameters={"type": "object", "properties": {"deadline": D}, "required": ["deadline"]}, handler=_advice,
            title="Consiglio", method="POST", clients=["telegram", "ui"], telegram_group=G,
            telegram={"section": "Scadenze", "primary": 4}),
], prefix="scadenze_")

transfer = Transfer("kairos", kit.hub, sections=[
    StoreSection("scadenze", "Scadenze", kit.store, ["deadline"], icon="clock", title=lambda r: r["data"].get("title", "")),
])
app.include_router(transfer.router())
kit.caps.update({**recap.capabilities(), **llm_capabilities([
    usecase(ADVICE_USE, "Scadenze · consigli", chain="veloce", help="Un consiglio pratico breve su una scadenza.")])})
kit.capabilities(transfer.capabilities)
kit.agenda_rules(lambda: [job_rule("kairos.daily", "Scadenze: avvisi", service="kairos", path=f"{API}/daily",
                                   recurrence="FREQ=DAILY", start_at="2026-01-01T08:30:00", tz=kit.tz,
                                   description="Un avviso al preavviso e uno il giorno della scadenza.")])
kit.on_warm(lambda: (mail.subscribe_async(_mail_rules), process_pending_mail()))
kit.webui(icon="clock", color="orange", description="Bollette, assicurazioni, bollo, revisione, documenti: avvisi e consigli.",
          pages=[page("scadenze", "Scadenze", element="kairos-list", icon="clock", order=70,
                      help="Le scadenze con il preavviso, quelle trovate nelle email da confermare, un consiglio per "
                           "ognuna. «Fatto» sposta le ricorrenti alla prossima data."),
                 page("scadenza/:id", "Scadenza", element="kairos-detail", detail=True, parent="scadenze")],
          widgets=[widget("prossime", "Scadenze", element="kairos-widget", sizes=["s", "m", "l"], size="m", auto=True,
                          open_page="scadenze", icon="clock")])
kit.finish()
