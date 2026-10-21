# Hestia-Hygieia 🧴

**Role:** Self care — products (face, hair, body, beard, teeth…), routines as ordered steps, what to do today,
usage over time, history of changes, optional diary per body area
**Node:** main host (with the other domain modules)
**Stack:** Python · FastAPI · Docker · WebUI plugin bundle (Lit, `ui/`)
**Port:** 19018 · Dossier: `docs/work/2026-10-17-selfcare-module/`

---

## Responsibility

- Owns the self care domain: products with their life (wishlist → stock → in use → finished / thrown away,
  level, expiry after opening, price, rating, "lo ricompro"), routines with ordered steps, logs of what was
  done, the optional diary, lists of values (areas, categories, actives, journal metrics, conflict rules).
- Computes everything derived: plan of the day, goal progress and streaks, adherence, product uses and cost per
  use, finish prediction (past bottles, or level), expiry alerts, shopping list, compatibility notes, timeline,
  "what was I using on…".
- **Goals, not calendars**: a routine (and optionally a single step) has a cadence — `daily`, `fixed_days`,
  `target` (at least N times per week/month), `as_needed`. The planner proposes, the user decides.
- **Conflicts are advisory**: active families (retinoid, aha, bha, vitc, bpo…) with seeded rules. Routines whose
  core steps conflict never land on the same day; steps with their own cadence alternate (the most behind wins,
  the other shows "non oggi: X"). A step already done today is a fact and is placed first, so after a retinol
  evening the acid step says "non oggi: <retinolo>" instead of coming back as suggested; when the clash comes from
  another routine done today, X is the product that clashes. Paused steps (`paused_until`) are skipped with their reason.
- Does not call models (Oracle is the brain) and has no database (Archive `selfcare-store`).

## Storage

Archive `/api/selfcare-store/records`: table `selfcare_records (kind, id)` with `data` JSONB, `parent_id`,
`ref_id`, `at`, `updated_at`, `deleted` tombstone, `seq` cursor — same protocol as `hercules-store`.
Kinds: product, event (product history), routine, version (immutable steps per change, with reason and diff),
log, journal, option (user list values), reminder (chain state), alert (last sent).
Hygieia keeps an in-memory mirror pulled by cursor. Archive away → reads keep working
(`[🔄] event=hygieia_mirror_refresh_failed`), writes answer 503.
Archive data epoch: store answers carry `epoch`; when it changes (a backup rollback swapped the database) the mirror is dropped and reloaded from zero (`[🔄] event=hygieia_mirror_reset reason=data_epoch`), so no stale row is written back.

## Planner states

`done` · `due` (behind the goal or a fixed day) · `suggested` (on track, good day for it) · `wait` (too soon after
the last time) · `ok` (goal met this period) · `off` (not a fixed day) · `rest` (as needed) · `blocked` (conflict
with something already done or due today) · `paused`. A target routine is behind when
`remaining*2-1 >= days_left`; spacing between times is `period_days // times`.

## Assistant

- Tools (`selfcare` domain via `module_tool_domains`, REST path `/api/selfcare/tools/<name>`, JSON-RPC `POST /mcp`):
  `selfcare_summary`, `today`, `log`, `products`, `product_get`, `product_add`, `product_update`, `routines`,
  `routine_get`, `routine_create`, `routine_edit` (add / remove / step cadence / pause N days / routine cadence /
  status / reminder / favorite, always with a reason), `undo_routine`, `journal_add`,
  `stats`, `timeline`, `period`, `check`, `shopping` (all prefixed `selfcare_`).
- `GET /api/module/context?budget=`: short caveman lines (left today, goals behind, alerts).
- Every step change keeps a version; `POST /routines/{id}/undo` goes back.

## Reminders and alerts (few, never piling up)

- Agenda job `hygieia.planner` (daily 20:30, editable in the agenda) → `POST /api/selfcare/reminders/run`.
  Only when the common switch `hygieia.reminder.enabled` is on (off by default), and only routines with their
  own reminder switched on, state `due`, not silenced, not already sent today, and under
  `hygieia.reminder.max_per_week` per routine. Event built by `hestia_common.reminders.reminder_event`. Hermes `service.action_required` with
  `replaces: selfcare.reminder.<routine_id>` (one live reminder, Hermes adds the skip counter); target `owner`.
  Actions: **Fatto** (resolves → `quick/routine/{id}`), **Salta** (`routines/{id}/skip`), **Non questa
  settimana** (resolves → `routines/{id}/snooze`).
- Agenda job `hygieia.alerts` (daily 10:00) → `POST /api/selfcare/alerts/run`: expiring / running out / finished
  but still in a routine, at most once a week per product (`replaces: selfcare.alert.<type>.<product_id>`),
  actions **Buttato** / **Ricomprato**.
- Every notification carries `_link` to its plugin page (`routine/<id>` for reminders, `prodotti/<id>` for alerts).
- Texts are short plain Italian, readable aloud as-is (future audio client).

## Client UI (plugin contract)

Icons, never emoji (DESIGN-SYSTEM rule, `docs/work/2026-10-20-icone-nei-client`): `<hxk-icon name tone>`. Slots sun/moon/sparkle, events (bag, unlock, trend-down, check, trash, star, repeat, note, book), alerts hourglass/cart/alert; body areas are labels only.

Bundle `ui/src/index.ts` → `/ui/webui/hygieia.js` (built in the Dockerfile). Pages: oggi (today: one tap per
routine, steps with reasons, wait timers, "ho usato un prodotto"), routine, routine/:id (editor: steps, order,
own cadence, pause, goal, zones, never-same-day, reminder, favorite, adherence, versions), prodotti,
prodotti/:id, diario, statistiche (heatmap, routines, top products, spend, history of
changes, a past day, JSON export), spesa. Widgets: oggi (quick chips), prossima, prodotti (alerts), settimana.
Quick actions: fatta (routines to do today + favorites, undo), uso (favorite products, undo).
A UI change needs `up-all.bat --build hygieia`.

## Settings (Themis, `hygieia.*`)

default_pao_months (12), reminder.enabled (false) and reminder.max_per_week (2) from
`hestia_common.reminders.reminder_settings` (same two settings in every module; each routine still chooses its own
reminder), alerts.enabled (true), alerts.expiry_days (30), alerts.restock_days (14). The diary has no switch: it is
there and used only when wanted. Week start and currency are the personal settings `themis.personal.week_start` /
`themis.personal.currency` (owner Themis, read with `follow_personal()`), never a module copy.

## API (via Hub `/route/hygieia/...`)

See `Hestia-Swagger/swagger.yml` tag *Hygieia*. Groups: meta/options, products (+status, level, repurchase,
use), routines (+undo, plan, done, skip, snooze), today, logs, journal, stats, timeline, period, alerts,
shopping, check, summary, overview, export, quick (Home chips), reminders/run, alerts/run.

## Configuration (infrastructure only)

`SERVICE_NAME`, `SERVICE_BASE_URL`, `HUB_API_URL`, `TZ` (local day for goals and reminders), `HYGIEIA_UI_DIST`.

## Tests

`python -m pytest -q -m unit Hestia-Hygieia/tests` (fake Archive in memory, no network).
