# Hestia-Plutus 💶

**Role:** Expenses (Spese) — every movement in one place: PayPal by email (push), bank statements (Hype PDF) from
the plugin or the chat, quick entry, categories that learn, budgets, recurring payments, statistics
**Node:** main host (with the other domain modules)
**Stack:** Python · FastAPI · Docker · WebUI plugin bundle (Lit, `ui/`) · `pypdf` (text only, no OCR)
**Port:** 19020 · Domain `finance` · Tools `finance_*` · Dossier: `docs/work/2026-10-19-email-push-spese/`

---

## Responsibility

- Owns the money domain: transactions, categories (seeded, editable), merchant rules (seeded + learned), accounts
  (PayPal, Hype, Contanti seeded; others created when used), budgets, recurring payments, statement imports.
- **Money is signed**: expense < 0, income/refund > 0. A typed positive amount from manual, quick or chat entry is a
  spending. Totals never count a row with `linked_to` nor a `transfer` category.
- **No double counting**: a PayPal payment paid with the card shows up twice (PayPal mail + bank row «PAYPAL *X»).
  `link_pass` links the bank row to the PayPal row (same amount, bank text mentions PayPal, within
  `plutus.link.window_days`): both kept, counted once. Manual links/unlinks win (`link_manual`).
- **Categories**: an explicit category wins, then the rules (longest pattern first), then Oracle for statement rows
  no rule knows, else `altro`/`entrate` with status `to_review` (email/statement only). Correcting with «usa sempre»
  (`learn`) saves a user rule.
- **Recurring**: same merchant, ±15 % amount, weekly/monthly/yearly interval, 3+ times (2 for yearly) → suggestion;
  the user confirms or dismisses (dismissed ones are not proposed again).
- Does not read mail itself (Iris pushes it), does not call models directly (Oracle `/api/llm/chat` with use case
  `plutus.lettura`, chain chosen in Oracle → Cervello → Modelli, only as a fallback), has no database (Archive `finance-store` + blobs).

## Inputs (every input works automatic and manual)

| Input | Automatic | Manual |
|---|---|---|
| PayPal mails | Iris subscription `plutus:paypal` (senders = `plutus.mail.senders`) stores the mail in Archive under `finance` and rings `POST /api/finance/mail`; Plutus reads `archive/finance/unevaluated`, parses (deterministic, Oracle fallback), marks evaluated | «Ricontrolla email PayPal» (`POST /api/finance/mail/check`, Iris backfill N days) |
| Bank statement PDF | Sent in chat: Oracle hands the blob to `POST /api/finance/attachments` (declared in `attachment_handlers`), reply = preview + «Li registro?» + import id; «sì» → `finance_import_statement(import_id, commit=true)` | Page *Importa*: upload → preview → confirm; undo |
| Bank app notifications | Phone → Hecate → feed `phone.notification` (`hestia_common.feeds`, `capabilities.feeds`) → `POST /api/finance/phone`; `app/core/phone.py` (deterministic: amount + «pagamento/addebito…» or «ricevuto/accredito…», merchant after «presso/da/a») → transaction `source: phone`, always `to_review`, `external_ref` `phone:` hash (no duplicates); anything else ignored (dossier `2026-10-24-tutto-brainstorm-cindy` W4, Cindy 32) | — (choose the apps in Hecate's setting «App da ascoltare») |
| Single expense | — | Quick action «Spesa veloce» (amount + category chip, undo), form in the plugin, chat «ho speso 12 € al bar» (`finance_add`) |

Statement parser: a line with a date at the start and an amount at the end is a row, lines in between continue the
description, saldo/totale lines are skipped, sign from `-`/`+` or income words. Every row has a stable
`external_ref` (`stmt:` hash of account, date, amount, text, occurrence) so re-uploading adds nothing. No row
recognised → Oracle extraction. PDFs are kept as Archive blobs (owner `plutus`, or `chat` when sent in chat).

## Storage

Archive `/api/finance-store/records`: table `finance_records (kind, id)` with `data` JSONB, `parent_id`, `ref_id`,
`at`, `updated_at`, `deleted` tombstone, `seq` cursor — same protocol as the other module stores.
Archive data epoch: store answers carry `epoch`; when it changes (a backup rollback swapped the database) the mirror is dropped and reloaded from zero (`[🔄] event=plutus_mirror_reset reason=data_epoch`), so no stale row is written back.
Kinds: tx, category, rule, budget, account, import, recurring, mail (processed mail refs, idempotency), alert (sent
budget alerts, one per category per level per month), reminder.

## Assistant (MCP, domain `finance`)

finance_summary, finance_search (with total), finance_add, finance_update (`always` = learn rule), finance_delete,
finance_budget, finance_set_budget, finance_categories, finance_import_statement (preview by blob id, then commit by
import id), finance_recurring, finance_stats. Each has a REST twin `/api/finance/tools/<name>`. Context line for the
assistant: `GET /api/module/context` (month spent/budget, pace, high budgets, top categories, to review, coming).
`&topic=<signal key>` → the detail behind a reflection signal (`budget_pace:<cat>|month`: spent vs budget, pace,
biggest movements; `unusual_week`: week vs 8-week median, top categories and merchants; `new_subscription:<id>`;
`to_review`); unknown topic → the normal line.
Daily recap piece «Spese»: `GET /api/module/recap?day=&next=` (spent by category, income, to review, confirmed
recurring payments due next; budget as note). Capability `recap_endpoint`.

## Reflection signals (`hestia_common.signals_client`, dossier `docs/work/2026-10-20-riflessione-a-livelli`)

Deterministic, no LLM; texts say «Spese», never the module name. Stored in Archive `signals-store` through
`Signals("plutus", "finance").sync()` (only changes written, signals gone are retracted).

| Key | Severity | When | Page |
|---|---|---|---|
| `budget_pace:<category>` / `budget_pace:month` | alta / attenzione | budget reached / month pace (spent ÷ days gone × days, from day 5) above budget | budget |
| `unusual_week` | attenzione | this ISO week's spending > 1.5 × median of the previous 8 weeks | statistiche |
| `new_subscription:<rec id>` | info | recurring payment first detected in the last 7 days (`found_at` on the recurring row) | abbonamenti |
| `to_review` | info | ≥ 5 movements to review | movimenti |

Weekly metrics (12 ISO weeks, current included, expenses only): `finance.spent` «Spesa settimanale» and
`finance.spent.<category>` for the top 4 categories of the period (label = category label). Re-evaluated after every
write (transactions, quick expense, budget, import commit/undo, PayPal mails, MCP writes; `signals.changed()`,
debounced), once after warm-up and by the agenda job `plutus.signals` (daily 17:30, editable) →
`POST /api/finance/signals/run`.

## Notifications (agenda → Hermes)

| Job | When | What |
|---|---|---|
| `plutus.daily` | every day 21:00 | budget alerts at `plutus.alerts.threshold` and at 100 % (switch `plutus.alerts.enabled`), recurring detection |
| `plutus.review` | 1st of the month 09:00 | last month vs budget and the month before, text by Oracle (fallback: plain numbers), only if `plutus.review.enabled` |
| `plutus.signals` | every day 17:30 | reflection signals + weekly metrics → Archive `signals-store` (no notification) |
| `plutus.statement_reminder` | days 3, 6, 9 at 10:00 | last month's statement missing → one reminder (max per week), «Non questo mese» skips it, only if `plutus.reminder.enabled` |

## Client UI (plugin contract)

Icons, never emoji (DESIGN-SYSTEM rule, `docs/work/2026-10-20-icone-nei-client`): `<hxk-icon name tone>`. Empty states without emoji.

Bundle `ui/src/index.ts` → `/ui/webui/plutus.js` (built in the Dockerfile). Pages: panoramica (month: spent, income,
left, pace, budget bar, categories, donut, latest, coming payments, top merchants, ricontrolla PayPal, chiedi),
movimenti (by month or «da rivedere», category, account, search; new), movimenti/:id (category chips, «usa sempre»,
links, edit, delete), budget, abbonamenti, importa (PDF upload + preview + undo, PayPal state), statistiche (months,
categories, merchants, JSON export), categorie (rename, archive, add; rules). Widgets: mese, ultimi. Quick action:
spesa (category chips from `/quick/categories`, params amount + note, undo). A UI change needs
`up-all.bat --build plutus`.

## Settings (Themis, `plutus.*`)

month_start_day (1; e.g. 27 to count salary to salary), alerts.enabled (true), alerts.threshold (80 %),
review.enabled (false), reminder.enabled / reminder.max_per_week and notifiche.voce (false: amounts read badly
aloud) (from `hestia_common.reminders`), mail.senders
(paypal.it, paypal.com), link.window_days (3, advanced). Currency is the personal setting
`themis.personal.currency` (`follow_personal()`).

## API (via Hub `/route/plutus/...`)

See `Hestia-Swagger/swagger.yml` tag *Plutus*. Groups under `/api/finance`: meta, categories, rules, accounts,
budgets, transactions, summary, stats, recurring, export, imports (+commit, undo), attachments, mail (+check), phone,
quick, alerts/run, review/run, reminders/run|skip, signals/run, tools.

## Export and import (`/api/transfer/*`, dossier `docs/work/2026-10-20-import-export`)

Sections over `finance-store`: `movimenti` (tx) · `categorie` · `regole` · `budget` · `conti` (account) · `ricorrenti`.
A transaction pulls its category and account. Statement imports, processed mails, alerts and reminder state are
runtime: never exported. Settings travel through Themis.

## Configuration (infrastructure only)

`SERVICE_NAME`, `SERVICE_BASE_URL`, `HUB_API_URL`, `TZ` (local day for months and jobs), `PLUTUS_UI_DIST`.

## Tests

`python -m pytest -q -m "unit or api or format" Hestia-Plutus/tests` (fake Archive in memory, synthetic receipts and a
generated PDF, no network).


## Coach of the weekly plan (dossier `docs/work/2026-10-20-coach-di-ogni-tipo` §7.3)

Hub tag `coach`; `app/core/coach.py` mounted with `hestia_common.coach.CoachRouter` (needs + review).
- **Targets**: one per budget (category or total) — what is left this budget month spread over the weeks still to go
  (`value`, `unit` = currency, `progress` = spent/budget).
- **Block** «Rivedi spese» (15', evening, `finance.review`) while movements to review ≥
  `plutus.coach.review_threshold` (10, group «Piano della settimana»). After a correction, an import commit or new
  mail payments Plutus tells the plan: changed when the review becomes due, done when it no longer is.
- **Review**: budgets kept vs over in the budget month.

## Telegram card (`display`)
Tools `finance_summary`, `finance_search`, `finance_add` return a `display` card: spent vs budget and pace, categories with orange/red over 80/100 %, «Da rivedere (n)»; movements as merchant · amount · category · date; a saved movement with Cambia categoria / Elimina (red) / Riepilogo. Built with `hestia_common.display`; Hestia-MCP keeps it only for Telegram (docs/work/2026-10-23-telegram-da-zero §6).

## Undo of a chat write
`finance_add` returns `undo = {tool: finance_delete, args: {id}}` (`hestia_common.mcp_helpers.undo`): the chat shows
«Ho fatto: Registra spesa» with «Annulla».

## Module guide for the assistant (dossier `docs/work/2026-10-24-tutto-brainstorm-cindy`, Cindy 30)
The Hub registration declares `capabilities.when_to_use` (one line in the assistant's «MODULI» index) and
`capabilities.manual` (short manual the assistant loads with `module_manual` only when it needs it).
