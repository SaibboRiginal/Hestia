"""Hestia-Demeter — nutrition («Alimentazione», port 19026, dossier docs/work/2026-10-24-tutto-brainstorm-cindy W5 A5).

Data in Archive (``/api/food-store``): diet, meals, supplements and intakes. A coach of the weekly plan (Hub tag
``coach``, ``/api/coach/*``), kcal estimates from Oracle (use case ``demeter.stima``, async, never blocking the log),
a piece of the daily recap, tools for the assistant and Telegram over MCP.
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
from hestia_common.coach import CoachClient, CoachRouter
from hestia_common.display import action, display, item
from hestia_common.mcp_helpers import MCPTool, undo
from hestia_common.plugin_client import page, widget
from hestia_common.module_kit import ModuleKit
from hestia_common.oracle_usecases import capabilities as llm_capabilities, usecase
from hestia_common.transfer import StoreSection, Transfer

from .core.service import ESTIMATE_USE, SLOTS, TIMES, Nutrition

API = "/api/food"
kit = ModuleKit("demeter", port=19026, api=API, domain="food", title="Alimentazione", store="food-store",
                tags=("coach",),
                when_to_use="alimentazione: dieta, pasti mangiati, calorie, integratori da prendere",
                manual="Dieta (cibo_dieta: kcal e proteine al giorno, regole), pasti (cibo_pasto registra cosa ha "
                       "mangiato; se non dice le kcal le stima l'assistente), riepilogo del giorno (cibo_oggi), "
                       "integratori con momento della giornata (cibo_integratori, cibo_preso).")
app = kit.app
coach = CoachClient("demeter", kit.hub_url)


def _coach_event(event: str, data: dict) -> None:
    def _send():
        if event == "done":
            coach.done(data.get("need_id") or "supplement", data.get("at"))
        elif event == "changed":
            coach.changed()
    threading.Thread(target=_send, daemon=True, name=f"demeter-coach-{event}").start()


food = Nutrition(kit.store, kit.settings.get, tz_name=kit.tz, hub=kit.hub, on_event=_coach_event)


def _estimate_async(meal: dict) -> None:
    if meal.get("kcal") is None:
        threading.Thread(target=lambda: _safe_estimate(meal["id"]), daemon=True, name="demeter-estimate").start()


def _safe_estimate(mid: str) -> None:
    try:
        food.estimate(mid)
    except Exception as exc:
        kit.logger.warning("[🔄] event=demeter_estimate_failed error=%s fallback=no_numbers", exc)


# ── REST (WebUI plugin, Hermes actions) ──────────────────────────────────────
@app.get(f"{API}/today")
def today(day: str = ""):
    from datetime import date
    return food.day_summary(date.fromisoformat(day) if day else None)


@app.get(f"{API}/meals")
def meals(day: str = "", days: int = 7):
    return {"items": food.meals(day, days)}


@app.post(f"{API}/meals")
def add_meal(body: dict = Body(...)):
    meal = food.add_meal(body.get("text", ""), slot=body.get("slot", ""), day=body.get("date", ""),
                         kcal=body.get("kcal"), protein=body.get("protein"))
    _estimate_async(meal)
    return meal


@app.put(f"{API}/meals/{{mid}}")
def update_meal(mid: str, body: dict = Body(...)):
    return food.update_meal(mid, body)


@app.delete(f"{API}/meals/{{mid}}")
def delete_meal(mid: str):
    return food.delete_meal(mid)


@app.get(f"{API}/diet")
def get_diet():
    return food.diet()


@app.put(f"{API}/diet")
def put_diet(body: dict = Body(...)):
    return food.set_diet(body)


@app.get(f"{API}/supplements")
def supplements(all: bool = False):
    return {"items": food.supplements(all), "today": food.supplements_today()}


@app.post(f"{API}/supplements")
def add_supplement(body: dict = Body(...)):
    return food.save_supplement(body)


@app.put(f"{API}/supplements/{{sid}}")
def update_supplement(sid: str, body: dict = Body(...)):
    return food.save_supplement(body, sid)


@app.delete(f"{API}/supplements/{{sid}}")
def delete_supplement(sid: str):
    return food.delete_supplement(sid)


@app.post(f"{API}/supplements/{{sid}}/take")
def take(sid: str, body: dict = Body(default={})):
    return food.take(sid, str(body.get("date") or ""))


app.include_router(CoachRouter("demeter", "food", "Alimentazione", needs=lambda s, e: food.needs(s, e),
                               review=lambda s, e: food.review(s, e)).router)
app.include_router(recap.recap_router(
    "demeter", lambda d, n: recap.piece("demeter", "Alimentazione", icon="leaf", order=45, **food.recap(d, n)),
    today=food.today))


# ── tools ────────────────────────────────────────────────────────────────────
def _today_display(t: dict) -> dict:
    lines = [f"{t['kcal']}" + (f" / {t['kcal_target']}" if t["kcal_target"] else "") + " kcal"
             + (f" · proteine {t['protein']}" + (f"/{t['protein_target']}" if t["protein_target"] else "") + " g")]
    if t["unknown"]:
        lines.append(f"{t['unknown']} pasti ancora senza numeri")
    items = [item(f"{SLOTS.get(m['slot'], m['slot'])}: {m['text']}",
                  [f"{'~' if m.get('estimated') else ''}{m['kcal']} kcal" if m["kcal"] is not None else "—"])
             for m in t["meals"]]
    items += [item(("Preso: " if s["taken"] else "Da prendere: ") + s["name"], [TIMES[s["time_of_day"]]])
              for s in t["supplements"]]
    return display("Oggi a tavola", lines=lines, items=items,
                   actions=[action("Registra pasto", "cibo_pasto", style="primary")] +
                           [action(f"Preso {s['name']}", "cibo_preso", {"supplement": s["id"]})
                            for s in t["supplements"] if not s["taken"]][:3])


def _meal(text: str, slot: str = "", kcal: int | None = None, protein: int | None = None, date: str = "") -> dict:
    meal = food.add_meal(text, slot=slot, day=date, kcal=kcal, protein=protein)
    _estimate_async(meal)
    return {"saved": True, "id": meal["id"], "slot": meal["slot"], "estimating": meal["kcal"] is None,
            "undo": undo("cibo_pasto_elimina", meal=meal["id"])}


def _diet(kcal: int | None = None, protein: int | None = None, rules: str = "", notes: str = "") -> dict:
    if any(v not in (None, "") for v in (kcal, protein, rules, notes)):
        d = food.set_diet({k: v for k, v in {"kcal": kcal, "protein": protein, "rules": rules or None,
                                              "notes": notes or None}.items() if v not in (None, "")})
    else:
        d = {**food.diet(), "unchanged": True}   # read only: no «Fatto» in the chat
    lines = [f"Obiettivo: {d['kcal'] or '—'} kcal · {d['protein'] or '—'} g proteine"] + d["rules"][:10]
    return {**d, "display": display("Dieta", lines=lines, actions=[action("Modifica", "cibo_dieta")])}


def _supplements() -> dict:
    items = food.supplements(True)
    return {"items": items, "display": display("Integratori", items=[
        item(s["name"], [s.get("dose") or "", TIMES[s["time_of_day"]], "in pausa" if s["status"] == "paused" else ""])
        for s in items], lines=[] if items else ["Nessun integratore."],
        actions=[action("Aggiungi", "cibo_integratore", style="primary")])}


S, I, B = {"type": "string"}, {"type": "integer"}, {"type": "boolean"}
SUP = {"type": "string", "description": "id o nome dell'integratore"}
G = "alimentazione"
kit.tools([
    MCPTool(name="cibo_oggi", description="Riepilogo di oggi: pasti, kcal e proteine rispetto alla dieta, integratori.",
            parameters={"type": "object", "properties": {"date": S}},
            handler=lambda date="": (lambda t: {**t, "display": _today_display(t)})(
                food.day_summary(__import__("datetime").date.fromisoformat(date) if date else None)),
            title="Oggi", clients=["telegram", "ui"], telegram_group=G, telegram={"section": "Pasti", "primary": 1}),
    MCPTool(name="cibo_pasto", description="Registra un pasto: text (cosa), slot colazione|pranzo|cena|spuntino, "
            "kcal e protein se note (altrimenti le stima l'assistente).",
            parameters={"type": "object", "properties": {"text": S, "slot": {"type": "string", "enum": list(SLOTS)},
                                                         "kcal": I, "protein": I, "date": S}, "required": ["text"]},
            handler=_meal, title="Registra pasto", method="POST", clients=["telegram", "ui"], telegram_group=G,
            telegram={"section": "Pasti", "primary": 2}),
    MCPTool(name="cibo_pasti", description="Pasti degli ultimi giorni (days, default 7).",
            parameters={"type": "object", "properties": {"days": I}},
            handler=lambda days=7: {"items": food.meals("", days)}, title="Pasti", clients=["telegram", "ui"],
            telegram_group=G, telegram={"section": "Pasti"}),
    MCPTool(name="cibo_pasto_elimina", description="Elimina un pasto registrato.",
            parameters={"type": "object", "properties": {"meal": S}, "required": ["meal"]},
            handler=lambda meal: food.delete_meal(meal), title="Elimina pasto", method="POST",
            clients=["telegram", "ui"], telegram_group=G, telegram={"section": "Pasti"}),
    MCPTool(name="cibo_dieta", description="La dieta: senza argomenti la mostra; kcal, protein (g), rules (una per "
            "riga) e notes la modificano.",
            parameters={"type": "object", "properties": {"kcal": I, "protein": I, "rules": S, "notes": S}},
            handler=_diet, title="Dieta", method="POST", clients=["telegram", "ui"], telegram_group=G,
            telegram={"section": "Dieta", "primary": 3}),
    MCPTool(name="cibo_integratori", description="Gli integratori che l'utente prende.",
            parameters={"type": "object", "properties": {}}, handler=_supplements, title="Integratori",
            clients=["telegram", "ui"], telegram_group=G, telegram={"section": "Integratori", "primary": 4}),
    MCPTool(name="cibo_integratore", description="Aggiungi o modifica un integratore: name, dose, time_of_day "
            "morning|midday|afternoon|evening|any, days (0=lun..6=dom, vuoto = ogni giorno), training_days_only, "
            "with_food, status active|paused.",
            parameters={"type": "object", "properties": {
                "supplement": SUP, "name": S, "dose": S, "time_of_day": {"type": "string", "enum": list(TIMES)},
                "days": {"type": "array", "items": I}, "training_days_only": B, "with_food": B,
                "status": {"type": "string", "enum": ["active", "paused"]}}},
            handler=lambda supplement="", **kw: food.save_supplement(
                kw, food.find_supplement(supplement)["id"] if supplement else None),
            title="Integratore", method="POST", clients=["telegram", "ui"], telegram_group=G,
            telegram={"section": "Integratori"}),
    MCPTool(name="cibo_preso", description="Segna preso un integratore (oggi o date).",
            parameters={"type": "object", "properties": {"supplement": SUP, "date": S}, "required": ["supplement"]},
            handler=lambda supplement, date="": food.take(supplement, date), title="Preso", method="POST",
            clients=["telegram", "ui"], telegram_group=G, telegram={"section": "Integratori", "primary": 5}),
    MCPTool(name="cibo_integratore_elimina", description="Elimina un integratore.",
            parameters={"type": "object", "properties": {"supplement": SUP}, "required": ["supplement"]},
            handler=lambda supplement: food.delete_supplement(supplement), title="Elimina integratore",
            method="POST", clients=["telegram", "ui"], telegram_group=G, telegram={"section": "Integratori"}),
], prefix="cibo_")

transfer = Transfer("demeter", kit.hub, sections=[
    StoreSection("dieta", "Dieta", kit.store, ["diet"], icon="leaf"),
    StoreSection("pasti", "Pasti", kit.store, ["meal"], icon="list", title=lambda r: r["data"].get("text", "")),
    StoreSection("integratori", "Integratori", kit.store, ["supplement", "intake"], icon="droplet",
                 title=lambda r: r["data"].get("name", "")),
])
app.include_router(transfer.router())
kit.caps.update({**recap.capabilities(), **llm_capabilities([
    usecase(ESTIMATE_USE, "Alimentazione · stima kcal", chain="veloce",
            help="Stima kcal e proteine di un pasto descritto a parole.")])})
kit.capabilities(transfer.capabilities)
kit.webui(icon="leaf", color="green", description="Dieta, pasti con calorie stimate, integratori nel piano della settimana.",
          pages=[page("oggi", "Alimentazione", element="demeter-today", icon="leaf", order=80,
                      help="I pasti del giorno con calorie e proteine (stimate dall'assistente se non le scrivi), "
                           "gli integratori da prendere."),
                 page("dieta", "Dieta", element="demeter-diet", icon="target", order=81, parent="oggi"),
                 page("integratori", "Integratori", element="demeter-supplements", icon="droplet", order=82,
                      parent="oggi")],
          widgets=[widget("oggi", "Alimentazione di oggi", element="demeter-widget", sizes=["s", "m"], size="m",
                          auto=True, open_page="oggi", icon="leaf")])
kit.finish()
