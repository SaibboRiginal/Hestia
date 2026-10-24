# Marko's product rules (decisions, dated)

Hestia's owner decided these rules in conversations outside the repo. They are written here so that every
developer — human, Claude Code in Forge, any model — sees them (Cindy idea 11, dossier
`docs/work/2026-10-24-tutto-brainstorm-cindy`). Technical contracts stay in `docs/ARCHITECTURE.md`; this file is
the **why** and the product invariants. When a rule changes, add the new decision with its date, do not rewrite
history. No personal data here: the repository is public.

Each rule: the decision · what it means in code · allowed exceptions · how to check.

## R1 — Every module does only its own job (2026-10-10, restated 2026-10-24)
- Oracle is only the brain: it reasons and calls tools inside what is asked. It never stores domain data, never
  writes files for the user, never talks to speech or image engines.
- Hermes is the only one who writes to the owner (notifications, confirmations, questions, reminders).
- Echo is the only voice (speech ↔ text). Apollo is the only image generator door. Archive is the only database.
  Hecate owns external providers (Google, Microsoft, weather, Garmin, phone webhooks). Chronos owns time (agenda,
  calendars, presence).
- Never give a module a job another module was designed for. A new capability = a new module, or the module whose
  job it already is.
- Check: `docs/ARCHITECTURE.md` «Hub is the only door»; reviews reject a service calling another's URL or a
  provider SDK outside its owner.

## R2 — Push, not poll; automatic and manual (2026-10-19)
- Modules are told when something changes (Iris mail doorbell, Chronos signals, Home Assistant websocket, phone
  webhooks). A poll must be justified in the module doc (example: news for the topic radar, nothing pushes them).
- Every input works both ways: Hestia finds it by itself **and** the owner can add or correct it by hand.
- Periodic work = an agenda job or window in Chronos, never a timer or loop in the module.

## R3 — No switch that only hides a feature (2026-10-18)
- A setting is a value to tune (threshold, time, list), declared with `hestia_common.settings_client.setting` in
  Themis. No `enabled: false` that just hides a feature; if a feature exists it works.
- Allowed: per-client display choices (show the pet on this client), pause of an agenda item (owner's decision).
- No new environment variable for a tunable: env = secrets and infrastructure only. No legacy compatibility when a
  value moves to Themis.

## R4 — The assistant proposes, the owner confirms (2026-10-10)
- Changes the assistant decides by itself (settings, agenda, memory clean-up, calendar moves, Forge tasks, new
  quick actions) are proposals delivered by Hermes; the owner confirms.
- The owner's edits always win; a paused or cancelled item stays so (no fallback that re-creates it).
- Turn authority (2026-10-24): a turn written by the owner can act (with the usual confirmation gate); a routine the
  owner wrote acts only inside its instruction; an autonomous turn only reads, proposes and notifies.

## R5 — Clients (2026-10-20, 2026-10-24)
- WebUI and plugins: stroke icons with a tone colour, never emoji. Telegram may keep emoji where there is no
  alternative.
- User-facing texts never name modules or internal parts («Non disponibile», not «Oracle è giù»); no cute names.
- Every function is reachable from Telegram too: a module tool with `telegram_group` + `telegram` hints and a
  `display` block. Menus are configuration (`telegram.menu.layout`), not code.

## R6 — Cost and privacy (2026-10-04, 2026-10-24)
- Prompts for local models are «caveman»: short and dense, every token is paid each turn.
- No personal data in tracked files (chat ids, emails, passwords, names of real people). Configuration values go in
  `.env`; notify targets use `owner`.
- Text sent to a model from logs or reports passes `hestia_common.redact` first.
- Docs follow code: every behaviour change updates the module doc, swagger, ARCHITECTURE and the dossier in the
  same change.

## R7 — Working style (2026-10-22, 2026-10-24)
- Threads merge their own PR once CI is green, unless they need an answer from the owner; main must always be ready
  for a `git pull` and a test.
- Large requests can be done «one shot»: one dossier with the plan for the record, no per-item approvals, test and
  finalize at the end.

## New feature checklist (put it in every SPEC)
1. What real job does it do for the owner?
2. Which module owns it (R1)? Does it need a new module?
3. Does it add configuration? Only tunables in Themis, no switches (R3), no env for tunables.
4. Push or poll (R2)? Automatic **and** manual?
5. Who confirms (R4)? What happens when the assistant does it alone?
6. Does it work on every client: WebUI (icons, no emoji) and Telegram (tool + display) (R5)?
7. Can the owner stop it, correct it and undo it?
8. Which docs change (module doc, swagger, ARCHITECTURE, AI-GUIDE, flow map, readme)?
