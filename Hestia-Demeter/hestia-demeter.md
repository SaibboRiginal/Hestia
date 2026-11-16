# Hestia-Demeter 🥗

**Role:** Nutrition («Alimentazione») — diet, meals, supplements and intakes; a coach of the weekly plan
**Node:** main host (with the other domain modules)
**Stack:** Python · FastAPI · Docker · `hestia_common.module_kit`
**Port:** 19026 · Dossier: `docs/work/2026-10-24-tutto-brainstorm-cindy/` (W5, brainstorm A5)

---

## Responsibility

- Archive `food-store`: `diet` (one row `current`: kcal and protein per day, rules in plain words, notes), `meal`
  (date, slot colazione/pranzo/cena/spuntino, text, kcal, protein, `estimated`), `supplement` (dose, part of the
  day, weekdays, only on training days, with food, active/paused), `intake` (one per supplement per day).
- A meal logged without numbers is estimated in the background by the assistant (Oracle use case `demeter.stima`,
  answer JSON `{kcal, protein}`, marked `estimated`); the owner's numbers always win (`PUT` clears `estimated`).
  Oracle offline → the meal stays without numbers and the day says how many are missing.
- **Coach** (Hub tag `coach`, `/api/coach/*`): every active supplement is a `slot` need per day in its part of the day;
  «only on training days» → `with: {tag: workout, relation: same_day}` so the plan puts it next to the workout.
  Taking one reports `done` to the planner; any change of diet or supplements reports `changed`.
- Hygieia keeps the products in the cabinet (stock, purchases); Demeter decides what is taken and when.
- Recap piece «Alimentazione» (yesterday's meals and kcal, today's supplements). Export/import sections `dieta`,
  `pasti`, `integratori`.

## API (`/api/food`)

`GET /today?day=` · `GET/POST /meals` · `PUT/DELETE /meals/{id}` · `GET/PUT /diet` · `GET/POST /supplements` ·
`PUT/DELETE /supplements/{id}` · `POST /supplements/{id}/take` · coach contract `/api/coach/needs|fit|placed|review`.

## Tools (Telegram area «Alimentazione»)

`cibo_oggi`, `cibo_pasto`, `cibo_pasti`, `cibo_pasto_elimina`, `cibo_dieta`, `cibo_integratori`, `cibo_integratore`,
`cibo_preso`, `cibo_integratore_elimina`. `cibo_dieta` without arguments only shows the diet and answers
`unchanged: true` (the chat shows no «Fatto»).

## WebUI plugin

Pages **Alimentazione** (`demeter-today`: day by day, kcal and protein against the diet, meals added, edited, deleted with «Annulla», supplements «Preso»), **Dieta** (`demeter-diet`) and **Integratori** (`demeter-supplements`: weekdays, pause); widget «Alimentazione di oggi» (the frame draws the title, the body shows only kcal and meals). Built from `ui/` in the image (`hestia_common.module_kit` `kit.webui`).

## Tests

`Hestia-Demeter/tests/test_demeter.py` and `tests/test_webui_plugin.py` (FakeArchive with a fake model answer).


**2026-11-14 (backend English, dossier `docs/work/2026-11-14-backend-inglese`)**: tool descriptions, the module manual and the meal estimate prompt are English. What people read about the tools comes from `hestia_common/locales/<lang>/tools.json`.

**2026-11-15 (owner's language, dossier `docs/work/2026-11-14-backend-inglese`)**: the notices, errors and cards this module shows go through `hestia_common.i18n.t` and follow «Lingua».

**2026-11-15 (WebUI page in the owner's language, dossier `docs/work/2026-11-14-backend-inglese`)**: the texts of this module's WebUI page and widgets go through `tr` of `@hestia/webui-sdk` and follow «Lingua»; source texts in English, Italian in `Hestia-Shared/hestia_common/locales/it/messages.json`.

**2026-11-16 (no Italian in the code, dossier `docs/work/2026-11-14-backend-inglese` v2.0)**: every text is English in the code; Italian lives only in `Hestia-Shared/hestia_common/locales/it/messages.json`. Labels declared at registration (manifest, capabilities, agenda rules, settings) are plain English, translated at the edge.
