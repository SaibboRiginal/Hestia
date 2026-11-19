"""Hestia-Demeter — nutrition («Alimentazione», port 19026, dossier docs/work/2026-10-24-whole-brainstorm-cindy W5 A5).

Data in Archive (``/api/food-store``): diet, meals, supplements and intakes. A coach of the weekly plan (Hub tag
``coach``, ``/api/coach/*``), kcal estimates from Oracle (use case ``demeter.estimate``, async, never blocking the log),
a piece of the daily recap, tools for the assistant and Telegram over MCP.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

from fastapi import Body
from hestia_common.i18n import t as tr  # fixed texts in the owner's language

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
kit = ModuleKit("demeter", port=19026, api=API, domain="food", title="Nutrition", store="food-store",
                tags=("coach",),
                when_to_use="nutrition: diet, meals eaten, calories, supplements to take",
                manual="Diet (food_diet: daily kcal and protein, rules), meals (food_meal logs what was eaten; if no kcal given the assistant estimates them), day summary (food_today), supplements with time of day (food_supplements, food_taken).")
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


app.include_router(CoachRouter("demeter", "food", "Nutrition", needs=lambda s, e: food.needs(s, e),
                               review=lambda s, e: food.review(s, e)).router)
app.include_router(recap.recap_router(
    "demeter", lambda d, n: recap.piece("demeter", tr("Nutrition"), icon="leaf", order=45, **food.recap(d, n)),
    today=food.today))


# ── tools ────────────────────────────────────────────────────────────────────
def _today_display(t: dict) -> dict:
    lines = [f"{t['kcal']}" + (f" / {t['kcal_target']}" if t["kcal_target"] else "") + " kcal"
             + (tr(" · protein {0}", t['protein']) + (f"/{t['protein_target']}" if t["protein_target"] else "") + " g")]
    if t["unknown"]:
        lines.append(tr("{0} meals still without numbers", t['unknown']))
    items = [item(f"{tr(SLOTS.get(m['slot'], m['slot']))}: {m['text']}",
                  [f"{'~' if m.get('estimated') else ''}{m['kcal']} kcal" if m["kcal"] is not None else "—"])
             for m in t["meals"]]
    items += [item((tr("Taken: ") if s["taken"] else tr("To take: ")) + s["name"], [tr(TIMES[s["time_of_day"]])])
              for s in t["supplements"]]
    return display(tr("At the table today"), lines=lines, items=items,
                   actions=[action(tr("Log meal"), "food_meal", style="primary")] +
                           [action(tr("Taken {0}", s['name']), "food_taken", {"supplement": s["id"]})
                            for s in t["supplements"] if not s["taken"]][:3])


def _meal(text: str, slot: str = "", kcal: int | None = None, protein: int | None = None, date: str = "") -> dict:
    meal = food.add_meal(text, slot=slot, day=date, kcal=kcal, protein=protein)
    _estimate_async(meal)
    return {"saved": True, "id": meal["id"], "slot": meal["slot"], "estimating": meal["kcal"] is None,
            "undo": undo("food_meal_delete", meal=meal["id"])}


def _diet(kcal: int | None = None, protein: int | None = None, rules: str = "", notes: str = "") -> dict:
    if any(v not in (None, "") for v in (kcal, protein, rules, notes)):
        d = food.set_diet({k: v for k, v in {"kcal": kcal, "protein": protein, "rules": rules or None,
                                              "notes": notes or None}.items() if v not in (None, "")})
    else:
        d = {**food.diet(), "unchanged": True}   # read only: no «Fatto» in the chat
    lines = [tr("Goal: {0} kcal · {1} g protein", d['kcal'] or '—', d['protein'] or '—')] + d["rules"][:10]
    return {**d, "display": display(tr("Diet"), lines=lines, actions=[action(tr("Edit"), "food_diet")])}


def _supplements() -> dict:
    items = food.supplements(True)
    return {"items": items, "display": display(tr("Supplements"), items=[
        item(s["name"], [s.get("dose") or "", tr(TIMES[s["time_of_day"]]), tr("paused") if s["status"] == "paused" else ""])
        for s in items], lines=[] if items else [tr("No supplements.")],
        actions=[action(tr("Add"), "food_supplement", style="primary")])}


S, I, B = {"type": "string"}, {"type": "integer"}, {"type": "boolean"}
SUP = {"type": "string", "description": "supplement id or name"}
G = "nutrition"
kit.tools([
    MCPTool(name="food_today", description="Today's summary: meals, kcal and protein against the diet, supplements.",
            parameters={"type": "object", "properties": {"date": S}},
            handler=lambda date="": (lambda t: {**t, "display": _today_display(t)})(
                food.day_summary(__import__("datetime").date.fromisoformat(date) if date else None)),
            title="Today", clients=["telegram", "ui"], telegram_group=G, telegram={"section": "Meals", "primary": 1}),
    MCPTool(name="food_meal", description=("Log a meal: text (what), slot colazione|pranzo|cena|spuntino, kcal and protein if known "
                                            "(otherwise the assistant estimates them)."),
            parameters={"type": "object", "properties": {"text": S, "slot": {"type": "string", "enum": list(SLOTS)},
                                                         "kcal": I, "protein": I, "date": S}, "required": ["text"]},
            handler=_meal, title="Log meal", method="POST", clients=["telegram", "ui"], telegram_group=G,
            telegram={"section": "Meals", "primary": 2}),
    MCPTool(name="food_meals", description="Meals of the last days (days, default 7).",
            parameters={"type": "object", "properties": {"days": I}},
            handler=lambda days=7: {"items": food.meals("", days)}, title="Meals", clients=["telegram", "ui"],
            telegram_group=G, telegram={"section": "Meals"}),
    MCPTool(name="food_meal_delete", description="Delete a logged meal.",
            parameters={"type": "object", "properties": {"meal": S}, "required": ["meal"]},
            handler=lambda meal: food.delete_meal(meal), title="Delete meal", method="POST",
            clients=["telegram", "ui"], telegram_group=G, telegram={"section": "Meals"}),
    MCPTool(name="food_diet", description=("The diet: with no arguments it shows it; kcal, protein (g), rules (one per line) and notes "
                                            "change it."),
            parameters={"type": "object", "properties": {"kcal": I, "protein": I, "rules": S, "notes": S}},
            handler=_diet, title="Diet", method="POST", clients=["telegram", "ui"], telegram_group=G,
            telegram={"section": "Diet", "primary": 3}),
    MCPTool(name="food_supplements", description="The supplements the user takes.",
            parameters={"type": "object", "properties": {}}, handler=_supplements, title="Supplements",
            clients=["telegram", "ui"], telegram_group=G, telegram={"section": "Supplements", "primary": 4}),
    MCPTool(name="food_supplement", description=("Add or edit a supplement: name, dose, time_of_day morning|midday|afternoon|evening|any, days "
                                                  "(0=Mon..6=Sun, empty = every day), training_days_only, with_food, status active|paused."),
            parameters={"type": "object", "properties": {
                "supplement": SUP, "name": S, "dose": S, "time_of_day": {"type": "string", "enum": list(TIMES)},
                "days": {"type": "array", "items": I}, "training_days_only": B, "with_food": B,
                "status": {"type": "string", "enum": ["active", "paused"]}}},
            handler=lambda supplement="", **kw: food.save_supplement(
                kw, food.find_supplement(supplement)["id"] if supplement else None),
            title="Supplement", method="POST", clients=["telegram", "ui"], telegram_group=G,
            telegram={"section": "Supplements"}),
    MCPTool(name="food_taken", description="Mark a supplement as taken (today or date).",
            parameters={"type": "object", "properties": {"supplement": SUP, "date": S}, "required": ["supplement"]},
            handler=lambda supplement, date="": food.take(supplement, date), title="Taken", method="POST",
            clients=["telegram", "ui"], telegram_group=G, telegram={"section": "Supplements", "primary": 5}),
    MCPTool(name="food_supplement_delete", description="Delete a supplement.",
            parameters={"type": "object", "properties": {"supplement": SUP}, "required": ["supplement"]},
            handler=lambda supplement: food.delete_supplement(supplement), title="Delete supplement",
            method="POST", clients=["telegram", "ui"], telegram_group=G, telegram={"section": "Supplements"}),
], prefix="food_")

transfer = Transfer("demeter", kit.hub, sections=[
    StoreSection("dieta", "Diet", kit.store, ["diet"], icon="leaf"),
    StoreSection("pasti", "Meals", kit.store, ["meal"], icon="list", title=lambda r: r["data"].get("text", "")),
    StoreSection("integratori", "Supplements", kit.store, ["supplement", "intake"], icon="droplet",
                 title=lambda r: r["data"].get("name", "")),
])
app.include_router(transfer.router())
kit.caps.update({**recap.capabilities(), **llm_capabilities([
    usecase(ESTIMATE_USE, "Nutrition · kcal estimate", chain="fast",
            help="Estimates kcal and protein of a meal described in words.")])})
kit.capabilities(transfer.capabilities)
kit.webui(icon="leaf", color="green", description="Diet, meals with estimated calories, supplements in the week plan.",
          pages=[page("today", "Nutrition", element="demeter-today", icon="leaf", order=80,
                      help="The meals of the day with calories and protein (estimated by the assistant if you don't write them), the supplements to take."),
                 page("diet", "Diet", element="demeter-diet", icon="target", order=81, parent="today"),
                 page("supplements", "Supplements", element="demeter-supplements", icon="droplet", order=82,
                      parent="today")],
          widgets=[widget("today", "Today's nutrition", element="demeter-widget", sizes=["s", "m"], size="m",
                          auto=True, open_page="today", icon="leaf")])
kit.finish()
