"""Routines in words (Cindy 7 + 27 + 28, dossier docs/work/2026-10-24-tutto-brainstorm-cindy).

A routine is **an agenda rule with a written instruction**, not a new timer:

- by **time**: an agenda ``job`` (RRULE) whose action is ``POST chronos /api/routines/{key}/run``;
- by **event**: an agenda ``event`` (never fired by the tick) with ``params.routine.on`` = ``{"mail": {senders,
  subject_contains}}`` (Chronos subscribes to Iris, push) or ``{"signal": "<name>"}`` (a module calls
  ``POST /api/routines/signal``).

``params.routine`` = ``{instruction, precheck?: {tool, args}, deliver: "hermes" | "recap", on?, template?}``.

Run = optional **pre-check** first (Cindy 27: a module tool, e.g. «ci sono annunci nuovi?»; empty answer → the run
stops, «niente di nuovo», no model call), then the assistant runs the instruction as a turn with origin
``routine:<key>`` (it may write, never delete: ``hestia_common.origin``), then the answer is delivered through
Hermes only if there is something (the model answers ``NIENTE`` otherwise) or kept for the evening recap.
Automatic **and** manual: «Esegui adesso» = the agenda's run now. The owner's edits win and pausing is the owner's call (agenda).
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from core import hermes_client, life_store
from services import agenda

logger = logging.getLogger("hestia_chronos.routines")

_HUB = os.getenv("HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
OWNER = "chronos"
PREFIX = "routine."
NOTHING = "NIENTE"
_RUN_TIMEOUT = 300
_lock = threading.Lock()
_results: list[dict] = []          # today's results kept for the recap (in memory, last 50)

# Cindy 27: gallery of ready-made routines. Fields are filled by the owner; `{name}` placeholders in the
# instruction / pre-check arguments take their values.
TEMPLATES: list[dict] = [
    {"id": "radar", "label": "Radar notizie", "icon": "radar",
     "help": "Ogni mattina le notizie importanti su un tema, con la fonte e perché ti interessano.",
     "fields": {"topic": {"label": "Tema", "required": True}},
     "recurrence": "FREQ=DAILY;BYHOUR=7;BYMINUTE=30", "deliver": "recap",
     "precheck": {"tool": "web_search", "args": {"q": "{topic} notizie oggi"}},
     "instruction": ("Dai risultati qui sotto scegli al massimo 5 notizie importanti di oggi su «{topic}». Per ognuna: "
                     "titolo, fonte (link) e una riga «perché ti interessa». Se non c'è niente di nuovo rispondi "
                     "solo NIENTE.")},
    {"id": "case", "label": "Case nuove", "icon": "home",
     "help": "Quando ci sono annunci nuovi, i migliori con il motivo.",
     "fields": {"query": {"label": "Zona", "required": False}},
     "recurrence": "FREQ=DAILY;BYHOUR=19;BYMINUTE=0", "deliver": "hermes",
     "precheck": {"tool": "scout_listings", "args": {"query": "{query}", "limit": 10}},
     "instruction": "Tra gli annunci qui sotto indicami i 3 più adatti a me e perché, in breve."},
    {"id": "spese", "label": "Spese da rivedere", "icon": "wallet",
     "help": "Ogni domenica le spese della settimana da sistemare.",
     "fields": {}, "recurrence": "FREQ=WEEKLY;BYDAY=SU;BYHOUR=18;BYMINUTE=0", "deliver": "hermes",
     "precheck": {"tool": "finance_search", "args": {"to_review": True, "limit": 30}},
     "instruction": "Queste spese sono da rivedere: proponi la categoria giusta per ognuna, in una lista breve."},
    {"id": "settimana", "label": "La settimana che arriva", "icon": "calendar",
     "help": "Il lunedì mattina cosa hai in settimana e cosa preparare.",
     "fields": {}, "recurrence": "FREQ=WEEKLY;BYDAY=MO;BYHOUR=7;BYMINUTE=45", "deliver": "hermes",
     "instruction": ("Guarda i miei impegni di questa settimana e dimmi in 5 righe cosa c'è e cosa devo preparare. "
                     "Se la settimana è vuota rispondi solo NIENTE.")},
    {"id": "mail", "label": "Mail da un mittente", "icon": "mail",
     "help": "Quando arriva una mail da qualcuno, il riassunto e se devi fare qualcosa.",
     "fields": {"senders": {"label": "Mittente (indirizzo o dominio)", "required": True}},
     "on": {"mail": {"senders": "{senders}"}}, "deliver": "hermes",
     "instruction": "Riassumi in 3 righe la mail appena arrivata e dimmi se devo fare qualcosa e entro quando."},
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _slug(text: str) -> str:
    return (re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-") or "routine")[:40]


def _fill(value: Any, values: dict) -> Any:
    if isinstance(value, str):
        return re.sub(r"\{(\w+)\}", lambda m: str(values.get(m.group(1), "")), value)
    if isinstance(value, dict):
        return {k: _fill(v, values) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill(v, values) for v in value]
    return value


# ── definitions ──────────────────────────────────────────────────────────────
def routine_of(item: dict) -> dict:
    return dict((item.get("params") or {}).get("routine") or {})


def list_routines(include_cancelled: bool = False) -> list[dict]:
    out = []
    for item in agenda.list_items(owner=OWNER, include_cancelled=include_cancelled):
        if str(item.get("key") or "").startswith(PREFIX) and routine_of(item):
            r = routine_of(item)
            runs = item.get("runs") or []
            out.append({"key": item["key"], "id": item["id"], "title": item["title"], "status": item["status"],
                        "recurrence": item.get("recurrence"), "start_at": item.get("start_at"),
                        "instruction": r.get("instruction"), "precheck": r.get("precheck"),
                        "deliver": r.get("deliver") or "hermes", "on": r.get("on"), "template": r.get("template"),
                        "trigger": "evento" if r.get("on") else "orario",
                        "last_run": runs[-1] if runs else None})
    return out


def create(*, title: str, instruction: str, recurrence: str | None = None, start_at: str | None = None,
           precheck: dict | None = None, deliver: str = "hermes", on: dict | None = None,
           template: str = "", by: str = "user") -> dict:
    """New routine. ``recurrence`` (RRULE) = by time; ``on`` = by event (mail/signal). One of the two."""
    instruction = str(instruction or "").strip()
    if not instruction:
        raise agenda.AgendaError("a routine needs an instruction (what to do, in words)")
    if not recurrence and not on:
        raise agenda.AgendaError("a routine needs a time (recurrence) or an event (on)")
    if deliver not in ("hermes", "recap"):
        deliver = "hermes"
    key = f"{PREFIX}{_slug(title)}-{uuid.uuid4().hex[:4]}"
    routine = {"instruction": instruction[:2000], "deliver": deliver, "template": template or None}
    if precheck and precheck.get("tool"):
        routine["precheck"] = {"tool": str(precheck["tool"]), "args": dict(precheck.get("args") or {})}
    if on:
        routine["on"] = on
    action = {"service": "chronos", "method": "POST", "path": f"/api/routines/{key}/run",
              "timeout_seconds": _RUN_TIMEOUT}
    start = start_at or _now().replace(second=0, microsecond=0).isoformat()
    item = agenda.create(title=title[:200], type_="event" if on and not recurrence else "job", owner=OWNER,
                         start_at=start, recurrence=recurrence, description=instruction[:500],
                         action=action, key=key, params={"routine": routine}, created_by=by)
    logger.info("event=routine_created key=%s trigger=%s deliver=%s by=%s", key, "event" if on else "time",
                deliver, by)
    if on and on.get("mail"):
        refresh_mail_subscriptions()
    return item


def from_template(template_id: str, values: dict | None = None, *, recurrence: str | None = None,
                  title: str = "") -> dict:
    tpl = next((t for t in TEMPLATES if t["id"] == template_id), None)
    if not tpl:
        raise agenda.AgendaError(f"routine template {template_id} not found", 404)
    values = {k: v for k, v in (values or {}).items() if k in tpl["fields"]}
    for name, spec in tpl["fields"].items():
        if spec.get("required") and not str(values.get(name) or "").strip():
            raise agenda.AgendaError(f"field '{name}' required ({spec['label']})")
    label = tpl["label"] + (f": {next(iter(values.values()))}" if values else "")
    return create(title=title or label, instruction=_fill(tpl["instruction"], values),
                  recurrence=recurrence or tpl.get("recurrence"), precheck=_fill(tpl.get("precheck"), values),
                  deliver=tpl.get("deliver", "hermes"), on=_fill(tpl.get("on"), values), template=template_id)


# ── run ──────────────────────────────────────────────────────────────────────
def _empty(payload: Any) -> bool:
    """A pre-check answer that means «nothing new» (no model call needed)."""
    if payload in (None, "", [], {}):
        return True
    if isinstance(payload, dict):
        for key in ("count", "total_new", "new"):
            if key in payload and isinstance(payload[key], (int, float)) and not payload[key]:
                return True
        for key in ("items", "results", "rows", "listings", "events"):
            if key in payload and isinstance(payload[key], list):
                return not payload[key]
    return False


def _mcp():
    from hestia_common.mcp_client import MCPClient
    return MCPClient(_HUB, "chronos", timeout=40)


def _ask_oracle(key: str, label: str, message: str) -> dict:
    """One assistant turn with origin ``routine:<key>``; ``{reply, changes}`` from the NDJSON answer."""
    from hestia_common import origin as origin_mod
    body = {"message": message, "session_id": f"routine:{key}", "client": "routine",
            "notify_target": "owner", "client_instructions": "Lavori per una routine dell'utente: sii breve."}
    resp = requests.post(f"{_HUB}/route/oracle/api/chat",
                         json={"method": "POST", "headers": origin_mod.headers("routine", key, label),
                               "query": {}, "body": body, "timeout_seconds": _RUN_TIMEOUT},
                         timeout=_RUN_TIMEOUT + 10)
    routed = resp.json() if resp.content else {}
    status = int(routed.get("status_code", resp.status_code))
    if status >= 400:
        raise RuntimeError(f"assistant {status}: {str(routed.get('payload'))[:160]}")
    payload = routed.get("payload")
    raw = payload.get("raw", "") if isinstance(payload, dict) else str(payload or "")
    reply, changes = "", []
    for line in str(raw).splitlines():
        try:
            frame = json.loads(line)
        except ValueError:
            continue
        if frame.get("type") == "final":
            reply = str(frame.get("reply") or "")
        elif frame.get("type") == "changes":
            changes = frame.get("items") or []
    return {"reply": reply.strip(), "changes": changes}


def run(key: str, *, by: str = "agenda", context: str = "") -> dict:
    """Execute one routine now. ``context`` = what triggered it (e.g. the mail that arrived)."""
    item = agenda.get(key)
    r = routine_of(item)
    if not r:
        raise agenda.AgendaError(f"{key} is not a routine", 404)
    if item["status"] in ("paused", "cancelled"):
        logger.info("event=routine_skipped key=%s reason=%s", key, item["status"])
        return {"ok": True, "ran": False, "reason": item["status"]}
    pre_text = ""
    if r.get("precheck"):
        ok, payload = _mcp().call(r["precheck"]["tool"], r["precheck"].get("args") or {}, origin=f"routine:{key}",
                                  timeout=40)
        if not ok:
            logger.warning("[🔄] event=routine_precheck_failed key=%s tool=%s error=%s fallback=run_without",
                           key, r["precheck"]["tool"], str(payload)[:160])
        elif _empty(payload):
            logger.info("event=routine_nothing_new key=%s tool=%s", key, r["precheck"]["tool"])
            return {"ok": True, "ran": False, "reason": "niente di nuovo"}
        else:
            pre_text = json.dumps(payload, ensure_ascii=False, default=str)[:6000]
    message = (f"[ROUTINE «{item['title']}»] {r['instruction']}\n"
               + (f"Cosa l'ha fatta partire:\n{context[:3000]}\n" if context else "")
               + (f"Dati del controllo:\n{pre_text}\n" if pre_text else "")
               + f"Se non c'è niente di utile da dire rispondi solo {NOTHING}.")
    out = _ask_oracle(key, "Da una tua routine", message)
    reply = out["reply"]
    if not reply or reply.strip().strip(".").upper() == NOTHING:
        logger.info("event=routine_quiet key=%s", key)
        return {"ok": True, "ran": True, "delivered": False, "reason": "niente da dire"}
    result = {"key": key, "title": item["title"], "text": reply, "at": _now().isoformat(),
              "changes": out["changes"]}
    if (r.get("deliver") or "hermes") == "recap":
        with _lock:
            _results.append(result)
            del _results[:-50]
        life_store.put("routine_result", f"{key}:{result['at']}", result, at=result["at"], ref_id=key)
    else:
        hermes_client.publish_event("assistant", "routine.result", key, {
            "_title": item["title"], "_message": reply, "_source": "Routine", "_level": "info",
            "replaces": f"routine.{key}", "dedupe_key": f"routine:{key}:{result['at'][:16]}",
            "_link": {"module": "chronos", "page": "routine"}})
    logger.info("event=routine_delivered key=%s deliver=%s by=%s chars=%d", key, r.get("deliver") or "hermes", by,
                len(reply))
    return {"ok": True, "ran": True, "delivered": True, "deliver": r.get("deliver") or "hermes", "text": reply}


def on_signal(name: str, data: dict | None = None) -> list[str]:
    """A module's event (``POST /api/routines/signal``): runs every routine waiting for it."""
    ran = []
    for r in list_routines():
        if (r.get("on") or {}).get("signal") == name and r["status"] == "confirmed":
            threading.Thread(target=_safe_run, args=(r["key"], f"evento {name}: "
                             + json.dumps(data or {}, ensure_ascii=False, default=str)[:2000]), daemon=True).start()
            ran.append(r["key"])
    return ran


def _safe_run(key: str, context: str) -> None:
    try:
        run(key, by="event", context=context)
    except Exception as exc:  # noqa: BLE001 — logged, the next event retries
        logger.warning("[🔄] event=routine_run_failed key=%s error=%s", key, str(exc)[:200])


# ── mail trigger (push from Iris) ────────────────────────────────────────────
MAIL_DOMAIN = "routine_mail"


def mail_rules() -> list[dict]:
    from hestia_common.mail_client import mail_rule
    rules = []
    for r in list_routines():
        mail = (r.get("on") or {}).get("mail")
        if mail and r["status"] == "confirmed":
            rules.append(mail_rule(r["key"], r["title"], path="/api/routines/mail", domain=MAIL_DOMAIN,
                                   senders=mail.get("senders"), subject_contains=mail.get("subject_contains")))
    return rules


def refresh_mail_subscriptions() -> None:
    try:
        from hestia_common.mail_client import MailClient
        MailClient("chronos").subscribe(mail_rules())
    except Exception as exc:  # noqa: BLE001
        logger.warning("[🔄] event=routine_mail_subscribe_failed error=%s", exc)


def on_mail(key: str, reference_ids: list[str]) -> dict:
    """Iris rang: the mails are raw records in Archive under ``routine_mail``; the routine reads them as its
    trigger, then they are marked evaluated (durable: a ring lost while Chronos was down is answered next time)."""
    from core import archive_client
    pending = archive_client._route_archive("GET", f"api/archive/{MAIL_DOMAIN}/unevaluated", timeout=15)
    wanted = set(reference_ids or [])
    texts = []
    for rec in pending if isinstance(pending, list) else []:
        if wanted and rec.get("reference_id") not in wanted:
            continue
        data = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}
        texts.append(json.dumps({k: data.get(k) for k in ("from", "subject", "snippet", "body", "date")
                                 if data.get(k)}, ensure_ascii=False, default=str)[:2500])
        archive_client._route_archive("PATCH", f"api/archive/{rec['id']}", body={"evaluation": {"routine": key}},
                                      timeout=8)
    threading.Thread(target=_safe_run, args=(key, "\n".join(texts) or "mail arrivata"), daemon=True).start()
    return {"ok": True, "key": key, "mails": len(texts)}


# ── recap piece ──────────────────────────────────────────────────────────────
def load_results() -> int:
    """Reload the last day's results kept for the recap (Archive ``chronos-store``) after a restart."""
    rows = life_store.load("routine_result", at_from=(_now() - timedelta(hours=36)).isoformat())
    with _lock:
        known = {(r["key"], r["at"]) for r in _results}
        for row in rows:
            data = row.get("data") or {}
            if data.get("key") and data.get("at") and (data["key"], data["at"]) not in known:
                _results.append(data)
        _results.sort(key=lambda r: r["at"])
        del _results[:-50]
    return len(rows)


def recap_lines(day: datetime | None = None) -> list[dict]:
    day = (day or _now()).date()
    with _lock:
        return [r for r in _results if datetime.fromisoformat(r["at"]).date() == day]


def results_since(hours: float = 24) -> list[dict]:
    limit = _now() - timedelta(hours=hours)
    with _lock:
        return [r for r in _results if datetime.fromisoformat(r["at"]) >= limit]
