"""Hestia-Plutus — expenses (domain ``finance``): PayPal mails by push, bank statements (Hype PDF), quick entry,
categories that learn, budgets, recurring payments, statistics.

SPEC docs/work/2026-10-19-email-push-spese §4. Data in Archive (``/api/finance-store``, PDFs in ``/api/blobs``),
mails pushed by Iris (subscription ``plutus:paypal``), settings in Themis, schedules in the agenda (Chronos),
notifications through Hermes, UI as a plugin bundle (``ui/``), assistant tools over MCP, text understanding via
Oracle only when the deterministic parsers cannot.
"""
from __future__ import annotations

import os
import sys
import threading
from datetime import timedelta
from pathlib import Path
from typing import Any

import requests
from fastapi import Body, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

try:
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging
except ModuleNotFoundError:
    _shared = Path(__file__).resolve().parents[2] / "Hestia-Shared"
    if str(_shared) not in sys.path:
        sys.path.insert(0, str(_shared))
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging

from hestia_common import recap
from hestia_common.agenda_client import AgendaClient, job_rule
from hestia_common.coach import CoachClient, CoachRouter
from hestia_common.mail_client import MailClient, mail_rule
from hestia_common.oracle_usecases import capabilities as llm_capabilities, usecase as llm_usecase
from hestia_common.plugin_client import PluginClient, page, quick_action, widget
from hestia_common.reminders import reminder_event, reminder_settings, voice_setting
from hestia_common.transfer import StoreSection, Transfer
from hestia_common.settings_client import SettingsClient, setting
from hestia_common.signals_client import Signals, signals_rule

from .core.coach import REVIEW_NEED, PlutusCoach
from .core.hub import Hub
from .core.service import Invalid, NotFound, Plutus
from .core.statements import Statements
from .core.store import Store, StoreUnavailable, now_iso

logger, log_buffer = setup_service_logging("hestia_plutus")

SERVICE_NAME = os.getenv("SERVICE_NAME", "plutus")
SERVICE_BASE_URL = os.getenv("SERVICE_BASE_URL", "http://hestia_plutus:19020")
SERVICE_VERSION = os.getenv("SERVICE_VERSION", "1.0.0")
SERVICE_TYPE = os.getenv("SERVICE_TYPE", "module")
SERVICE_TAGS = [t.strip().lower() for t in os.getenv("SERVICE_TAGS", "module,finance,context,coach").split(",") if t.strip()]
SERVICE_TOPOLOGY_TAGS = [t.strip().lower() for t in os.getenv(
    "SERVICE_TOPOLOGY_TAGS", "layer:domain,domain:finance,status:alpha").split(",") if t.strip()]
HUB_API_URL = os.getenv("HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
UI_DIST = os.getenv("PLUTUS_UI_DIST", "/code/ui/dist")
TZ = os.getenv("TZ") or "Europe/Rome"
API = "/api/finance"
DOMAIN = "finance"
MAIL_KEY = "paypal"
DEFAULT_PAYPAL_SENDERS = ["paypal.it", "paypal.com"]

# ── settings (Themis) ────────────────────────────────────────────────────────
settings = SettingsClient("plutus")
settings.declare([
    setting("plutus.month_start_day", "Il mese inizia il giorno", "int", 1, group="Mese", min=1, max=28,
            help="Per budget e riepiloghi. Es. 27 se ragioni da uno stipendio all'altro."),
    setting("plutus.alerts.enabled", "Avvisi budget", "bool", True, group="Avvisi",
            help="Un avviso quando una categoria (o il totale) arriva alla soglia e uno quando la supera. "
                 "Al massimo uno per categoria per livello al mese."),
    setting("plutus.alerts.threshold", "Soglia avviso", "int", 80, group="Avvisi", min=50, max=99, unit="%",
            depends_on={"key": "plutus.alerts.enabled", "equals": True}),
    setting("plutus.review.enabled", "Riepilogo mensile", "bool", False, group="Avvisi",
            help="Il primo del mese: com'è andato il mese passato rispetto al budget e al mese prima."),
    *reminder_settings("plutus", help="Ti ricordo di caricare l'estratto conto (PDF dei movimenti) se il mese "
                                      "passato non c'è ancora. Uno alla volta."),
    voice_setting("plutus", False),
    setting("plutus.mail.senders", "Mittenti PayPal", "list", list(DEFAULT_PAYPAL_SENDERS), group="Email", order=0,
            help="Indirizzi o domini delle email di pagamento: Iris le passa a Spese appena arrivano."),
    setting("plutus.coach.review_threshold", "Movimenti da controllare per proporre un ripasso", "int", 10,
            group="Piano della settimana", min=1, max=100, unit="movimenti",
            help="Da questo numero di movimenti da controllare metto nel piano della settimana 15 minuti per "
                 "rivedere le spese."),
    setting("plutus.link.window_days", "Giorni per collegare PayPal e banca", "int", 3, group="Email", min=0, max=10,
            unit="giorni", advanced=True,
            help="Un pagamento PayPal pagato con la carta compare due volte: le due righe con lo stesso importo "
                 "entro questi giorni vengono collegate e contate una volta sola."),
]).follow_personal()                                       # currency, week start: personal settings shared by every module

hub = Hub(HUB_API_URL)
store = Store(hub)


# What Spese asks Oracle for (the chain is chosen by Marko in Oracle → Cervello → Modelli).
LLM_USECASE = "plutus.lettura"
LLM_USECASES = [llm_usecase(LLM_USECASE, "Spese · email ed estratti", chain="veloce",
                            help="Legge le email o gli estratti che il lettore automatico non capisce e propone le "
                                 "categorie.")]


def _llm(prompt: str) -> str | None:
    """Oracle (the only door to models), compact prompt, JSON answers; failure → None (caller has a fallback)."""
    body = {"use_case": LLM_USECASE, "temperature": 0, "max_tokens": 1500,
            "messages": [{"role": "user", "content": prompt}]}
    try:
        out = hub.ok("oracle", "POST", "api/llm/chat", body=body, timeout=120)
        text = ((out or {}).get("choices") or [{}])[0].get("message", {}).get("content") or ""
        if isinstance(text, list):
            text = " ".join(str(t.get("text", "")) for t in text if isinstance(t, dict))
        return str(text)
    except Exception as exc:
        logger.warning("[🔄] event=plutus_llm_failed error=%s fallback=to_review", exc)
        return None


plutus = Plutus(store, settings.get, tz_name=TZ, llm=_llm)
statements = Statements(plutus, hub)
agenda = AgendaClient("plutus", HUB_API_URL)
mail = MailClient("plutus", HUB_API_URL)
# Reflection signals (budget pace, unusual week, new subscriptions + weekly spent) → Archive signals-store.
# evaluate goes through the module global so tests can swap ``plutus``.
signals = Signals("plutus", DOMAIN, evaluate=lambda: plutus.signals(), hub_api_url=HUB_API_URL)
coach = PlutusCoach(plutus)
coach_client = CoachClient("plutus", HUB_API_URL)


def _coach_check() -> None:
    """After movements change, tell the weekly plan (Chronos) in the background if the review is due or done."""
    def _run():
        try:
            event = coach.check()
        except Exception as exc:
            logger.warning("[🔄] event=plutus_coach_check_failed error=%s", exc)
            return
        if event == "done":
            coach_client.done(REVIEW_NEED)
        elif event == "changed":
            coach_client.changed()
    threading.Thread(target=_run, daemon=True, name="plutus-coach").start()

app = FastAPI(title="Hestia-Plutus", version=SERVICE_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(CoachRouter("plutus", DOMAIN, "Spese", needs=coach.needs, review=coach.review).router)


@app.exception_handler(Invalid)
async def _invalid(_: Request, exc: Invalid):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(NotFound)
async def _not_found(_: Request, exc: NotFound):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(StoreUnavailable)
async def _store_down(_: Request, exc: StoreUnavailable):
    return JSONResponse(status_code=503, content={"detail": "archivio non raggiungibile, riprova tra poco"})


@app.get("/health")
def health():
    return {"status": "ok", "service": "hestia_plutus", "version": SERVICE_VERSION, "mirror_loaded": store.loaded,
            "rows": len(store.rows), "cursor": store.cursor}


@app.get("/api/logs")
def get_logs(limit: int = 200, level: str | None = None, contains: str | None = None):
    logs = log_buffer.query(limit=limit, level=level, contains=contains)
    return {"service": "hestia_plutus", "count": len(logs), "logs": logs}


# ── meta, categories, rules, accounts, budgets ───────────────────────────────
@app.get(f"{API}/meta")
def meta():
    return {"currency": plutus.currency(), "categories": plutus.categories(), "accounts": plutus.accounts(),
            "budgets": plutus.budgets(), "month_start_day": plutus.setting("plutus.month_start_day", 1),
            "month": plutus.month_range()[0].isoformat()}


@app.get(f"{API}/categories")
def categories(archived: bool = False):
    return {"items": plutus.categories(archived)}


@app.post(f"{API}/categories")
def category_create(body: dict = Body(...)):
    return plutus.save_category(body)


@app.put(f"{API}/categories/{{id}}")
def category_update(id: str, body: dict = Body(...)):
    plutus.get("category", id)
    return plutus.save_category(body, id=id)


@app.get(f"{API}/rules")
def rules():
    return {"items": plutus.rules()}


@app.post(f"{API}/rules")
def rule_create(body: dict = Body(...)):
    out = plutus.learn_rule(str(body.get("pattern") or ""), plutus.resolve_category(body.get("category")) or "")
    if not out:
        raise Invalid("serve un testo di almeno 3 lettere e una categoria esistente")
    return out


@app.delete(f"{API}/rules/{{id}}")
def rule_delete(id: str):
    return plutus.delete_rule(id)


@app.get(f"{API}/accounts")
def accounts():
    return {"items": plutus.accounts()}


@app.post(f"{API}/accounts")
def account_create(body: dict = Body(...)):
    aid = plutus.resolve_account(body.get("name"))
    return plutus.get("account", aid)


@app.get(f"{API}/budgets")
def budgets(month: str = ""):
    s = plutus.summary(month)
    return {"month": s["month"], "label": s["label"], "currency": s["currency"], "total": s["budget"],
            "spent": s["spent"], "budgets": plutus.budgets(), "categories": s["categories"],
            "all_categories": [c for c in plutus.categories() if c.get("kind") == "expense"]}


@app.put(f"{API}/budgets/{{category}}")
def budget_set(category: str, body: dict = Body(...)):
    out = plutus.set_budget(category, body.get("amount"))
    signals.changed()
    return out


# ── transactions ─────────────────────────────────────────────────────────────
@app.get(f"{API}/transactions")
def transactions(month: str = "", since: str = "", until: str = "", category: str = "", account: str = "", q: str = "",
                 status: str = "", source: str = "", import_id: str = "", limit: int = 500):
    items = plutus.transactions(month=month, since=since, until=until, category=category, account=account, q=q,
                                status=status, source=source, import_id=import_id, limit=limit)
    return {"count": len(items), "items": items}


@app.post(f"{API}/transactions")
def transaction_create(body: dict = Body(...)):
    out = plutus.add_tx(body, source=body.get("source") or "manual")
    signals.changed()
    return out


@app.get(f"{API}/transactions/{{id}}")
def transaction_get(id: str):
    t = plutus.tx_view(plutus.get("tx", id))
    linked = [plutus.tx_view(x) for x in plutus._tx_rows() if x.get("linked_to") == id]
    if t.get("linked_to"):
        linked.append(plutus.tx_view(plutus.get("tx", t["linked_to"])))
    return {**t, "linked": linked, "similar": plutus.transactions(q=(t.get("merchant") or "")[:30], limit=6)
            if t.get("merchant") else []}


@app.put(f"{API}/transactions/{{id}}")
def transaction_update(id: str, body: dict = Body(...)):
    out = plutus.update_tx(id, body, learn=bool(body.get("learn")))
    signals.changed()
    _coach_check()
    return out


@app.delete(f"{API}/transactions/{{id}}")
def transaction_delete(id: str):
    out = plutus.delete_tx(id)
    signals.changed()
    return out


# ── summaries ────────────────────────────────────────────────────────────────
@app.get(f"{API}/summary")
def summary(month: str = ""):
    return plutus.summary(month)


@app.get(f"{API}/stats")
def stats(months: int = 6):
    return plutus.stats(months)


@app.get(f"{API}/recurring")
def recurring(detect: bool = True):
    if detect:
        plutus.detect_recurring()
    return {"items": plutus.recurring(), "currency": plutus.currency()}


@app.post(f"{API}/recurring/{{id}}")
def recurring_set(id: str, body: dict = Body(...)):
    return plutus.set_recurring(id, str(body.get("status") or ""))


@app.get(f"{API}/export")
def export():
    return {"filename": f"spese-{plutus.today().isoformat()}.json", "data": plutus.export()}


def _recap_piece(day, nxt) -> dict:
    """Daily recap piece (docs/work/2026-10-20-recap-giornaliero)."""
    return recap.piece("plutus", "Spese", icon="wallet", emoji="💶", order=60, **plutus.recap(day, nxt))


app.include_router(recap.recap_router("plutus", _recap_piece, today=lambda: plutus.today()))


@app.get("/api/module/context")
def module_context(budget: int = 400, topic: str = ""):
    """Shared contract of the modules: a short caveman line the assistant may include. ``topic`` = a signal key
    (``budget_pace:<cat>``, ``unusual_week``, ``new_subscription:<id>``, ``to_review``) → the detail behind it;
    unknown topic → the normal line."""
    text = (plutus.topic_text(topic, budget) if topic else None) or plutus.context_text(budget)
    return {"module": "plutus", "domain": DOMAIN, "updated_at": now_iso(), "text": text}


@app.post(f"{API}/signals/run")
def signals_run():
    """Agenda job ``plutus.signals``: re-evaluate the reflection signals and weekly metrics, sync to Archive."""
    return signals.run()


# ── statements (Hype PDF): preview → commit → undo ───────────────────────────
@app.get(f"{API}/imports")
def imports():
    return {"items": statements.imports(), "mail": _mail_state()}


@app.post(f"{API}/imports")
def import_preview(body: dict = Body(...)):
    """Upload ``{name, mime, data_b64}`` (plugin) or ``{blob_id}`` (chat attachment) or ``{text}``."""
    return statements.preview(data_b64=str(body.get("data_b64") or ""), text=str(body.get("text") or ""),
                              name=str(body.get("name") or ""), account=str(body.get("account") or "hype"),
                              blob_id=str(body.get("blob_id") or ""), source=str(body.get("source") or "webui"))


@app.get(f"{API}/imports/{{id}}")
def import_get(id: str):
    return statements.view(id)


@app.post(f"{API}/imports/{{id}}/commit")
def import_commit(id: str):
    out = statements.commit(id)
    signals.changed()
    _coach_check()
    return out


@app.post(f"{API}/imports/{{id}}/undo")
def import_undo(id: str):
    out = statements.undo(id)
    signals.changed()
    return out


# Chat attachments (Oracle hand-off): a PDF whose text has these words is offered to Plutus (Hub capability).
ATTACHMENT_HANDLERS = [{"mime": ["application/pdf"], "label": "Estratto conto", "min_hits": 2, "path": f"{API}/attachments",
                        "match": ["lista movimenti", "estratto conto", "saldo contabile", "saldo disponibile", "saldo iniziale",
                                  "saldo finale", "data valuta", "data operazione", "iban", "movimenti"]}]


def _day(iso: str) -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if len(iso or "") >= 10 else str(iso)


def _money(v: float, cur: str) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + (" €" if cur == "EUR" else f" {cur}")


@app.post(f"{API}/attachments")
def attachment(body: dict = Body(...)):
    """Oracle hand-off: a statement PDF sent in chat (Archive blob) → preview; the reply asks to confirm."""
    try:
        v = statements.preview(blob_id=str(body.get("blob_id") or ""), name=str(body.get("filename") or ""),
                               account="hype", source="chat")
    except (Invalid, NotFound) as exc:
        logger.info("event=plutus_attachment_declined reason=%s", exc)
        return {"handled": False, "reason": str(exc)}
    c, cur = v["counts"], v["currency"]
    new, dup, link = c.get("new", 0), c.get("duplicate", 0), c.get("link", 0)
    period = " → ".join(_day(d) for d in v["period"])
    if not new and not link:
        text = f"Ho letto l'estratto conto ({period}): i movimenti ci sono già tutti ({dup}), non aggiungo niente."
    else:
        n = new + link
        text = (f"Ho letto l'estratto conto ({period}): {n} {'movimento' if n == 1 else 'movimenti'} da aggiungere, "
                f"spese nuove {_money(v['total_new_spent'], cur)}"
                + (f", {link} {'collegato a un pagamento' if link == 1 else 'collegati a pagamenti'} PayPal già "
                   f"{'registrato' if link == 1 else 'registrati'} (contati una volta)" if link else "")
                + (f", {dup} già {'presente' if dup == 1 else 'presenti'}" if dup else "")
                + f". Li registro? Rispondi «sì» oppure controllali in Spese › Importa. (import_id {v['id']})")
    return {"handled": True, "text": text, "import_id": v["id"], "counts": c}


# ── PayPal mails pushed by Iris ──────────────────────────────────────────────
_mail_lock = threading.Lock()
_mail_stats: dict[str, Any] = {"last_run": None, "processed": 0, "added": 0, "last_error": None}


def _mail_rules() -> list[dict]:
    senders = settings.get("plutus.mail.senders") or DEFAULT_PAYPAL_SENDERS
    return [mail_rule(MAIL_KEY, "Pagamenti PayPal", path=f"{API}/mail", domain=DOMAIN, senders=senders,
                      description="Ricevute, rimborsi e denaro ricevuto: Spese li registra da sola.")]


def process_pending_mail() -> dict:
    """Read every pending ``finance`` mail record in Archive (stored by Iris) → transactions; mark evaluated."""
    if not _mail_lock.acquire(blocking=False):
        return {"status": "busy"}
    try:
        try:
            pending = hub.ok("archive", "GET", f"api/archive/{DOMAIN}/unevaluated", timeout=15) or []
        except Exception as exc:
            _mail_stats["last_error"] = str(exc)[:200]
            logger.warning("[🔄] event=plutus_mail_pending_failed error=%s fallback=next_ring", exc)
            return {"status": "error", "error": str(exc)[:200]}
        added = 0
        for record in pending if isinstance(pending, list) else []:
            try:
                out = plutus.process_mail(record)
                added += out.get("status") == "added"
                hub.ok("archive", "PATCH", f"api/archive/{record['id']}", body={"evaluation": out}, timeout=10)
            except StoreUnavailable as exc:
                logger.warning("[🔄] event=plutus_mail_store_down error=%s fallback=next_ring", exc)
                break
            except Exception as exc:
                logger.warning("[🔄] event=plutus_mail_record_failed id=%s error=%s", record.get("id"), exc)
        _mail_stats.update(last_run=now_iso(), processed=_mail_stats["processed"] + len(pending or []),
                           added=_mail_stats["added"] + added, last_error=None)
        if added:
            plutus.detect_recurring()
            signals.changed()
            _coach_check()
        return {"status": "ok", "processed": len(pending or []), "added": added}
    finally:
        _mail_lock.release()


def _mail_state() -> dict:
    return {**_mail_stats, "subscription": f"plutus:{MAIL_KEY}", "senders": settings.get("plutus.mail.senders")}


@app.post(f"{API}/mail")
def mail_delivered(body: dict = Body(default={})):
    """Iris rang: PayPal mails are waiting in Archive → process them now (async)."""
    logger.info("event=plutus_mail_delivered count=%s source=%s", body.get("count"), body.get("source"))
    threading.Thread(target=process_pending_mail, daemon=True, name="plutus-mail").start()
    return {"status": "started"}


@app.post(f"{API}/mail/check")
def mail_check(body: dict = Body(default={})):
    """«Controlla email PayPal»: Iris passes again the last days' PayPal mails (dedup by id), then process."""
    days = int(body.get("days") or 7)

    def _run():
        mail.backfill(MAIL_KEY, days)
        process_pending_mail()
    threading.Thread(target=_run, daemon=True, name="plutus-mail-check").start()
    return {"status": "started", "days": days}


def _on_settings(changed: dict) -> None:
    if "plutus.mail.senders" in changed:
        mail.refresh()


settings.on_change(_on_settings)


# ── quick actions (WebUI Home) ───────────────────────────────────────────────
@app.get(f"{API}/quick/categories")
def quick_categories():
    return plutus.quick_categories()


@app.post(f"{API}/quick/expense/{{id}}")
def quick_expense(id: str, body: dict = Body(default={})):
    out = plutus.add_tx({"amount": body.get("amount"), "category": id, "date": body.get("date"),
                         "merchant": body.get("merchant") or body.get("note") or "", "type": "expense",
                         "account": body.get("account") or "contanti"}, source="quick")
    signals.changed()
    return {**out, "label": f"{out['category_label']}: {abs(out['amount']):.2f} {out['currency']}"}


@app.delete(f"{API}/quick/expense/{{id}}")
def quick_expense_undo(id: str, date: str = ""):
    """Undo of the toast: the last quick expense of that category (today or ``date``)."""
    day = date or plutus.today().isoformat()
    rows = [t for t in plutus._tx_rows() if t.get("category") == id and t.get("source") == "quick" and t["date"] == day]
    if not rows:
        raise NotFound("nessuna spesa veloce da annullare")
    last = max(rows, key=lambda t: t.get("created_at") or "")
    out = plutus.delete_tx(last["id"])
    signals.changed()
    return out


# ── alerts, review, statement reminder (agenda jobs → Hermes) ────────────────
def _emit(key: str, title: str, text: str, actions: list[dict], level: str = "info", page_: str = "panoramica") -> None:
    hub.ok("hermes", "POST", "api/events/ingest", body=reminder_event(
        module="plutus", domain=DOMAIN, key=key, kind=key.rsplit(".", 1)[0], title=title, text=text,
        voice=bool(settings.get("plutus.notifiche.voce", False)),
        actions=actions, page=page_, level=level), timeout=8)


@app.post(f"{API}/alerts/run")
def alerts_run():
    """Agenda job ``plutus.daily``: budget alerts (one per category per level per month) + recurring detection."""
    plutus.detect_recurring()
    if not plutus.setting("plutus.alerts.enabled", True):
        return {"items": [], "why": "disabled"}
    sent = []
    for a in plutus.budget_alerts():
        sid = f"{a['month']}.{a['category']}.{a['level']}"
        if store.data("alert", sid):
            continue
        try:
            _emit(a["key"], "Spese", a["text"], [], level="warning" if a["level"] == 100 else "info", page_="budget")
            store.upsert("alert", sid, {"sent": now_iso(), **a})
            sent.append(a["key"])
        except Exception as exc:
            logger.warning("[🔄] event=plutus_alert_emit_failed key=%s error=%s fallback=next_run", a["key"], exc)
    logger.info("event=plutus_alerts_run sent=%d", len(sent))
    return {"items": sent}


def _review_text(r: dict) -> str:
    cur = r["currency"]
    prompt = ("Scrivi in italiano, 3-5 frasi brevi e concrete, il riepilogo spese del mese per l'utente (tu = "
              "l'assistente). Niente consigli generici. Dati JSON: " + str(r))
    text = (_llm(prompt) or "").strip()
    if text:
        return text[:1200]
    parts = [f"{r['month']}: spesi {r['spent']:.2f} {cur}"
             + (f" su un budget di {r['budget']:.2f}" if r.get("budget") else "")
             + f" (mese prima {r['previous_spent']:.2f})."]
    if r["over_budget"]:
        parts.append("Oltre il budget: " + ", ".join(r["over_budget"]) + ".")
    if r["biggest_changes"]:
        c = r["biggest_changes"][0]
        parts.append(f"Cambiata di più: {c['label']} ({'+' if c['delta'] >= 0 else ''}{c['delta']:.2f}).")
    if r["to_review"]:
        parts.append(f"{r['to_review']} movimenti da rivedere.")
    return " ".join(parts)


@app.post(f"{API}/review/run")
def review_run(body: dict = Body(default={})):
    """Agenda job ``plutus.review`` (1st of the month): last month vs budget and the month before."""
    if not plutus.setting("plutus.review.enabled", False) and not body.get("force"):
        return {"sent": False, "why": "disabled"}
    r = plutus.review()
    text = _review_text(r)
    _emit(f"finance.review.{plutus.month_range()[0].isoformat()}", f"Spese di {r['month']}", text, [], page_="panoramica")
    return {"sent": True, "text": text, "review": r}


@app.post(f"{API}/reminders/run")
def reminders_run():
    """Agenda job ``plutus.statement_reminder``: last month's statement missing → one reminder (max per week)."""
    if not plutus.setting("plutus.reminder.enabled", False):
        return {"sent": False, "why": "disabled"}
    start, _ = plutus.month_range()
    prev_start, prev_end = plutus.month_range(start - timedelta(days=1))
    if statements.covers_month(prev_start, prev_end):
        return {"sent": False, "why": "statement_present"}
    state = store.data("reminder", "statement") or {}
    today = plutus.today()
    if state.get("skip_month") == prev_start.isoformat():
        return {"sent": False, "why": "skipped_this_month"}
    week = [d for d in state.get("sent", []) if d >= (today - timedelta(days=7)).isoformat()]
    if today.isoformat() in week or len(week) >= int(plutus.setting("plutus.reminder.max_per_week", 2) or 2):
        return {"sent": False, "why": "limit"}
    label = plutus.month_label(prev_start)
    actions = [{"id": "skip", "label": "Non questo mese", "text": "🌙 Non questo mese", "service": "plutus",
                "method": "POST", "path": f"{API}/reminders/skip", "body": {"month": prev_start.isoformat()},
                "resolves": True}]
    try:
        _emit("finance.reminder.statement", "Spese",
              f"Manca l'estratto conto di {label}: scarica la lista movimenti in PDF dall'app della banca e "
              "caricala nella pagina Importa (o mandala in chat).", actions, page_="importa")
    except Exception as exc:
        logger.warning("[🔄] event=plutus_reminder_emit_failed error=%s fallback=next_run", exc)
        return {"sent": False, "why": "hermes_unreachable"}
    store.upsert("reminder", "statement", {**state, "sent": week + [today.isoformat()]})
    return {"sent": True}


@app.post(f"{API}/reminders/skip")
def reminders_skip(body: dict = Body(default={})):
    state = store.data("reminder", "statement") or {}
    store.upsert("reminder", "statement", {**state, "skip_month": body.get("month")})
    return {"status": "ok", "label": "Promemoria estratto conto: salto questo mese"}


def _agenda_rules() -> list[dict]:
    return [
        job_rule("plutus.daily", "Spese: avvisi budget e abbonamenti", service="plutus", path=f"{API}/alerts/run",
                 recurrence="FREQ=DAILY", start_at="2026-01-01T21:00:00", tz=TZ,
                 description="Controlla i budget del mese (avviso alla soglia e al superamento, uno per categoria) "
                             "e riconosce i pagamenti ricorrenti."),
        job_rule("plutus.review", "Spese: riepilogo del mese", service="plutus", path=f"{API}/review/run",
                 recurrence="FREQ=MONTHLY;BYMONTHDAY=1", start_at="2026-01-01T09:00:00", tz=TZ,
                 description="Solo se il riepilogo mensile è attivo: com'è andato il mese passato."),
        job_rule("plutus.statement_reminder", "Spese: promemoria estratto conto", service="plutus",
                 path=f"{API}/reminders/run", recurrence="FREQ=MONTHLY;BYMONTHDAY=3,6,9", start_at="2026-01-01T10:00:00",
                 tz=TZ, description="Solo se il promemoria è attivo e manca l'estratto del mese passato."),
        signals_rule("plutus", "Spese", path=f"{API}/signals/run", tz=TZ),
    ]


# ── plugin (UI bundle) ───────────────────────────────────────────────────────
ui = PluginClient("plutus", title="Spese", icon="wallet", color="green",
                  description="Spese e entrate: PayPal da solo, estratti conto, budget, abbonamenti, statistiche.",
                  dist=UI_DIST, version=SERVICE_VERSION)
ui.webui(
    entry="plutus.js", api_prefix=f"{API}/",
    pages=[page("panoramica", "Spese", element="plutus-overview", icon="wallet", order=60,
                help="Il mese in corso: speso, budget, categorie, ultimi movimenti."),
           page("movimenti", "Movimenti", element="plutus-transactions", icon="list", order=61, parent="panoramica",
                badge={"source": f"{API}/summary", "field": "to_review"}),
           page("movimenti/:id", "Movimento", element="plutus-transaction", detail=True, parent="panoramica"),
           page("budget", "Budget", element="plutus-budgets", icon="target", order=62, parent="panoramica"),
           page("abbonamenti", "Abbonamenti", element="plutus-recurring", icon="repeat", order=63, parent="panoramica"),
           page("importa", "Importa", element="plutus-import", icon="upload", order=64, parent="panoramica",
                help="Carica il PDF dei movimenti della banca (es. Hype): vedi l'anteprima e confermi. Le email "
                     "PayPal arrivano da sole."),
           page("statistiche", "Statistiche", element="plutus-stats", icon="chart", order=65, parent="panoramica"),
           page("categorie", "Categorie e regole", element="plutus-categories", icon="tag", order=66,
                parent="panoramica")],
    widgets=[widget("mese", "Spese del mese", element="plutus-month-widget", sizes=["s", "m", "l"], auto=True,
                    open_page="panoramica", icon="wallet"),
             widget("ultimi", "Ultimi movimenti", element="plutus-latest-widget", sizes=["m", "l"],
                    open_page="movimenti", icon="list")],
    quick_actions=[quick_action("spesa", "Spesa veloce", "POST", f"{API}/quick/expense/{{id}}", icon="wallet",
                                group="Spese", source=f"{API}/quick/categories",
                                undo={"method": "DELETE", "path": f"{API}/quick/expense/{{id}}"},
                                params={"amount": {"type": "float", "label": "Importo", "required": True},
                                        "note": {"type": "string", "label": "Dove / cosa"}},
                                favorite=True, order=60)],
)
app.include_router(ui.router())
app.include_router(settings.router())

# ── export / import (hestia_common.transfer; reminder/alert rows are runtime state) ─────────────────────
transfer = Transfer("plutus", hub, sections=[
    StoreSection("movimenti", "Movimenti", store, ["tx"], icon="wallet",
                 title=lambda r: f"{r['data'].get('merchant') or r['data'].get('description') or 'Movimento'} "
                                 f"{r['data'].get('amount')} {r['data'].get('currency') or ''}".strip(),
                 subtitle=lambda r: r["data"].get("date") or "", depends_on=["categorie", "conti"]),
    StoreSection("categorie", "Categorie", store, ["category"], icon="tag"),
    StoreSection("regole", "Regole", store, ["rule"], icon="filter",
                 title=lambda r: f"{r['data'].get('pattern')} → {r['data'].get('category')}", depends_on=["categorie"]),
    StoreSection("budget", "Budget", store, ["budget"], icon="target",
                 title=lambda r: f"{r['data'].get('category')}: {r['data'].get('amount')}", depends_on=["categorie"]),
    StoreSection("conti", "Conti", store, ["account"], icon="wallet"),
    StoreSection("ricorrenti", "Ricorrenti", store, ["recurring"], icon="repeat",
                 title=lambda r: r["data"].get("merchant") or r["id"], depends_on=["categorie"]),
])
app.include_router(transfer.router())


# ── MCP tools (domain finance; Oracle calls them, the logic stays here) ──────
def _t(fn):
    def run(**kw):
        try:
            return fn(**{k: v for k, v in kw.items() if v is not None})
        except (Invalid, NotFound) as exc:
            return {"error": str(exc)}
    return run


def _short(t: dict) -> dict:
    return {k: t.get(k) for k in ("id", "date", "amount", "currency", "merchant", "category_label", "account",
                                  "status") if t.get(k) not in (None, "")} | ({"counted": False} if not t.get("counted") else {})


try:
    from hestia_common.mcp_helpers import MCPTool, create_mcp_router, mount_missing_rest_routes

    def _summary(month: str = "") -> dict:
        s = plutus.summary(month)
        return {k: s[k] for k in ("label", "currency", "spent", "income", "budget", "left", "pace", "to_review")} | {
            "categories": [f"{c['label']} {c['spent']:.2f}" + (f"/{c['budget']:.0f} ({c['pct']}%)" if c.get("budget") else "")
                           for c in s["categories"]],
            "top_merchants": [f"{m['merchant']} {m['spent']:.2f}" for m in s["top_merchants"]],
            "recurring_next": [f"{r['merchant']} {r['amount']:.2f} il {r['next']}" for r in s["recurring_next"]]}

    def _search(query: str = "", category: str = "", month: str = "", since: str = "", until: str = "",
                account: str = "", to_review: bool = False, limit: int = 30) -> dict:
        items = plutus.transactions(q=query, category=category, month=month, since=since, until=until, account=account,
                                    status="to_review" if to_review else "", limit=max(1, min(limit, 100)))
        total = round(sum(t["amount"] for t in items if t.get("counted")), 2)
        return {"count": len(items), "total": total, "items": [_short(t) for t in items]}

    def _add(amount: float | None = None, category: str = "", merchant: str = "", date: str = "", account: str = "",
             note: str = "", income: bool = False) -> dict:
        out = plutus.add_tx({"amount": amount, "category": category, "merchant": merchant, "date": date,
                             "account": account or "contanti", "notes": note, "type": "income" if income else "expense"},
                            source="chat")
        signals.changed()
        return {"saved": True, **_short(out), "undo": "finance_delete"}

    def _update(id: str = "", category: str = "", amount: float | None = None, date: str = "", merchant: str = "",
                note: str = "", always: bool = False) -> dict:
        body = {k: v for k, v in {"category": category, "amount": amount, "date": date, "merchant": merchant,
                                  "notes": note}.items() if v not in (None, "")}
        if not body:
            return {"error": "nessuna modifica indicata"}
        out = plutus.update_tx(id, body, learn=always)
        signals.changed()
        _coach_check()
        return {"saved": True, **_short(out)}

    def _delete(id: str = "") -> dict:
        out = plutus.delete_tx(id)
        signals.changed()
        return out

    def _budget(month: str = "") -> dict:
        b = budgets(month)
        return {"month": b["label"], "currency": b["currency"], "total": b["total"], "spent": b["spent"],
                "categories": [f"{c['label']}: {c['spent']:.2f}" + (f" / {c['budget']:.0f}" if c.get("budget") else "")
                               for c in b["categories"]]}

    def _set_budget(category: str = "", amount: float | None = None) -> dict:
        out = plutus.set_budget(category or "total", amount)
        signals.changed()
        return {"saved": True, **out}

    def _categories() -> dict:
        return {"items": [f"{c['id']} = {c['label']} ({c.get('kind')})" for c in plutus.categories()]}

    def _import(blob_id: str = "", account: str = "hype", commit: bool = False, import_id: str = "") -> dict:
        if import_id and commit:
            v = statements.commit(import_id)
            signals.changed()
            return {"committed": True, "added": v.get("added"), "linked": v.get("linked"), "period": v.get("period")}
        v = statements.preview(blob_id=blob_id, account=account, source="chat")
        return {"import_id": v["id"], "period": v["period"], "counts": v["counts"], "how": v["how"],
                "total_new_spent": v["total_new_spent"], "currency": v["currency"],
                "next": "chiedi conferma all'utente, poi finance_import_statement con import_id e commit=true",
                "sample": [f"{r['date']} {r['merchant']} {r['amount']:.2f} [{r['state']}]" for r in v["rows"][:8]]}

    def _recurring() -> dict:
        plutus.detect_recurring()
        return {"items": [f"{r['merchant']} {r['amount']:.2f} {r['period']} prossimo {r['next']} [{r['status']}]"
                          for r in plutus.recurring()]}

    def _stats(months: int = 6) -> dict:
        s = plutus.stats(months)
        return {"currency": s["currency"], "avg_spent": s["avg_spent"],
                "months": [f"{m['label']}: {m['spent']:.2f} spese, {m['income']:.2f} entrate" for m in s["months"]],
                "categories": [f"{c['label']} {c['total']:.2f} (media {c['avg']:.2f})" for c in s["categories"][:10]],
                "merchants": [f"{m['merchant']} {m['total']:.2f} ×{m['count']}" for m in s["merchants"][:10]]}

    S = {"type": "string"}
    I = {"type": "integer"}
    N = {"type": "number"}
    B = {"type": "boolean"}
    G = "spese"
    _tools = [
        MCPTool(name="finance_summary", description="Spese del mese (o 'month' YYYY-MM-DD): speso, entrate, budget, "
                "ritmo, categorie, esercenti principali, pagamenti ricorrenti in arrivo. Usalo per primo per domande "
                "su soldi, spese, budget.", parameters={"type": "object", "properties": {"month": S}},
                handler=_t(_summary), title="Spese del mese", clients=["telegram", "ui"], telegram_group="spese",
                telegram={"section": "Movimenti", "summary": True}),
        MCPTool(name="finance_search", description="Cerca movimenti: query (esercente/descrizione), category, month o "
                "since/until YYYY-MM-DD, account (paypal, hype, contanti…), to_review. Dà anche il totale.",
                parameters={"type": "object", "properties": {"query": S, "category": S, "month": S, "since": S,
                                                             "until": S, "account": S, "to_review": B, "limit": I}},
                handler=_t(_search), title="Cerca movimenti", clients=["telegram", "ui"], telegram_group="spese",
                telegram={"section": "Movimenti", "primary": 2}),
        MCPTool(name="finance_add", description="Registra una spesa (es. 'ho speso 12 € al bar' = amount 12, merchant "
                "bar, category ristoranti) o un'entrata (income=true). date YYYY-MM-DD (default oggi), account "
                "contanti (default) | hype | paypal.",
                parameters={"type": "object", "properties": {"amount": N, "category": S, "merchant": S, "date": S,
                                                             "account": S, "note": S, "income": B},
                            "required": ["amount"]},
                handler=_t(_add), title="Registra spesa", method="POST", clients=["telegram", "ui"], telegram_group="spese",
                telegram={"section": "Movimenti", "primary": 1}),
        MCPTool(name="finance_update", description="Correggi un movimento (id da finance_search): category, amount, "
                "date, merchant, note. always=true → da ora in poi stessa categoria per quell'esercente.",
                parameters={"type": "object", "properties": {"id": S, "category": S, "amount": N, "date": S,
                                                             "merchant": S, "note": S, "always": B},
                            "required": ["id"]},
                handler=_t(_update), title="Correggi movimento", method="POST", clients=["ui"],
                telegram_visible=False, telegram_group="spese",
                telegram={"section": "Movimenti"}),
        MCPTool(name="finance_delete", description="Elimina un movimento (id). Solo dopo il sì dell'utente.",
                parameters={"type": "object", "properties": {"id": S}, "required": ["id"]},
                handler=_t(_delete), title="Elimina movimento", method="POST", clients=["ui"],
                telegram_visible=False, telegram_group="spese",
                telegram={"section": "Movimenti"}),
        MCPTool(name="finance_budget", description="Budget del mese per categoria e totale, con lo speso.",
                parameters={"type": "object", "properties": {"month": S}}, handler=_t(_budget),
                title="Budget", clients=["telegram", "ui"], telegram_group="spese",
                telegram={"section": "Budget e categorie", "primary": 3}),
        MCPTool(name="finance_set_budget", description="Imposta il budget mensile di una categoria (o 'total'). "
                "amount 0 = togli. Solo dopo il sì dell'utente.",
                parameters={"type": "object", "properties": {"category": S, "amount": N}, "required": ["amount"]},
                handler=_t(_set_budget), title="Imposta budget", method="POST", clients=["ui"],
                telegram_visible=False, telegram_group="spese",
                telegram={"section": "Budget e categorie"}),
        MCPTool(name="finance_categories", description="Le categorie di spesa (id = nome).",
                parameters={"type": "object", "properties": {}}, handler=_t(_categories), title="Categorie",
                clients=["ui"], telegram_visible=False, telegram_group="spese",
                telegram={"section": "Budget e categorie"}),
        MCPTool(name="finance_import_statement", description="Estratto conto PDF mandato in chat (blob_id "
                "dell'allegato): prima anteprima (movimenti nuovi, già presenti, collegati a PayPal), poi, dopo il sì "
                "dell'utente, import_id + commit=true. account hype (default) o altra banca.",
                parameters={"type": "object", "properties": {"blob_id": S, "account": S, "commit": B, "import_id": S}},
                handler=_t(_import), title="Importa estratto conto", method="POST", clients=["ui"],
                telegram_visible=False, telegram_group="spese",
                telegram={"section": "Importa"}),
        MCPTool(name="finance_recurring", description="Pagamenti ricorrenti e abbonamenti riconosciuti (importo, "
                "periodo, prossima data).", parameters={"type": "object", "properties": {}},
                handler=_t(_recurring), title="Abbonamenti", clients=["telegram", "ui"], telegram_group="spese",
                telegram={"section": "Statistiche", "primary": 4}),
        MCPTool(name="finance_stats", description="Andamento degli ultimi mesi: totali, per categoria, esercenti.",
                parameters={"type": "object", "properties": {"months": I}}, handler=_t(_stats),
                title="Statistiche spese", clients=["ui"], telegram_visible=False, telegram_group="spese",
                telegram={"section": "Statistiche", "label": "Statistiche"}),
    ]

    def _coerced(t: MCPTool):
        """REST callers (Telegram, gateway) send strings: coerce by the tool's schema before the handler."""
        props = (t.parameters or {}).get("properties") or {}
        inner = t.handler

        def run(**kw):
            for k, v in list(kw.items()):
                typ = (props.get(k) or {}).get("type")
                if not isinstance(v, str):
                    continue
                if typ == "integer" and v.strip().lstrip("-").isdigit():
                    kw[k] = int(v)
                elif typ == "number":
                    try:
                        kw[k] = float(v.replace(",", "."))
                    except ValueError:
                        pass
                elif typ == "boolean":
                    kw[k] = v.lower() in ("1", "true", "si", "sì", "yes")
            return inner(**{k: v for k, v in kw.items() if k in props})
        return run

    for _tool in _tools:
        # one REST path per tool whose arguments are exactly the tool's (served by mount_missing_rest_routes)
        _tool.path = f"{API}/tools/{_tool.name.removeprefix('finance_')}"
        _tool.handler = _coerced(_tool)
    app.include_router(create_mcp_router(_tools, service_name="plutus"))
except ModuleNotFoundError:
    logger.info("event=mcp_router_skipped service=plutus reason=hestia_common_not_available")

app.include_router(create_log_control_router("hestia_plutus"))
try:
    mount_missing_rest_routes(app, _tools, service_name="plutus")
except NameError:
    pass


# ── Hub registration ─────────────────────────────────────────────────────────
def _registration() -> dict:
    caps = {"mcp_endpoint": f"{SERVICE_BASE_URL.rstrip('/')}/mcp", "module_tool_domains": [DOMAIN],
            "context_endpoint": "/api/module/context", "attachment_handlers": ATTACHMENT_HANDLERS,
            **recap.capabilities(),
            **llm_capabilities(LLM_USECASES)}
    try:
        caps.update(ui.capabilities(SERVICE_BASE_URL))
        caps.update(transfer.capabilities())
    except Exception as exc:
        logger.warning("[🔄] event=plutus_ui_manifest_failed error=%s fallback=no_ui", exc)
    return {"name": SERVICE_NAME, "base_url": SERVICE_BASE_URL, "health_endpoint": "/health",
            "service_type": SERVICE_TYPE, "service_version": SERVICE_VERSION, "tags": SERVICE_TAGS,
            "topology_tags": SERVICE_TOPOLOGY_TAGS, "capabilities": caps}


def _register() -> None:
    resp = requests.post(f"{HUB_API_URL}/registry/register", json=_registration(), timeout=4)
    if resp.status_code >= 400:
        logger.warning("event=hub_registration_non_success status=%s body=%s", resp.status_code, resp.text[:200])
    else:
        logger.info("event=registered_on_hub hub=%s base_url=%s", HUB_API_URL, SERVICE_BASE_URL)


def _warm_up() -> None:
    """Load the mirror and seed defaults in the background, then process mails that waited while we were down."""
    import time
    for attempt in range(1, 1000):
        try:
            if store.refresh(force=True):
                plutus.ensure_seed()
                process_pending_mail()
                signals.changed()
                return
        except Exception as exc:
            logger.warning("[🔄] event=plutus_warmup_failed attempt=%d error=%s", attempt, exc)
        time.sleep(min(60, 5 * attempt))


@app.on_event("startup")
def startup():
    try:
        _register()
    except Exception as exc:
        logger.warning("[🔄] event=hub_registration_failed_non_fatal error=%s", exc)
    from hestia_common.startup_utils import start_hub_keepalive
    start_hub_keepalive(_register, logger=logger, name="plutus-hub-keepalive")
    settings.start()
    agenda.register_async(_agenda_rules)
    mail.subscribe_async(_mail_rules)
    threading.Thread(target=_warm_up, daemon=True, name="plutus-warmup").start()
