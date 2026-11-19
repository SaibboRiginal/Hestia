# SPEC — Email by PUSH (one Gmail watcher, Iris dispatches) + expenses module (Hestia-Plutus)

| | |
|---|---|
| **Version** | 1.2 |
| **Source** | user via external chat → project brainstorm 2026-10-19, item 3 of the final list (`/mnt/project-files/brainstorm/2026-10-19-idee-e-cloud.md` §0); routed by the project coordinator |
| **Status** | Implemented and merged 2026-10-19 (PR #8); Marko real run pending |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).

User's words (summary, Italian original in the brainstorm): «regola che mi piace sempre il PUSH, mai se non necessario
il POLL». One Gmail watcher, Iris dispatches mails to the modules that subscribed with their own rules, so the agenda is
not full of per-module polling jobs; Scout stops polling. A new expenses module, **complete like the other modules**:
PayPal from the emails, the monthly Hype PDF uploaded in chat (Hype sends no summary by email), quick entry, categories
and budget, `finance_*` tools, WebUI plugin, reflection, reminders. Vision check (Marko): an open, personal "Jarvis";
the finance data set is one of the personal data sets future coaches (item 9) will lean on.

---

## 1. Today (verified in code, 2026-10-19)

- Scout polls: Chronos job `scout.email_cycle` every `scout.cycle.interval` (1800 s) → `POST /api/scout/cycle` →
  for each filter (`scout.mail.senders` / `scout.mail.filter_queries`) `POST iris /api/email/ingest` → Hecate
  `/api/ingest/trigger` (connector `iris_email`, cursor = last run date in Hecate `state.json`) → raw records in Archive
  (domain `real_estate`, deduped by `reference_id`) → Scout reads `get_unevaluated` and extracts listings.
- Iris only searches/sends/threads through Hecate; it does not dispatch incoming mail.
- Hecate reads Gmail with the OAuth token (`gmail.readonly`, `gmail.send`), search only (no history, no watch).
- Chronos `register` is idempotent and keeps user edits, but there is **no way for a module to retire a rule** it no
  longer declares.
- Oracle chat attachments (`/api/chat/document`) are read by the model and not stored: a tool cannot receive them.

## 2. Goal

1. **One** watcher of the mailbox, owned by Hecate (the provider owner). No module talks to Gmail or polls for mail.
2. **Iris dispatches**: modules subscribe with rules; every new mail that matches is delivered to them by push.
3. Scout moves to a subscription; its polling job and interval setting disappear.
4. **Hestia-Plutus** (expenses): a full module like Hygieia/Hercules/Wardrobe, fed by PayPal mails (push from Iris),
   the monthly Hype PDF, and quick manual entry.

Out of scope: bank APIs (GoCardless closed to new users since July 2025; others to evaluate later), investments,
taxes, multi-user accounts, sending money. Outlook mail (Hecate keeps the provider shape so it can be added).

## 3. Mail flow (push)

```
Gmail ──(A light check | B Pub/Sub)──▶ Hecate watcher ──POST route/iris/api/email/incoming──▶ Iris
Iris: match headers against subscriptions ─▶ for each match: ship full mail to Archive (module domain)
      ─▶ POST route/<module>/<path> {subscription, count, reference_ids}   ("doorbell": the parcel is in Archive)
```

### 3.1 Hecate watcher (one per mailbox)
- **A — light check (default, always available):** one Chronos agenda job `hecate.mail_watch` (default every 15 min,
  editable/pausable in the agenda) → `POST /api/gateway/mail/watch/run`. Uses the Gmail **history API**
  (`users.history.list(startHistoryId)`, `messageAdded`, INBOX + any label): when nothing arrived it is one tiny call
  with an empty answer, no search, no LLM. Cursor `historyId` persisted in Hecate `data/`. History expired (Gmail keeps
  ~a week) → `[🔄]` fallback search `after:<last check>` and a fresh `historyId`.
  It is still a periodic check, so the SPEC justifies it (Marko's rule): Gmail can only push through Google Cloud
  Pub/Sub; without that setup a single cheap check is the only option, and it replaces N module polls.
- **B — Gmail push via Pub/Sub (optional, when configured):** `users.watch(topic)` + **streaming pull** from a
  Pub/Sub subscription. Streaming pull keeps one outgoing connection open, so it is real push **without a public URL**
  (the quick tunnel URL changes at every restart, a push endpoint would break). Needs, once, in Marko's Google Cloud
  project: Pub/Sub API on, a topic with publish right for `gmail-api-push@system.gserviceaccount.com`, a subscription,
  and a credential allowed to read it (§10 Q2). `users.watch` expires after 7 days → Chronos job `hecate.mail_watch_renew`
  (daily). When B is up, job A slows down to a safety net (default every 6 h) instead of disappearing (Pub/Sub may drop).
  Topic/subscription names = infrastructure → env (`HECATE_GMAIL_PUBSUB_SUBSCRIPTION`, `…_TOPIC`); the check
  intervals = Themis settings `hecate.mail.watch_interval` / `hecate.mail.safety_interval`.
- For every new message Hecate sends Iris only **headers** (`id`, `thread_id`, `from`, `to`, `subject`, `labels`,
  `date`, `snippet`): the body is fetched only for mails someone subscribed to.
- Gmail not authorized → same behaviour as today (`action_required=reauth_google`, Telegram button), job runs are
  recorded as skipped, no crash loop.

### 3.2 Iris subscriptions and dispatch
- Shared client **`hestia_common.mail_client`** (like `agenda_client`): `MailClient("scout").subscribe([mail_rule(key,
  path=..., senders=[...], subject_contains=[...], labels=[...], query=...)])`. Idempotent by `(owner, key)`,
  re-asserted at boot and hourly; modules rebuild rules when their own settings change (e.g. `scout.mail.senders`).
- Iris stores subscriptions in Archive (generic records store `iris_records`, same LWW protocol as the other modules)
  so they survive restarts; owner gone from Hub → kept (delivery is durable, see below).
- Matching is deterministic (sender address/domain, subject words, Gmail label; optional Gmail `query` evaluated by
  Hecate for complex rules). One mail can match several modules.
- **Delivery is durable**: Iris first ships the full mail to Archive under the subscriber's domain (raw record, deduped
  by Gmail id — the same table Scout already reads), then rings the module. Module down → the record waits
  "unevaluated" and is processed at the next ring or when the module starts (`on startup: process pending`). No mail lost,
  no retry loop.
- **Backfill**: a new or changed subscription asks Iris for the last `iris.backfill_days` (default 7) of matching
  mail (Hecate search, once). Also exposed as `POST /api/email/subscriptions/{owner}/{key}/backfill` (the module's
  "check now" button).
- Endpoints (Iris): `POST /api/email/subscriptions` (register), `GET /api/email/subscriptions`, `DELETE …/{owner}/{key}`,
  `POST /api/email/incoming` (from Hecate), `POST …/backfill`, `GET /api/email/dispatch/log` (last deliveries).
  Hub tools: `email_subscriptions` (read only). WebUI: Iris serves a small plugin page **Email** (subscriptions, last
  deliveries, unmatched count, watcher state, «controlla ora») so Marko never needs the logs.
- Logs: `event=mail_dispatched owner= key= count=`, `event=mail_unmatched count=`, `[🔄] event=mail_ring_failed owner=`.

### 3.3 Chronos: retiring rules
- `agenda_client.retire(keys)` → `POST /api/agenda/retire {owner, keys}`: Chronos cancels the module's own default
  rules that the module no longer declares (marked `retired_by_module`, shown greyed in *Regole per modulo*). Needed so
  `scout.email_cycle` disappears from every existing install. A rule the user created stays.

### 3.4 Scout on push
- Subscription `scout.listings` built from `scout.mail.senders` / `scout.mail.filter_queries` (unchanged settings),
  path `/api/scout/mail` → runs the existing cycle (lock, debounce, batching unchanged) on the pending records.
- Removed: agenda job `scout.email_cycle` (retired), setting `scout.cycle.interval`, template `extra_check`, the call
  chain Scout → `iris /api/email/ingest` → Hecate `/api/ingest/trigger` for mail. The plugin button «Controlla ora» =
  Iris backfill + cycle. Reconcile/enrichment keep their own cadence (`scout.reconcile.every_cycles` counts pushes).
- Hecate `iris_email` connector and `/api/ingest/trigger` mail path: removed if no other caller (only Scout today);
  calendar ingest untouched.

## 4. Hestia-Plutus (expenses)

### 4.1 Name, place, boundaries
- **Hestia-Plutus** (Greek god of wealth), container `hestia_plutus`, port **19020**, node Main PC, type `module`,
  tags `module,finance,context`, domain `finance`, tools `finance_*`, plugin decade **60**. Template: Hestia-Hygieia.

| Need | Owner | How |
|---|---|---|
| Tables | **Archive** | `finance_records` + `/api/finance-store` (same protocol as the other module stores); PDFs in `/api/blobs` |
| Domain logic, parsing, categories, budget, stats | **Plutus** | own API, no DB connection |
| PayPal mails | **Iris** (push) | subscription `plutus.paypal` |
| Understanding text no parser knows | **Oracle** | `/api/llm/generate`, caveman prompt, JSON out |
| Schedules (monthly review, reminder) | **Chronos** | agenda jobs |
| Alerts, reminders, confirmations | **Hermes** | `hestia_common.reminders`, `service.action_required` domain `system` |
| Tunables | **Themis** | `settings_client`, currency via `follow_personal()` |
| Pages / widgets / quick actions | **WebUI** plugin | `PluginClient` + `@hestia/webui-sdk` |

### 4.2 Data (records in `finance_records`, all with `created_at`/`updated_at`)
- **transaction**: date, amount (signed: expense < 0, income/refund > 0), currency, merchant, description, category,
  account (`paypal`, `hype`, `cash`, user accounts), source (`email`, `statement`, `manual`, `chat`), external_ref
  (PayPal transaction id / statement row hash → dedupe), linked_to (see 4.4), notes, tags, status (`confirmed`,
  `to_review`).
- **category**: seeded defaults, editable (Spesa, Casa e bollette, Trasporti, Ristoranti e bar, Abbonamenti, Salute,
  Cura personale, Svago, Shopping, Viaggi, Regali, Lavoro, Entrate, Trasferimenti, Altro), icon, colour, parent.
- **rule**: merchant pattern → category. Learned when the user recategorises («sempre così per questo esercente?»),
  editable; applied before asking Oracle.
- **budget**: category (or total) × monthly amount; month starts on `plutus.month_start_day`.
- **account**: name, kind, currency, optional opening balance.
- **import**: one per PDF/backfill: file blob id, period, rows found/new/duplicates/linked, status (`preview`,
  `committed`, `undone`). Undo removes the rows it created.
- **recurring**: detected subscriptions (same merchant, similar amount, regular interval), confirmed or dismissed by
  the user; next expected date.

### 4.3 Sources
- **PayPal (push):** subscription on PayPal sender addresses (setting `plutus.mail.senders`, defaults = PayPal's
  public receipt senders). Deterministic parser for the Italian/English receipt templates (amount, currency, merchant,
  PayPal transaction id, payment vs refund vs received); unknown template → Oracle extraction; unreadable → transaction
  `to_review` with the mail link. Category from rules, else Oracle with the category list.
- **Hype PDF (monthly):** uploaded from the plugin page *Importa* or **sent in chat** (WebUI/Telegram). Plutus reads
  the text (`pypdf`, deterministic Hype layout parser; other layouts → Oracle extraction per page), shows a **preview**
  (new / duplicate / linked to PayPal), the user confirms → commit (idempotent by row hash). Chat path needs a small
  generic Oracle change: attachments are stored in Archive blobs (`owner_module=chat`) and their ids are given to the
  tools of the chosen domain, so `finance_import_statement(blob_id)` can take the file. Useful later for Wardrobe
  photos too. (§10 Q3)
  *How (v1.2):* a module declares `attachment_handlers` in its Hub capabilities (`mime`, `match` words, `min_hits`,
  `path`). Oracle's document path extracts the text; on a match it stores the file as a blob (`owner_module=chat`) and
  calls `POST <module><path>` with the blob id. The module answers `{handled, text}` (Plutus: the preview counts +
  «Li registro?» + the import id); that text is the chat reply and stays in the history, so «sì» reaches
  `finance_import_statement(import_id, commit=true)`. No match / module declines / any error → the usual analysis.
- **Quick entry:** Home quick action «Spesa veloce» (amount + category chips, undo); chat «ho speso 12 € al bar» →
  `finance_add`.

### 4.4 No double counting
A PayPal payment funded by the Hype card appears twice (PayPal mail + Hype row «PayPal *MERCHANT»). Plutus links them
(same amount, ±3 days, PayPal-like description): the PayPal row keeps the detail, the bank row is marked `linked_to` and
excluded from totals. Same for internal transfers between own accounts (category Trasferimenti, excluded). The user can
unlink.

### 4.5 Assistant (MCP tools, `finance_*`)
`finance_summary` (month: spent, budget left, top categories), `finance_search` (period/category/merchant/text),
`finance_add`, `finance_update` (incl. recategorise + learn rule), `finance_delete`, `finance_budget` /
`finance_set_budget`, `finance_categories`, `finance_import_statement` (preview/commit), `finance_recurring`,
`finance_stats` (trend, by category, compare months). `GET /api/module/context?budget=` caveman lines (month spent vs
budget, categories over budget, upcoming recurring).

### 4.6 Reflection, alerts, reminders (common rules)
- **Budget alerts**: category at `plutus.alerts.threshold` % (default 80) and at 100 % → one Hermes notification each
  per month (`replaces` per category), `_link` to the Budget page. Switch `plutus.alerts.enabled` (acts on its own → allowed).
- **Monthly review**: agenda job `plutus.review` (1st of month, 09:00, editable) → `POST /api/finance/review/run` when
  `plutus.review.enabled` (off by default, like Wardrobe): last month vs budget, biggest changes, new recurring, rows
  to review; Oracle writes the text from Plutus' numbers, Hermes delivers.
- **Reminder** «carica l'estratto Hype»: `hestia_common.reminders` (`plutus.reminder.enabled` off + `max_per_week`),
  agenda job `plutus.statement_reminder` (day 3 of the month), only if no Hype import covers last month.
- Module-level evaluation stays inside Plutus (budget state, anomalies) and is exposed through `/api/module/context`;
  the cross-domain "signals" format belongs to brainstorm item 5 and is not invented here.

### 4.7 WebUI plugin (decade 60)
Pages: **Panoramica** (month: spent vs budget ring, by category, last movements, trend 6 months), **Movimenti** (list
with filters, inline recategorise, to-review queue, link/unlink), **Budget** (per category, month navigation),
**Abbonamenti** (recurring), **Importa** (PDF upload + preview/commit, import history with undo, PayPal mail status from
Iris), **Statistiche** (by category/merchant/month), **Categorie e regole**. Home widget «Spese del mese» and quick
action «Spesa veloce». Design system `Hestia-WebUI/frontend/DESIGN-SYSTEM.md`.

### 4.8 Settings (Themis, `plutus.*`)
`month_start_day` (1), `alerts.enabled` (true), `alerts.threshold` (80), `review.enabled` (false),
`reminder.enabled` / `reminder.max_per_week` (common helper), `mail.senders` (PayPal defaults), `link.window_days` (3),
`ai.profile` (local/cloud), log level. Currency = `themis.personal.currency` via `follow_personal()`. No feature switches.

### 4.9 Privacy
Financial data only in Archive (Marko's own DB). No real amounts, merchants, IBAN or mails in tracked files: test
fixtures are synthetic receipts/PDFs generated in tests. Oracle prompts get only the rows they need.

## 5. Docs and contracts to update
`Hestia-Hecate/hestia-hecate.md`, `Hestia-Iris/hestia-iris.md`, `Hestia-Scout/hestia-scout.md`,
`Hestia-Chronos/hestia-chronos.md`, new `Hestia-Plutus/hestia-plutus.md`, `Hestia-Swagger/swagger.yml`,
`docs/ARCHITECTURE.md` (push rule: modules subscribe to Iris, never poll mail), `docs/AI-GUIDE.md`, `readme.md`,
`architecture-and-flow-map.md`, `.env.example` + compose (Plutus service, Pub/Sub env), CI matrix, cloud bench compose,
root `CHANGELOG.md`.

## 6. Phases
- **P1 Mail push core**: Hecate watcher A (history API, cursor, fallback) + agenda job; Iris subscriptions store,
  `incoming`, durable dispatch, backfill; `hestia_common.mail_client`; Chronos `retire`; tests.
- **P2 Scout on push**: subscription, `/api/scout/mail`, retire job, drop interval/template/ingest path, plugin button;
  tests; Hecate `iris_email` removal if unused.
- **P3 Plutus core**: service skeleton, Archive store, transactions/categories/rules/budget/accounts, PayPal via Iris,
  quick entry, `finance_*` tools, module context, alerts, compose/CI/swagger/docs.
- **P4 Statements**: Hype PDF parser + preview/commit/undo, PayPal↔bank linking, recurring detection, Oracle chat
  attachments as blobs → tool.
- **P5 Plugin + reflection**: WebUI pages, widget, quick action; monthly review; statement reminder.
- **P6 Gmail Pub/Sub (B)**: streaming pull, watch renewal job, safety-net interval — only after Marko's Google Cloud
  setup (code can land earlier, inactive without env).
- **P7 Verify**: pytest of touched services, plugin build, `python tools/cloud_test.py all` with screenshots of the
  Plutus pages and a simulated PayPal mail travelling Hecate → Iris → Plutus and Scout.

## 7. Acceptance criteria
1. No module has an agenda job that polls mail; the agenda shows one `hecate.mail_watch` (and, with B, the renewal).
2. A new matching mail reaches Scout/Plutus within one watch interval (A) or seconds (B), exactly once.
3. Module down when a mail arrives → processed when it is back; nothing lost, nothing duplicated.
4. Existing installs: `scout.email_cycle` is retired automatically; `scout.cycle.interval` gone from Themis.
5. A PayPal receipt becomes a categorised transaction; the same payment in the Hype PDF is linked, not double counted.
6. Hype PDF: preview → commit → undo works; re-uploading the same PDF adds nothing.
7. Plugin pages, widget, quick action work in the WebUI on the cloud bench (screenshots); `finance_*` tools listed in MCP.
8. Budget alert and monthly review delivered through Hermes with `_link`; reminder only when the PDF is missing.
9. No personal data in tracked files; docs, swagger, compose, CI updated; CI green.

## 8. Risks
- Hype PDF layout unknown to us (no sample): parser built on public descriptions + Oracle fallback; first real PDF from
  Marko (never committed) tunes it. 
- PayPal template changes → Oracle fallback + `to_review`, never silent loss.
- Gmail history gaps → fallback search; Archive dedupe by Gmail id keeps it exactly-once.

## 9. Design decisions (proposed)
- Hecate watches, Iris decides who gets what, modules only react: each module does its own job.
- Delivery via Archive raw records + "doorbell" instead of mail bodies in the push: durable, reuses Scout's pipeline.
- Light check stays as safety net even with Pub/Sub.

## 10. Decisions (Marko, 2026-10-19)
1. Name **Hestia-Plutus** (port 19020, domain `finance`, tools `finance_*`).
2. Gmail Pub/Sub (B): written now, inactive until the Google Cloud setup («non importa se rimane bloccato»).
3. Hype PDF both in chat and from the plugin. General rule: every input works **automatic and manual, always, for
   everything**.
4. Small WebUI page «Email» for subscriptions and deliveries.
5. Watch interval: 2 min is too often; default **15 min** (tunable `hecate.mail.watch_interval`).
