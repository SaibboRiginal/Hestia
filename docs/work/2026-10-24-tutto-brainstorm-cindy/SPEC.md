# SPEC — Everything from the 2026-10-23 brainstorm and the Cindy ideas, in one shot

| | |
|---|---|
| **Version** | 1.2 |
| **Source** | user via project thread «Implementare tutto il brainstorm e Cindy» (Marko 2026-10-24 18:31: «iniziamo a implementare TUTTO … tutto one shot, poi una volta fatto tutto e collegato tutto e senza bug, fai il test e finalizza solo alla fine fine»); lists: `/mnt/project-files/brainstorm/2026-10-23-review-e-nuove-idee.md` §0 (A–D) + §5, adaptation table `/mnt/project-files/valutazioni/idee-dal-repo-cindy.md` «Adattamento a Hestia»; routed by the project coordinator |
| **Status** | For the record (Marko asked for no per-item approvals); implementation in waves, merged by Claude when CI is green |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).

## 0. How this is run

- One dossier, one plan, **waves** = one PR each, merged when CI is green (Marko's standing rule) so `main` always works.
- No per-item SPEC approval (Marko: «one shot»). Real doubts that only Marko can settle are asked once, the work goes on
  with the recommended option meanwhile.
- Final step: integration pass across everything, bug fixing, whole-stack run on the cloud bench (`tools/cloud_test.py
  all`), report.
- Rules applied everywhere (project memory + ARCHITECTURE + `docs/REGOLE-DI-MARKO.md` written in wave 1):
  R1 module boundaries (Oracle only brain, Hermes the only one who writes to Marko, Echo only voice, Archive only DB,
  Hecate external providers, Chronos time), R2 push not poll + every input automatic **and** manual, R3 no on/off switch
  that only hides a feature, tunables in Themis via `settings_client.setting`, never a new env var (env = secrets and
  infrastructure), R4 the assistant proposes, Marko confirms through Hermes, his edits win, R5 clients: stroke icons
  with tone, no emoji in WebUI, user texts never name modules, **every function on Telegram** (tools with
  `telegram_group` + `telegram` hints, `display` blocks), R6 caveman prompts for local models, no personal data in the
  public repo, docs follow code.

## 1. Inventory and owners

Legend: **new** = new module. Port numbers continue after Echo (19021).

### A. New modules
| # | Item | Owner | Notes |
|---|---|---|---|
| A1 | Images via remote ComfyUI | **new Hestia-Apollo** (19022) | the only module that talks to image generators; `APOLLO_COMFYUI_URL` / `APOLLO_COMFYUI_KEY` env (infra/secret); workflow catalog (ComfyUI API JSON + purpose + inputs) uploaded by Marko; job queue; results in Archive blobs; missing workflow → Hermes notice with where to upload |
| A2 | Client appearance (pets, graphic profiles, special-moment effects) | **new Hestia-Aphrodite** (19023) | inventory + per-client choice; decides the active profile by itself (holidays, seasons, special events from Chronos); Marko can only turn it off = back to his standard; asks images from Apollo; clients read only «what do I show now» |
| A3 | Smart home on Home Assistant | **new Hestia-Lares** (19024, «Casa» for the user) | lights, sensors, scenes, «sono a casa» to presence (Chronos); HA URL/token env; HA pushes state changes over its websocket (push, not poll); quick actions and Home scenes |
| A4 | Important people | **new Hestia-Hera** (19025, «Persone») | cards with dates, tastes, gift ideas from conversations, last contact; anniversaries go to the calendar as special events with lead time and gift proposals |
| A5 | Nutrition | **new Hestia-Demeter** (19026, «Alimentazione») | diet, meals, supplements; a coach (Hub tag `coach`) for the weekly plan |
| Cindy 21 | Real documents PDF/Word/Excel | **new Hestia-Calliope** (19027, «Documenti») | HTML draft → PDF/DOCX/XLSX with 3 shared themes, final check (file exists, pages, key content), result in Archive blobs; tool `documento_crea` |

### B. Calendar and life
| # | Item | Owner |
|---|---|---|
| B6 | Special events (birthday from personal settings, custom important events, lead time; Marko marks them **and** Hestia discovers them from mail/conversations/memory and proposes) | Chronos (generic «special» mark + lead time on calendar items) · Hera (people dates) · Oracle/Athena discovery → proposals via Hermes · Aphrodite effects |
| B7 | Deadlines of everything with advice (bills, insurance, car tax, inspection, servicing, documents) | Chronos calendar items of kind deadline? → **no**: domain = **new Hestia-Kairos** (19028, «Scadenze») with mail subscription (Iris), advice via Oracle use case, entries mirrored to the calendar with lead time |
| B8 | Smart calendar assistant: proposes to move Marko's events around his commitments | Chronos (planner already moves agenda jobs, §3.8 of the recap dossier) → extended to Marko's own events **as proposals** via Hermes, never moved without his yes |
| B9 | Spoken evening diary after the recap | Hygieia owns the diary (always on) → «diario a voce» entry: Echo transcribes, Hygieia stores, memory note, reflection reads it; prompt after the recap via Hermes action |
| B10 | Garmin, only if fully automatic | Hecate provider (`garminconnect`, credentials in env or via the secret handoff Cindy 4), daily sync job in the agenda, data to Hercules (load/recovery), Hygieia (sleep), Chronos presence (sleeping/awake) |

### C. WebUI and clients
| # | Item | Owner |
|---|---|---|
| C11 | «Adesso» row: 3 from habits/recents + 3 invented by the LLM, each with a reason; changes on events/time windows; learns from taps; also Telegram and Ctrl+K; the assistant may propose new actions | usage log + suggestion engine in **Metis** (learning organ: «are we improving»), LLM use case `metis.adesso`; WebUI Home row, Telegram «Adesso» keyboard, palette |
| C12 | Live voice mode from sidebar/Home/shortcut over any page, pet as its face; dictation in the normal chat | WebUI (overlay service on top of the existing `live-voice.service.ts`), Echo streams |
| C13 | New sidebar: real SVG logo, visible Search, **Generale on top above Fissati**, pinned chats or 3 recent, second sidebar with full history (search + date filter), Sistema as one entry with its page, compact icon mode | WebUI |
| C14 | «Scopri» page: features never/rarely used, what they do, link to try | WebUI page + Metis usage stats vs Hub catalog |
| C15 | Web Push from the WebUI (PWA) | Hermes (VAPID keys env, subscriptions in Archive, delivery like any client) + WebUI service worker |

### D. System
| # | Item | Owner |
|---|---|---|
| D16 | Stack performance: RAM, CPU, start time, response time per module, history, alerts, page in Sistema | Argus (Docker socket read-only stats + Hub latency), Themis thresholds |
| D17 | llama-server instead of Ollama with slots and saved KV | Oracle provider type `llamacpp` (OpenAI-compatible + `id_slot`/`cache_prompt`, slot save/restore), compose service, Ollama stays selectable |

### E. Cindy ideas (numbers of `valutazioni/idee-dal-repo-cindy.md`; 14 dropped, 22 and 24 done by the Telegram thread)
| # | Item | Owner |
|---|---|---|
| 1 | Loop guard in the agent loop | Oracle |
| 2 | No double actions when the chain changes model | Oracle chains |
| 3 | Independent reviewer before the diff | Hephaestus Forge |
| 4 | «Te lo chiedo io»: secrets outside the brain | Hermes request + requesting module; WebUI form + Telegram Mini App |
| 5 | «Da decidere»: everything waiting for Marko in the Hermes inbox + one reminder | Hermes |
| 6 | Message origin written by the system + turn authority | callers (`hestia_common.origin`), Hestia-MCP (external) + Oracle |
| 7 | Routines in words, by time or event | Chronos (agenda rule + instruction) + Oracle + Iris/module signals |
| 8 | Nightly learning: mandatory quote, skip without LLM, log with undo | Athena + Oracle memory |
| 9 | Components in WebUI chat answers (`hxk-*`) | Oracle (prompt for capable steps, WebUI only) + WebUI renderer + Telegram text fallback |
| 10 | Voice: recognises Marko's voice, end of turn on real silence | Echo |
| 11 | Marko's rules in the repo + new-feature checklist in the SPEC template | docs |
| 12 | Site recipes without a model at every step | Atlas (+ Scout) |
| 13 | «Cosa ho cambiato» under the answer with Undo per item | Oracle (list) + modules (inverse action in the tool) + clients |
| 15 | Forge tasks wait for the Claude limit reset | Hephaestus + Chronos one-off job |
| 16 | Images described to text-only models | Oracle `visione` |
| 17 | Personal dictionary for transcription | Echo |
| 18 | «Rivedi cosa sai di me»: memory clean-up proposals | Oracle tool + Athena |
| 19 | Logs redacted before a cloud model | `hestia_common.redact`, used by Argus and Forge |
| 20 | Notifications that do not chase between clients | Hermes + presence (Chronos) + client activity |
| 23 | Goal for a multi-turn conversation | Oracle |
| 25 | Database and blob growth alerts | Argus |
| 26 | Coloured tags for conversations | Archive (chat sessions) + Oracle tool + WebUI history + Telegram filter |
| 27 | Deterministic pre-check before a routine + routine templates gallery | Chronos + module tools |
| 28 | Topic radar (news with sources and «why it matters») | routine template: Atlas fetch + Oracle + recap/Hermes |
| 29 | Repo docs aligned with code: periodic check → proposals to Forge | Athena Sistema |
| 30 | Progressive tool discovery: «when to use me» line + module manual on demand | Hub registration + Oracle |
| 31 | Forge team: plan split in pieces, worktrees, engines, then review | Hephaestus |
| 32 | Android phone as automatic sensor (push from Tasker-like apps) | Hecate (webhook, token) → Chronos presence, Iris-like dispatch of app notifications |

### F. Telegram parity leftovers (`docs/work/2026-10-23-telegram-da-zero/PROGRESS.md`)
Tools for: export/import `.hestia` (Archive transfer), backup now / restore (Archive), presence change (Chronos),
Athena proposals and thoughts, Argus remediation history.

## 2. Design decisions (shared pieces first)

1. **Usage log (C11, C14)**: Metis owns it (`metis-store` in Archive, kind `tap`, `{client, kind: action|page|tool,
   ref, at}`); clients push taps (`POST /api/metis/usage`), Hub-routed. Suggestions = deterministic frequency per
   weekday/hour bucket + due agenda windows + recents; the LLM fills the invented half a few times a day on events
   (agenda job + signals), never at each open. Telegram and WebUI read the same `GET /api/metis/adesso`.
2. **Origin and turn authority (Cindy 6)**: the caller's code sets `X-Hestia-Origin` (`hestia_common.origin`);
   Hestia-MCP stamps `esterno:<access>` for external AIs; no header from a non-user client = `autonomo` (fail
   closed); a body field or the model never sets it (v1.1: not stamped by the Hub, which forwards headers and does
   not know who is a user). Oracle maps origin → level:
   `utente` (today's confirmation gate), `routine` (inside the routine instruction), `autonomo` (read, propose,
   notify only; writes return «serve che lo chieda Marko»).
3. **Change set (Cindy 13)**: a tool result may carry `undo: {tool, args}` or `undo: "<tool>"` (helper
   `hestia_common.mcp_helpers.undo`); Oracle collects the write results of the turn into a `changes` frame after `final`; clients show the
   line and call the undo through the normal tool path.
4. **Special events (B6)**: Chronos calendar items get `special: {kind: birthday|anniversary|custom, lead_days,
   person_id?}`; birthday comes from `themis.personal.birth_date`; Chronos fires a `special_moment` signal on the day
   (Iris-like push to subscribers: Aphrodite effects, Hera gifts) and the lead-time notice through Hermes.
5. **Secrets (Cindy 4)**: Hermes notification kind `secret` carries only field names; the value goes WebUI/Mini App →
   Hub → requesting module `POST <path>` directly, never Oracle or Archive; Telegram chat only shows the Mini App button.
6. **New modules** follow the Plutus pattern: generic `build_router` store in Archive (`<module>-store`), Themis
   settings, agenda rules, plugin UI bundle (`ui/` + webui-sdk), MCP tools with Telegram hints and `display`, transfer
   sections, recap piece where useful, Hub registration with `when_to_use` (Cindy 30), compose service, swagger, doc.
7. **No new timers**: every periodic thing is an agenda job; push sources: Iris (mail), HA websocket (Lares), Hecate
   webhooks (phone), Chronos signals.

## 3. Waves (one PR each)

1. **W1 Rules + Oracle core**: Cindy 11, 1, 2, 6 (Hub+Oracle), 16, 19 (`hestia_common.redact`), 23, 30, 13 (Oracle
   side), 9 (Oracle side), D17 llama-server provider.
2. **W2 Hermes · Chronos · Iris**: Cindy 5, 20, 4, 7+27+28, B6 special events, B8 smart calendar, C15 Web Push
   backend, F presence tool.
3. **W3 Athena · Argus · Hephaestus · Atlas · Archive**: Cindy 8, 18, 29, D16 + 25, 19 usage, 3, 31, 15, 12, F tools
   (Athena proposals, Argus history, export/import, backup).
4. **W4 Echo · Hecate · Hygieia**: Cindy 10, 17, B9 spoken diary, B10 Garmin, Cindy 32 phone sensor.
5. **W5 New modules**: Apollo, Aphrodite, Lares, Hera, Kairos, Demeter, Calliope.
6. **W6 Metis usage + «Adesso» + «Scopri» backend**, Telegram «Adesso».
7. **W7 WebUI**: sidebar, Adesso row, Scopri, Live overlay + dictation, pet overlay + editor, graphic profiles,
   effects, chat components, change-set row, origin label, chat tags + history sidebar, Web Push worker, Sistema page,
   performance page, «Da decidere» counter, secret form.
8. **W8 Integration**: cross-checks, cloud bench run, bug fixing, docs sweep, report.

## 4. Acceptance

- Every item above implemented, reachable from WebUI **and** Telegram, documented (module doc, swagger, ARCHITECTURE,
  AI-GUIDE, readme module list, flow map), with unit tests per module; CI green on every wave.
- Whole stack starts on the cloud bench; every new module registers on the Hub and shows its pages; smoke flows recorded
  in this folder.
- Things that need Marko's hardware/accounts (ComfyUI, Home Assistant, Garmin, phone, real Telegram, .NET build) are
  listed with the exact setup steps in `TESTING.md` and the module docs.
