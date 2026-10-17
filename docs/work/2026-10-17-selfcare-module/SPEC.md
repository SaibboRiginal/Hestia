# SPEC — Self care module (Hestia-Hygieia): products, routines, tracking over time

| | |
|---|---|
| **Version** | 1.2 |
| **Source** | User via external chat (Claude Code cloud session, project thread "Modulo Self care") · 2026-10-17 |
| **Status** | Draft — waiting for user approval. UI part waits for the module-plugin contract (thread "Plugin dei moduli nei client") to be on main |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).

User's words (summary, Italian original in the thread): new modules that enrich what the assistant knows about
the user, built **like serious standalone apps** ("non limitarti, fallo veramente completo"). Self care: the list of
cosmetics and products used (face, hair, body, etc.), the **routines** that use them (morning / evening, ordered
steps like *detergente > retinolo > crema*), so usage and **changes over time** can be checked. Functional, easy
UX/UI, MCP tools for the AI as usual, pages and widgets plugged into clients.

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
| When a reminder fires | **Chronos** | agenda jobs registered by Hygieia with `agenda_client` (key `selfcare.routine.<id>`), user-editable |
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
- Routine: `id`, `name` (e.g. "Viso sera"), `areas[]`, `slot` (`morning` · `evening` · `anytime` · `weekly` · custom
  label), `schedule` (`daily` · days of week · every N days · RRULE), `reminder` (on/off; time lives in the agenda job),
  `status` (`active` · `paused` · `archived`), `order`, `color`/`icon`, `current_version`.
- Steps are stored in an **immutable version** (`routine_id`, `version`, `steps` JSON, `reason`, `valid_from`):
  every edit of the steps creates version N+1, so the history of the routine is exact.
- Step: `{id, order, product_id | null, label (when no product, e.g. "massaggio cuoio capelluto"),
  amount ("2 gocce", "noce"), wait_seconds, days (subset of week or "every N days" / "alternate with step X"),
  optional, note}`.
  *Example "Viso sera"*: detergente → (lun/mer/ven) retinolo, attendi 20 min → (mar/gio/sab) niacinamide →
  crema idratante → (opzionale) olio.
- **Rotation / cycling** supported via step `days` and named cycles (e.g. skin cycling 4 nights: esfoliazione,
  retinolo, recupero, recupero) — a cycle is a step rule `cycle: {length: 4, position: [1]}` anchored to a start date.

### 3.5 Logs — `selfcare_logs`
One row per routine run: `routine_id`, `version`, `date`, `done_at`, `status` (`done` · `partial` · `skipped`),
`steps` (per step: done/skipped + product actually used, so a substitution is recorded), `note`, `source`
(`webui` · `telegram` · `assistant` · `reminder_button`). Ad-hoc usage outside routines (a mask on Sunday) is a log
with `routine_id = null` and one step.

### 3.6 Journal — `selfcare_journal`
`date`, `area`, `scores` (user-chosen metrics per area, 1–5: viso → idratazione, brufoli, rossori, oleosità,
sensibilità; capelli → caduta, forfora, lucentezza…; metrics are an editable list per area), `tags`
(ciclo, stress, sole, viaggio, nuovo prodotto…), `note`, `photo_ids[]`. Optional and quick (3 taps).

## 4. What Hygieia computes (domain logic)

- **Today**: which routines/steps apply today (day rules, cycles), done vs. pending, next one due.
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
Actions (called by Chronos jobs and Hermes buttons): `POST reminders/fire {routine_id}`,
`POST logs/quick {routine_id, status}`.
Plugin: `GET /api/plugin/manifest` (shape from the plugin thread).
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

- A routine with `reminder` on registers an agenda **job** `selfcare.routine.<id>` (RRULE from the routine
  schedule, default time from `slot`: morning 07:30, evening 22:00 — only defaults, the user edits the job in the
  agenda and his edit wins). Paused routine → job paused; archived → job cancelled.
- The job calls `POST /api/selfcare/reminders/fire` → Hygieia checks it is not already done today → emits a Hermes
  event `selfcare.reminder` with the steps of today and actions **Fatto** · **Salta** · **Tra 30 min**; the button
  routes back to `logs/quick` (or asks Chronos to re-fire later).
- Alerts of §4 → Hermes events `selfcare.alert` (level info, dedupe per product+type). Presence quiet hours are
  already handled by Hermes.

## 8. Settings (Themis, `hestia_common.settings_client`)

| Key | Type / default | Notes |
|---|---|---|
| `selfcare.reminders.enabled` | bool, true | master switch |
| `selfcare.reminders.snooze_minutes` | int, 30 | "Tra 30 min" button |
| `selfcare.alerts.expiry_days` | int, 30 | expiry warning |
| `selfcare.alerts.restock_days` | int, 14 | predicted finish warning |
| `selfcare.alerts.enabled` | bool, true | |
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

**Widgets** (dashboard): "Routine di oggi" (checklist, tick from the widget), "Prossima routine" (compact),
"In scadenza / da ricomprare", "Streak".

## 10. Phases (each shippable alone)

1. **Backend core**: service skeleton (Dummy template, Hub registration, compose, Swagger), Archive tables + store
   router, products / areas / lists CRUD, routines with versions, logs, `today`, MCP tools for these. Tests.
2. **Tracking & insight**: product events/lifecycle, usage stats, finish prediction, alerts, conflicts, timeline,
   journal, shopping list, Hermes events.
3. **Reminders**: agenda jobs per routine, Hermes buttons → quick log, snooze.
4. **UI**: plugin manifest, WebUI page (6 tabs) and widgets — after the plugin contract is on main.
5. **Extras**: photos (shared `/api/blobs` store), barcode scan in WebUI + Open Beauty Facts lookup via Atlas, CSV
   import/export, journal photo comparison side by side.

## 11. Acceptance criteria

- I add "CeraVe Detergente schiumoso 236 ml" in < 15 s on phone; opening it sets `opened_at` and the PAO countdown.
- "Viso sera" = detergente → retinolo (lun/mer/ven, 20 min) → crema: on Tuesday the retinol step is not shown.
- Editing the routine creates a new version; on "periodo = marzo" I see the routine and products as they were then.
- One tap logs the routine; product uses and the streak update.
- Asking the assistant "cosa uso stasera?" / "ho finito la crema" / "togli il retinolo per una settimana" works via
  tools, and the change shows in the UI.
- A product near PAO expiry or almost finished produces one Hermes notification (no duplicates) and appears in
  the shopping list.
- Retinol and AHA in the same evening shows a warning in the editor and in `selfcare_check`.
- Reminder at the agenda time with Fatto / Salta / Tra 30 min working from Telegram and WebUI.
- No direct service URL, no DB access outside Archive, no new env tunable, logs `event=…`.

## 12. Design decisions

- **Typed tables, not generic `entities`**: routines/logs/versions need relational queries (stats, periods);
  generic JSON entities would push that logic into Python scans.
- **Versions immutable, logs reference the version** → history is exact even after edits.
- **One row per physical item** + `product_key` → real usage durations and cost per bottle.
- **Lists are data** (areas, categories, actives, metrics, conflict rules) → extensible without code (same idea as
  presence states).
- **Reminder time belongs to the agenda**, not to the module; Hygieia only proposes the default.
- **Advice is advisory**: conflicts warn, never block.

## 13. Open points for the user

1. Name **Hygieia** OK?
2. Reminders on by default for new routines, or off until you enable them per routine? (proposed: off)
3. Journal (skin/hair condition) in v1 or later? (proposed: in phase 2, optional)
4. Start with phase 1–3 now (backend, tracking, reminders) while the plugin contract is designed, UI right after?
