# SPEC — Self care module (Hestia-Hygieia): products, routines, tracking over time

| | |
|---|---|
| **Version** | 2.2 |
| **Source** | User via external chat (Claude Code cloud session, project thread "Modulo Self care") · 2026-10-17 |
| **Status** | Approved by the user (v2.0 answers §13). Implementation starts after the module-plugin contract (thread "Plugin dei moduli nei client") is on main |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).

User's words (summary, Italian original in the thread): new modules that enrich what the assistant knows about
the user, built **like serious standalone apps** ("non limitarti, fallo veramente completo"). Self care: the list of
cosmetics and products used (face, hair, body, etc.), the **routines** that use them (morning / evening, ordered
steps like *detergente > retinolo > crema*), so usage and **changes over time** can be checked. Functional, easy
UX/UI, MCP tools for the AI as usual, pages and widgets plugged into clients.
v2.0 (user, same thread): name Hygieia OK. **No fixed routines and no nagging**: routines are things to do about
N times a week, some only once a day, some never on the same day as others (retinol and acids); reminders at most
1–2 times a week; never 999 reminders piling up when ignored: **one** reminder that says how many times it was
skipped (idea valid for every module). Future: an audio client where the assistant speaks notifications. Journal
per body part. Start after the plugin contract.

---

## 1. Goal

One module that owns everything about personal care:
1. **Inventory** of every product, with its lifecycle (wishlist → in stock → opened → finished / thrown away),
   active ingredients, expiry after opening, cost.
2. **Routines** per area and moment of the day, as ordered steps, with day rules (retinol only Mon/Wed/Fri),
   waiting times and versions: every change is kept, so "what was I using in March?" has an answer.
3. **Tracking**: what was actually done each day (one tap), product usage, a light condition journal
   (skin, hair…), statistics and a timeline of changes, so cause and effect can be seen.
4. **Assistant knowledge**: the assistant always knows the current routines and products and can read history,
   log, edit and advise through MCP tools.
5. **UI** as client plugins (pages + widgets) using the contract of the plugin thread; Telegram through commands.

Out of scope: medical advice beyond common cosmetic knowledge; e-commerce; ordering products.

## 2. Name, place, boundaries

- **Hestia-Hygieia** (Greek goddess of health and cleanliness, root of "hygiene"), container `hestia_hygieia`,
  port **19018** (19017 Guardaroba, 19019 Coach, agreed between the parallel threads), node Main PC, type `module`,
  tags `domain:selfcare`. Template: Hestia-Dummy + Scout's registration/tools pattern.
- Who does what (strict module boundaries):

| Need | Owner | How |
|---|---|---|
| Data (tables) | **Archive** | new typed tables + router `/api/selfcare-store` (pattern of `presence.py`) |
| Domain logic, validation, stats, routine engine | **Hygieia** | its own API, never a DB connection |
| When the planner runs | **Chronos** | one agenda job `selfcare.planner` registered with `agenda_client` (daily, default 20:30), user-editable |
| Delivering reminders / alerts, "Fatto / Salta / Dopo" buttons | **Hermes** | Hygieia emits events; button actions route back to Hygieia via Hub |
| Tunables | **Themis** | `settings_client.setting(...)`, no new env var |
| Reasoning, advice, natural-language edits | **Oracle** | only through Hygieia's MCP tools |
| Photos | **Archive** blob store `/api/blobs` | generic store designed by the Guardaroba thread (owner); Hygieia only references blob ids |
| Pages / widgets on clients | **WebUI** (and future clients) | plugin manifest served by Hygieia, contract from the plugin thread |
| Product lookup by barcode (phase 5) | **Atlas** (fetch) | Open Beauty Facts public data, through Hub |

## 3. Data model (Archive tables, all with `created_at` / `updated_at`)

Lists of values (areas, categories, actives, units) are **data with seeded defaults**, editable by the user, not
code enums — new ones never need a code change.

### 3.1 Areas — `selfcare_areas`
`key`, `label`, `icon`, `order`, `archived`. Seed: viso, occhi, labbra, capelli, cuoio capelluto, barba, corpo,
mani, piedi, unghie, denti e bocca, profumo. Every product/routine/journal entry references one or more areas.

### 3.2 Products — `selfcare_products`
| Field | Notes |
|---|---|
| `id`, `name`, `brand`, `line` | `line` = product line/variant (e.g. "Hydra Boost") |
| `areas[]`, `category` | category from a seeded editable list: detergente, struccante, tonico, esfoliante (AHA/BHA/fisico), siero, trattamento, crema idratante, contorno occhi, SPF, maschera, olio, balsamo labbra, shampoo, balsamo, maschera capelli, styling, bagnoschiuma, crema corpo, deodorante, scrub, rasatura, dopobarba, dentifricio, collutorio, profumo, integratore, strumento (es. gua sha, spazzolino), altro |
| `actives[]` | `{name, percent?}` from an editable list (retinolo, retinale, niacinamide, vitamina C, AHA glicolico/lattico, BHA salicilico, PHA, acido azelaico, peptidi, ceramidi, acido ialuronico, benzoyl peroxide, SPF filtri…) |
| `inci` | optional full ingredient text |
| `size`, `unit` | ml / g / pz / applicazioni |
| `price`, `currency`, `shop`, `url` | cost tracking |
| `status` | `wishlist` · `stock` (bought, closed) · `in_use` · `finished` · `discarded` · `paused` |
| `purchased_at`, `opened_at`, `pao_months`, `expires_at` | PAO = period after opening (the "12M" jar icon); effective expiry = min(`expires_at`, `opened_at` + PAO) |
| `level` | estimated remaining: `full` · `3/4` · `half` · `1/4` · `almost_empty` (manual, one tap) |
| `rating` (1–5), `verdict` | `repurchase` · `maybe` · `never` |
| `photo_id`, `barcode`, `tags[]`, `notes` | |
| `replaces_id` | when this product replaced another one (timeline of changes) |

One row = **one physical item**. Buying the same product again creates a new row linked by `product_key`
(normalised brand+name) so stats can say "this is my 4th bottle, each lasts ~3 months".

### 3.3 Product events — `selfcare_product_events`
`product_id`, `type` (`bought`, `opened`, `level_changed`, `finished`, `discarded`, `rated`, `replaced`, `note`),
`at`, `data`. Written by Hygieia on every lifecycle change → per-product timeline and global "what changed".

### 3.4 Routines — `selfcare_routines` + `selfcare_routine_versions`
- Routine: `id`, `name` (e.g. "Viso sera", "Maschera capelli"), `areas[]`, `slot` (`morning` · `evening` · `anytime`
  · custom label), `cadence`, `reminder` (on/off, **off by default**), `status` (`active` · `paused` · `archived`),
  `order`, `color`/`icon`, `current_version`.
- **Cadence = an option chosen per routine** (v2.1: the user picks it in one control; default `target`). One of:
  - `daily` — every day (e.g. face morning);
  - `target` — `{times: 2, per: week|month}`, optionally a range `{min: 1, max: 2}` (e.g. hair mask 1–2/week);
  - `as_needed` — no goal, only logged when done;
  - `fixed_days` — mandatory on chosen weekdays.
  `daily` and `fixed_days` are "obbligatorie" (missing one counts as skipped in stats); `target` = "almeno N"
  (e.g. two face routines, each at least 2×/week); stats work the same for all modes.
- `favorite` (bool) + `order`: favourites are the ones on the WebUI Home quick widget (§9).
  Plus constraints: `max_per_day` (default 1), `min_gap_hours` (e.g. 48 for an exfoliation), and
  `not_same_day_as[]` (other routines/steps). Conflicts on actives (§4) add `not_same_day_as` pairs **automatically**
  (a routine with retinol and one with AHA/BHA), the user can add more by hand.
- Steps are stored in an **immutable version** (`routine_id`, `version`, `steps` JSON, `reason`, `valid_from`):
  every edit of the steps creates version N+1, so the history of the routine is exact.
- Step: `{id, order, product_id | null, label (when no product, e.g. "massaggio cuoio capelluto"),
  amount ("2 gocce", "noce"), wait_seconds, cadence (same shape as the routine's; default = every time the routine
  runs), not_same_day_as[], optional, note}`.
  *Example "Viso sera"* (daily): detergente → retinolo (target 3/week, not with AHA, attendi 20 min) →
  esfoliante AHA (target 1/week) → crema idratante → (opzionale) olio. Each evening the planner decides whether
  the retinol or the AHA step is in, from what was done this week; on a retinol day the AHA step is shown
  greyed "non oggi: retinolo".
- **Skin cycling** and similar rotations = steps with targets + `not_same_day_as`, no special calendar.

### 3.5 Logs — `selfcare_logs`
One row per routine run: `routine_id`, `version`, `date`, `done_at`, `status` (`done` · `partial` · `skipped`),
`steps` (per step: done/skipped + product actually used, so a substitution is recorded), `note`, `source`
(`webui` · `telegram` · `assistant` · `reminder_button`). Ad-hoc usage outside routines (a mask on Sunday) is a log
with `routine_id = null` and one step.

### 3.6 Journal — `selfcare_journal` (per body part, v2.0; optional, hidden until enabled — v2.1)
Purpose: see whether products and routines actually work (e.g. pimples trend down since retinol started).
One entry per area per day (one quick form can fill several areas at once). `date`, `area`, `scores` (user-chosen metrics per area, 1–5: viso → idratazione, brufoli, rossori, oleosità,
sensibilità; capelli → caduta, forfora, lucentezza…; metrics are an editable list per area), `tags`
(ciclo, stress, sole, viaggio, nuovo prodotto…), `note`, `photo_ids[]`. Optional and quick (3 taps).

## 4. What Hygieia computes (domain logic)

- **Planner (v2.0)** — for any day: every routine/step with its state `due` (goal behind: done this period <
  target and days left are getting short), `suggested` (could be done, goal not yet met), `ok` (goal met),
  `blocked` (max per day, min gap, or a `not_same_day_as` partner already done today — with the reason), `done`.
  Priority = how far behind the goal is. Nothing is ever "overdue forever": a missed week just starts a new period.
- **Today**: the planner for today, in slot order; next one suggested.
- **Adherence & streaks** per routine (week / month / all time), skipped steps most often.
- **Product usage**: uses per product (from logs), days since opened, estimated finish date
  (from previous bottles of the same `product_key` or from size ÷ observed uses), cost per month / per use.
- **Alerts** (each a Hermes event, dedupe per product): expiring within `selfcare.alerts.expiry_days`,
  level `almost_empty` or predicted finish within `selfcare.alerts.restock_days` → shopping list, product in a
  routine but `finished`.
- **Conflicts / compatibility** (advisory, never blocking): seeded editable rules on actives in the same slot/day
  (retinoide + AHA/BHA, retinoide + benzoyl peroxide, vitamina C + AHA, …), and "SPF missing in a morning face
  routine". Shown in the routine editor and exposed to the assistant.
- **Changes over time**: one merged timeline (routine versions, product opened/finished/replaced, journal) and a
  "periodo" view: products and routines in use in a chosen date range, journal trend beside it.
- **Shopping list**: wishlist + restock suggestions, mark as bought → creates the `stock` item.

## 5. API (Hygieia, all under `/api/selfcare`, declared in swagger)

CRUD: `areas`, `products` (+ `/{id}/events`, `/{id}/open`, `/{id}/finish`, `/{id}/level`, `/{id}/duplicate`
for "ricomprato"), `routines` (+ `/{id}/versions`, `/{id}/reorder`, `/{id}/pause`), `logs`, `journal`,
`lists/{categories|actives|metrics|conflicts}`.
Views: `GET today?date=`, `GET stats?from=&to=`, `GET timeline?from=&to=`, `GET period?date=`, `GET shopping`,
`GET overview` (compact text+json summary for the assistant, see §6).
Actions (called by Chronos jobs and Hermes buttons): `POST reminders/run` (planner job),
`POST logs/quick {routine_id, status}`.
Plugin (contract `docs/work/2026-10-17-client-plugins/SPEC.md` v2.3): `GET /api/ui/manifest` built by `plugin_client`,
UI API under `/api/ui/`. Quick actions (§4.2b): dynamic `routine_done` with `source: /api/ui/quick/routines` (one chip
per favourite / due-today routine, `state` todo|done|late, `hint` "1/2 sett."), `POST /api/ui/routines/{id}/done`,
undo `DELETE /api/ui/routines/{id}/done/today`; `product_used` same shape for favourite products.
Context: `GET /api/module/context` — the same short caveman summary as `selfcare_overview`, common contract of the
three new modules (Guardaroba, Self care, Coach) so Oracle can include it in its context: `?budget=` →
`{module, domain, updated_at, text}`, Hub tag `context`, built with `hestia_common.context_client.ModuleContext`
(written by the Guardaroba thread, its SPEC §6.2). Photo uploads follow the plugin contract (base64 ≤ 8 MB, resized by the client).

## 6. Assistant (MCP tools, `hestia_common.mcp_helpers.MCPTool`)

| Tool | Does |
|---|---|
| `selfcare_overview` | current routines with steps, products in use, alerts — short, caveman-style; the assistant's context |
| `selfcare_today` | what is left today / tonight |
| `selfcare_log` | "fatto la routine sera", "ho saltato il retinolo", ad-hoc use |
| `selfcare_products` / `selfcare_product_get` | search by name/area/active/status |
| `selfcare_product_add` / `_update` / `_status` | add from chat ("ho comprato il siero X 30ml"), open, finish, rate |
| `selfcare_routines` / `selfcare_routine_get` | incl. version history |
| `selfcare_routine_edit` | add/remove/move steps, change days — creates a new version with `reason` |
| `selfcare_journal_add` | "pelle irritata oggi" |
| `selfcare_stats` / `selfcare_timeline` | adherence, usage, what changed in a period |
| `selfcare_check` | compatibility check of a routine or of a product the user wants to add |
| `selfcare_shopping` | shopping list |

Writes from the assistant are the user's own data asked in chat, so they apply directly and are reported in the
answer (and logged with `source=assistant`); routine edits are reversible (previous version kept).
How the overview reaches the assistant's standing context (always-on snippet vs. tool call) follows the
"context contribution" part of the plugin contract; until then it is the `selfcare_overview` tool.
Telegram gets the visible ones as commands through Hub discovery (`telegram_group: "Self care"`).

## 7. Reminders and notifications

Principle (v2.0): **few, useful, never piling up.**
- Reminders are **off by default**, per routine. Master switch `selfcare.reminders.enabled`.
- One agenda job `selfcare.planner` (daily, default 20:30, the user moves it in the agenda; his edit wins) calls
  `POST /api/selfcare/reminders/run`. Hygieia nudges a routine only when it is `due` (behind its goal) and not
  `blocked`, and at most `selfcare.reminders.max_per_week` times per routine (default 2). Daily routines done
  every day are never nudged.
- **One live reminder per routine**: event `selfcare.reminder` with `dedupe_key = selfcare.reminder.<routine_id>`.
  If the previous one is still unanswered, the new one **replaces** it (`closes` the old key, then sends the new one)
  and says how many times it was skipped: «Maschera capelli — 0/1 questa settimana, saltata 3 volte». So there is
  never more than one per routine on any client.
- Actions **Fatto** · **Salta** · **Non questa settimana**; the button routes back to `POST logs/quick` (Fatto logs it,
  Salta counts a skip, Non questa settimana silences that routine until the next period).
- **Generic need, owned by Hermes**: Marko wants this "one live notification with a skip counter" for every module.
  Proposed as a Hermes feature (event key `replaces: <dedupe_key>` + `repeat_count` kept by Hermes, updating the
  notification in place on every client); handed to the channel session to schedule in Hermes. Until it exists,
  Hygieia uses `closes` + new event as above (same result for the user).
- Text of reminders and alerts is short plain Italian, readable aloud as-is, so the future **audio client** (the
  assistant speaking notifications) needs nothing from this module.
- Alerts of §4 → Hermes events `selfcare.alert` (level info, dedupe per product+type). Presence quiet hours are
  already handled by Hermes.

## 8. Settings (Themis, `hestia_common.settings_client`)

| Key | Type / default | Notes |
|---|---|---|
| `selfcare.reminders.enabled` | bool, true | master switch (each routine is still off until enabled) |
| `selfcare.reminders.max_per_week` | int, 2 | max nudges per routine per week |
| `selfcare.alerts.expiry_days` | int, 30 | expiry warning |
| `selfcare.alerts.restock_days` | int, 14 | predicted finish warning |
| `selfcare.alerts.enabled` | bool, true | |
| `selfcare.journal.enabled` | bool, false | shows the Diario tab and journal tools |
| `selfcare.journal.prompt` | enum off/after_evening/weekly, off | ask for a journal entry after the evening routine |
| `selfcare.default_pao_months` | int, 12 | used when PAO unknown |
| `selfcare.currency` | string, EUR | |

## 9. UI (client plugins — needs the plugin contract on main)

Mobile-first, design system `Hestia-WebUI/frontend/DESIGN-SYSTEM.md`, side panels with `<hx-resize>`.

**Page "Self care"** (always visible, hideable per client per the plugin contract), tabs:
1. **Oggi** — cards per routine due today in slot order; each step is a big tappable row (product photo/initial,
   name, amount, wait timer that starts when the previous step is ticked); "Tutto fatto" in one tap; skipped
   steps greyed; tomorrow preview.
2. **Routine** — list grouped by slot; editor: drag-reorder steps, pick product from inventory (search + filter by
   area/category) or free label, day chips (L M M G V S D), cycle builder, wait time, compatibility warnings inline,
   "reason for change" field, version history with diff ("v3 → v4: aggiunto niacinamide").
3. **Prodotti** — grid/list toggle, filters (area, category, status, active), sort (scadenza, ultimo uso, prezzo);
   badges: in uso / scorta / in scadenza / quasi finito; quick actions swipe/menu: apri, livello, finito, ricomprato;
   detail panel: info, actives, PAO countdown, usage chart, timeline, routines that use it. Fast add form
   (name+brand+category required, everything else optional), later barcode scan.
4. **Diario** — quick entry (area, sliders, tags, note, photo), trend chart per metric with markers where products
   or routines changed.
5. **Statistiche & storia** — adherence heatmap (calendar), streaks, uses per product, spend per month, the merged
   timeline, "periodo" picker.
6. **Lista spesa** — wishlist + restock suggestions.

**Home quick log (v2.1, top priority of the UI)** — implemented as plugin **quick actions** (chips drawn by the
WebUI, zero load, pinned via ★) plus the widget "Self care" on the WebUI **Home**: favourite routines as
big buttons, **one tap = "fatta oggi"** (toast with Annulla, no dialog), a badge with this week's progress
(1/2), a second tap shows the steps to untick a skipped one; also favourite products for an ad-hoc use (mask).
Everything else is optional detail.

**Widgets** (dashboard): "Routine di oggi" (checklist, tick from the widget), "Prossima routine" (compact),
"In scadenza / da ricomprare", "Streak".

## 10. Phases (each shippable alone)

1. **Backend core**: service skeleton (Dummy template, Hub registration, compose, Swagger), Archive tables + store
   router, products / areas / lists CRUD, routines with versions, logs, `today`, MCP tools for these. Tests.
2. **Tracking & insight**: product events/lifecycle, usage stats, finish prediction, alerts, conflicts, timeline,
   journal, shopping list, Hermes events.
3. **Reminders**: planner agenda job, one live reminder per routine with skip counter, Hermes buttons → quick log.
4. **UI**: plugin manifest, WebUI page (6 tabs) and widgets — after the plugin contract is on main.
5. **Extras**: photos (shared `/api/blobs` store), barcode scan in WebUI + Open Beauty Facts lookup via Atlas, CSV
   import/export, journal photo comparison side by side.

## 11. Acceptance criteria

- I add "CeraVe Detergente schiumoso 236 ml" in < 15 s on phone; opening it sets `opened_at` and the PAO countdown.
- "Viso sera" with retinol 3/week and AHA 1/week: after a retinol evening the AHA step shows "non oggi: retinolo";
  late in the week the retinol step becomes `due` if I'm behind; nothing is tied to fixed weekdays.
- Editing the routine creates a new version; on "periodo = marzo" I see the routine and products as they were then.
- One tap logs the routine; product uses and the streak update.
- Asking the assistant "cosa uso stasera?" / "ho finito la crema" / "togli il retinolo per una settimana" works via
  tools, and the change shows in the UI.
- A product near PAO expiry or almost finished produces one Hermes notification (no duplicates) and appears in
  the shopping list.
- Retinol and AHA in the same evening shows a warning in the editor and in `selfcare_check`.
- A routine with reminders on, ignored for 3 weeks, shows **one** notification that says "saltata 3 volte", never
  more than `max_per_week` nudges a week; Fatto / Salta / Non questa settimana work from Telegram and WebUI.
- No direct service URL, no DB access outside Archive, no new env tunable, logs `event=…`.

## 12. Design decisions

- **Typed tables, not generic `entities`**: routines/logs/versions need relational queries (stats, periods);
  generic JSON entities would push that logic into Python scans.
- **Versions immutable, logs reference the version** → history is exact even after edits.
- **One row per physical item** + `product_key` → real usage durations and cost per bottle.
- **Lists are data** (areas, categories, actives, metrics, conflict rules) → extensible without code (same idea as
  presence states).
- **Reminder time belongs to the agenda**, not to the module; Hygieia only proposes the default.
- **Goals, not calendars** (v2.0): cadence = times per period + constraints; the planner suggests, the user decides.
- **One live reminder per routine**, replaced not stacked; the generic version belongs to Hermes.
- **Advice is advisory**: conflicts warn, never block.

## 13. User decisions (v2.0, 2026-10-17)

1. Name **Hygieia**: yes.
2. Reminders off by default; flexible goals instead of fixed routines; at most 1–2 nudges a week; one reminder with
   a skip counter instead of many (to be generic for all modules, via Hermes).
3. Journal per body part: yes (phase 2).
4. Implementation starts after the plugin contract is on main.
