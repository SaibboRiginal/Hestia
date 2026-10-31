# Hestia-Hephaestus

Role: Guarded self-healing and coding executor.

P2-2 implementation is intentionally constrained to read-only diagnostics. Hephaestus produces runbook-based plans with explicit consent and dry-run guardrails.

Target role evolution: autonomous remediation executor triggered by Argus/Oracle policy contracts.

## Principles
- Runbook-first
- Explicit consent tiers
- Dry-run default
- Rollback checkpoints required
- No mutating execution in MVP
- Full audit trail for every mutation
- User-visible notifications before and after automated mutation
- Source-control-first remediation (branch/commit/rollback)

## Endpoints
- GET /health
- GET /api/hephaestus/status
- GET /api/hephaestus/runbooks
- POST /api/hephaestus/diagnose
- POST /api/hephaestus/execute-preview
- POST /api/hephaestus/remediate
- POST /api/hephaestus/remediate/{task_id}/approve
- POST /api/hephaestus/remediate/{task_id}/retry (agenda retry of a failed repair)
- POST /api/hephaestus/remediate/{task_id}/rollback — real undo («Annulla riparazione»): a repair still waiting for
  approval or failed is stopped (`rolled_back`, `rollback_result.status=cancelled`, no agenda retry); a succeeded one
  with `undoable=true` (the module's reconcile answered `details.undo_available`) calls the same module's
  `…/maintenance/undo` through the Hub (`restored`; on error `failed` and still undoable); anything else stays as it is
  with `nothing_to_undo` (dry run, a pure re-sync). Today only Archive's reconcile is restorable (it deletes rows).
- POST /api/hephaestus/restart `{service, reason?, attempt?}` — immune system (Argus, oracle-offline v3 B): restarts the
  module's container through the Docker socket, then checks its health → `{status, service, restarted, healthy,
  detail}`; refuses `hephaestus` and bad names, `skipped` while Forge is deploying that module
- GET /api/hephaestus/tasks
- GET /api/hephaestus/tasks/{task_id}
- GET /api/ui/manifest · GET /ui/webui/{file} (WebUI plugin, see below)

Execution endpoints above are implemented as policy-gated remediation flows (task creation, approval, real undo through the target module) with real Hub-routed maintenance execution against target services.

### WebUI plugin (Sistema)

Icons, never emoji (DESIGN-SYSTEM rule, `docs/work/2026-10-20-icone-nei-client`): `<hxk-icon name tone>`. Forge panel: tests passed check (success), failed x (danger), skipped minus; changed docs edit.

Hephaestus ships its own inside view on the client plugin contract (`hestia_common.plugin_client`, SPEC
`docs/work/2026-10-18-moduli-core-e-mcp-esterno` §A2/A3): `app/core/webui_plugin.py` declares it, kind `core`
(WebUI sidebar section *Sistema*), `api_prefix` `/api/hephaestus/` (remediation and Forge share it).
- page **Sviluppo** (`sviluppo`, `hephaestus-sviluppo`, order 170, first; §A4 — ported from the WebUI built-in
  `/forge` page, which calls nothing of its own any more): Forge task list (search, filters Tutti / Aperti / *Dai
  moduli* / Applicati / Non riusciti, open count, paused banner), the engine conversation (transcript polled every 4 s
  while working — no streaming), follow-up composer (new task with `parent_task`), side panel Panoramica (incl. notes
  + *Aggiungi nota*) · File · Diff (unified/split) · Dossier · Test · Log · Ramo, actions Avvia / Avvia ora with the
  engine picker, Approva e applica, Rifiuta, Rollback, Riprova, Pausa/Riprendi, Nuovo sviluppo (engine, services,
  continue a dossier), *Chiedi a Hestia*, engines + Claude budget when nothing is selected, read-only **Repository**
  browser (commit graph, commit, files at any ref, branches, compare, tags, dossiers). **Copia per AI** (§B5): pick
  tasks (or the current one) → `GET /forge/tasks/export` markdown → clipboard (fallback/also `.md` download); the
  markdown comes from the forge_task / forge_tasks views and is never written to the repo. Badge: `GET /forge/counts`
  field `review` (awaiting_review + proposed). Links: `/p/hephaestus/sviluppo?task=<id>` (short ids ok),
  `?view=repo`. What the old WebUI controller added is sent by the plugin: actions `by=user`, new tasks
  `source=ui, requested_by=user` (the Forge defaults are the same).
  Panoramica shows the **Revisione automatica** card (Cindy 3, W7): verdict, issues by priority with file and
  evidence, and the round of fixes (`task.review`); states `reviewing` (revisione automatica) and `waiting_limit`
  (attende il limite di Claude) are labelled and count as open (`/forge/counts`).
- page **Riparazioni** (`riparazioni`, `hephaestus-repairs`, order 171): remediation tasks from
  `/api/hephaestus/tasks` + `/runbooks` + `/status` — counts per state, filter, per task runbook (title, steps,
  read-only/rollback checkpoints), consent tier, dry-run, environment, attempts, notes timeline, execution result,
  `rollback_ref`, branch, Forge task after escalation (link to it in Sviluppo). Read only: approve/undo keep their consent path (chat/Telegram
  tools `hephaestus_approve` / `hephaestus_rollback`); the page only says how to ask.
- widget **Forge** (`forge`, `hephaestus-forge-widget`, sizes s/m/l, auto): active/paused/off, running, queue,
  awaiting review, proposed, Claude budget phase (`/forge/status`, `/forge/claude-budget`, `/forge/tasks`). Its only
  button is the existing manual brake `POST /forge/pause` (after a confirm, same switch as Sviluppo/Telegram);
  it opens the Sviluppo page.
- No quick actions.
- Unreachable module → the page/widget shows the "non raggiungibile" state.
Bundle: `Hestia-Hephaestus/ui/src` (Lit, `@hestia/webui-sdk`), built by the Node stage of the Dockerfile into
`/ui/dist/webui/hephaestus.js` (outside `/code`: the dev mount of `app/` would hide it); infra env
`HEPHAESTUS_UI_DIST` (default `/ui/dist`). Local check: `cd Hestia-Shared/webui-sdk && node build.mjs plugin
../../Hestia-Hephaestus/ui/src/index.ts /tmp/x/webui/hephaestus.js` and `tsc -p ../../Hestia-Hephaestus/ui/tsconfig.json`.

### Repairs in the assistant agenda

- Repair waiting for approval → event `hephaestus.repair.<id>` ("🛠️ Riparazione da approvare").
- Failed (non dry-run) repair → agenda task retry after setting `hephaestus.remediate.retry_minutes` × attempt
  (default 15), up to `hephaestus.remediate.max_attempts` (3); fired via Hub → `/remediate/{id}/retry`.
- Last failure → **escalated to Forge** as a code-fix task (state `escalated`, `forge_task_id`); Forge applies
  your permission mode. Success/rollback completes the agenda entry.

## Safety contract (Current)
- Production mutation requires explicit approval.
- Non-production mutation can be policy-gated via setting `hephaestus.remediate.require_approval` (default on).
- Auto-approval can be blocked/enabled via setting `hephaestus.remediate.auto_approve_non_prod` (default off).
  Both are safety switches: the assistant may read them, never propose them (`oracle: read`).
- execute-preview remains a diagnostic gating endpoint.

## Autonomous Remediation Contract (Target)

1. Triggering:
- Allowed from Argus/Oracle/user command via Hub-routed contract.

2. Source control requirements:
- Branch-per-remediation (`auto/hephaestus/<task-id>` pattern).
- Atomic commits with machine-readable execution metadata.
- Rollback pointer required (baseline commit/tag) before mutation.

3. Notification requirements:
- Notify start of mutation with reason and scope.
- Notify completion with changed files, branch/commit refs, and deployment result.
- Notify rollback when executed or recommended.

4. Deployment requirements:
- Local deploy allowed under policy.
- Remote/cluster deploy requires environment-level policy gates and health verification.

5. Copilot account/runtime note:
- Hephaestus must not depend on opening an interactive personal IDE Copilot session.
- Automation is performed through service/workflow APIs, repository operations, and deterministic runbooks.

## Forge — self-development (Hestia develops itself)

You ask Hestia on Telegram "aggiungi X / correggi Y". Oracle calls `forge_develop`;
Forge codes it on an isolated branch, tests it, and asks you to approve.

```
user/Argus ──► POST /forge/tasks ──► proposed ─approve─► queued ─► running (engine in git worktree)
                                                                     │ Forge commits + runs tests itself
                                                                     ▼
                                    rejected ◄─reject── awaiting_review ──approve──► merged ──► deployed
                                                                                      └─rollback─► rolled_back
```

- **Isolation:** each task = `git worktree` + branch `auto/forge/<id>` from the base branch. Live checkout untouched until merge.
- **Verification:** Forge runs `HEPHAESTUS_FORGE_TEST_CMD` on the touched services' `tests/` (never trusts the agent).
- **Merge:** `git merge --no-ff` into base branch (repo must be on base branch and clean). **Rollback:** `git revert -m 1`.
- **Deploy (optional):** `HEPHAESTUS_FORGE_DEPLOY_CMD` (`{services}` placeholder), then health check via Hub; unhealthy (checked after `hephaestus.forge.verify_delay`) + setting `hephaestus.forge.auto_rollback` (default on) → revert + redeploy.
- **Notifications:** start, review request (summary + diff stat + test result), merge/deploy, rollback → Telegram via Hermes (`HEPHAESTUS_NOTIFY_TARGET`) + `system/hephaestus.forge` event.
- **Resilience:** task state persisted in `data/forge/tasks.json`; queued/running/approved tasks resume after restart.
- **Human gate on merge:** nothing merges without "approva sviluppo <id>" unless the group is in `full_auto`.
- Who may start/merge alone: see *Permission modes* below.

### Engines — Oracle's chain and Claude Code

| Engine | What | Where configured |
|---|---|---|
| `oracle` | Built-in agent; each turn goes to Oracle `/api/llm/chat` with use case **`forge.codice`** (declared by Hephaestus in its Hub registration), which walks its chain (default `codice`: local Ollama first, then cloud steps; quota skip) | **Oracle → Cervello → Modelli**: chain of `forge.codice` |
| `claude` | Claude Code (Pro/Max subscription) run **by Oracle** in the shared task worktree (`POST /api/llm/code`) | **Oracle**: build `--build-arg INSTALL_CLAUDE_CODE=1`, `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token` in Oracle's `.env` (plan limits) |

Old names `local`, `cloud`, `builtin`, `ollama` (tasks, settings, agenda rules) are read as `oracle`.

**Microservice boundary:** Forge never holds LLM URLs or keys. The built-in agent sends each turn
(messages + tools) to Oracle `POST /api/llm/chat {use_case: "forge.codice"}` via Hub; Oracle owns providers and chains.
Claude Code also lives in Oracle (the LLM core holds every credential, including the Pro token). Task worktrees
are mounted at the same absolute path `/forge/worktrees` in Hephaestus and Oracle, and the repo at `/repo` in both,
so git worktree links resolve. Hephaestus keeps orchestration: branch, independent tests, merge, deploy, rollback.
All other calls also go through Hub: Hermes (notifications), service `/health` (deploy check).
Requests reach Forge only via Hub: user → Telegram → Oracle → Hub → Hephaestus; Athena/Argus → Hub → Hephaestus.

- Default engine = central setting `hephaestus.forge.engine` (Themis, live, default `oracle`): WebUI →
  Impostazioni → Hephaestus, or `POST /api/hephaestus/forge/engine` from a client (saved to Themis as a user
  change). The assistant can only propose it (`settings_propose`), you confirm via Hermes.
  Fallback order = setting `hephaestus.forge.fallback` (default `oracle, claude`).
- Per task: "sviluppa X con claude" → `engine` field (no fallback when explicit).

### Permission modes (like Claude Code / Codex)

One mode per group = central settings `hephaestus.forge.mode.local` / `hephaestus.forge.mode.cloud` (live).
Change them in WebUI → Impostazioni or `POST /api/hephaestus/forge/settings/mode {"mode", "group"}` (saved to
Themis). Safety switches: the assistant may read them but never propose them (`oracle: read`).
`data/forge/settings.json` keeps only the Claude Pro schedule and budget state.

| Mode | Athena/Argus tasks | Your tasks | Merge/deploy |
|---|---|---|---|
| `ask` | wait for "approva sviluppo <id>" | start | waits for you |
| `auto` | start on their own branch | start | waits for you |
| `full_auto` | start | start | automatic if engine ok + tests green (health check, auto rollback) |

Groups: `local` = engine `oracle` while every usable step of `forge.codice` is unbilled (local models; default `auto`);
`cloud` = engine `oracle` with a billed step (cloud key, subscription) or `claude` (default `ask`: no tokens spent without
your ok). Oracle's `/api/llm/usecases/forge.codice` says `billed`.

### Who decides, duplicates, engine per task

- **Who creates tasks**: you (WebUI, Telegram, chat → `source` user/ui/telegram/oracle), Athena (`athena`:
  strategist "improvement" candidates, `athena.forge.enabled`, max `athena.forge.max_per_day`), Argus
  (`argus`: same error signature `argus.forge.threshold` times in `argus.forge.window`, one per
  `argus.forge.cooldown`), remediation escalation (`hephaestus.remediation`: repair failed every attempt).
- **Who decides whether it starts**: Forge, with the permission mode of the engine group (table below) and
  the manual pause. Merge always waits for you unless `full_auto`.
- **Duplicates**: `hephaestus.forge.dedup_days` (default 7, 0 = off). A module proposal with the same
  services and ≥ 60% word overlap (request + start of context, so templated Argus/remediation requests are
  told apart by their error) with any task of those days, rejected included, is not created: the answer is
  the existing task with `duplicate: true`. Your own requests are never filtered.
- **Engine per task**: `approve {engine}` on a `proposed`/`scheduled` task sets who develops it
  (an explicit choice starts now, outside the Claude windows); WebUI Sviluppo has the picker next to Avvia.
  New tasks and follow-ups already take `engine`.
- **Proposer visible**: task `source`/`requested_by`; WebUI list shows it and filters *Dai moduli*; the chat
  brief marks module tasks `· da <source>`.

### Manual pause (brake)

`hephaestus.forge.paused` (Themis, live, `oracle: read`) overrides the modes above: while it is on **nothing
starts on its own**. Tasks from modules (Athena, Argus, remediation escalation, anything not in
`USER_SOURCES`) become silent proposals (`held_by_pause`, no notification), queued autonomous tasks (also
after a restart) are put back to `proposed`, and the scheduler starts no Claude-window task. Your own
requests (WebUI, Telegram, chat) and your "Avvia"/`approve` (`manual_start`) still run; merges you approved
still deploy. Resuming restarts nothing: held tasks stay proposed until you start or reject them.
Switch: WebUI Sviluppo → **Pausa / Riprendi**, Impostazioni → Sistema, Telegram tool `forge_pause`,
or `POST /api/hephaestus/forge/pause {"paused": true|false}`; `status.paused` shows it.

Agent prompt is caveman-style (`app/forge/prompts.py`): short rules, Hestia architecture constraints, docs/tests duty, no secrets.

### Claude Pro budget window (autonomous work on the weekly leftover)

The Pro plan has a weekly limit. Forge spends on autonomous work only what would otherwise be lost:

| Who asks | When a `claude` task starts |
|---|---|
| You (Telegram/UI) | immediately (on demand) |
| Athena / Argus | state `scheduled` → starts only **at night** (`night`, default 00:00-07:00) in the **last `window_hours`** (48) before the weekly reset, max `night_max_tasks` (3) per night, one at a time |
| Athena / Argus, last `final_hours` (6) before reset | any time, no cap: the remaining quota is used up |

- Approving a proposed/scheduled claude task keeps it in the window; "approva sviluppo <id> **subito**" (`now=true`) runs it now.
- If Claude answers with a usage-limit error, Forge pauses all budgeted work until the reset (`phase=exhausted`) and
  re-schedules the task.
- The remaining % is not readable by programs: the policy is time-based + Claude's own limit signal.
- **Assistant agenda:** the two windows live in Chronos' assistant agenda as `forge.claude_nights` and
  `forge.claude_final` (registered at start, updated when the schedule changes). Forge asks the agenda first, so
  moving, pausing or **skipping** a night there ("salta stanotte") is respected; Chronos down → built-in schedule.
  Every Forge task is mirrored in the agenda as `forge.task.<id>`: ⏳ da approvare, 🌙 programmato (at the
  next Claude window), 🔨 in coda/lavorazione, 👀 diff da rivedere, 🔀 merge; completed when the task ends.
  A **scheduled** task follows its entry: cancel it in the agenda → task rejected; move it later → Forge waits.
  **Links**: `agenda_parent` (request field / `forge_develop` arg) links the mirror to the agenda item the task
  serves (e.g. the rule the assistant could not create without a new tool). Cancelling that item cascades to the
  mirror → a proposed or scheduled task is rejected (scheduler pass); a `failed` / `rolled_back` task reports
  `POST /api/agenda/items/forge.task.<id>/fail` so the parent shows the failure.
- Configure from Telegram ("il reset di Claude è lunedì alle 10") → tool `forge_set_claude_schedule`, or
  `POST /api/hephaestus/forge/settings/claude-schedule {reset_day, reset_time, tz, window_hours, night,
  night_max_tasks, final_hours}`. Status: `GET /api/hephaestus/forge/claude-budget`. Persisted in `settings.json`.
  Check the real reset moment in claude.ai → Settings → Usage.

### Forge endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/hephaestus/forge/status` | Repo, base branch, engines availability, queue |
| POST | `/api/hephaestus/forge/pause` | `{"paused": bool}` — manual pause of autonomous starts (saved to Themis); returns `{paused, held[]}` |
| GET | `/api/hephaestus/forge/engine` | Default engine, fallback chain, availability |
| POST | `/api/hephaestus/forge/engine` | `{"engine": "oracle|claude"}` — set default (persisted; `local`/`cloud` read as `oracle`) |
| GET | `/api/hephaestus/forge/settings` | Default engine, fallback, permission modes |
| POST | `/api/hephaestus/forge/settings/mode` | `{"mode": "ask|auto|full_auto", "group": "local|cloud|"}` |
| POST | `/api/hephaestus/forge/tasks` | `{request, services[], engine, auto_start, auto_merge, context, source, notify_target, workdoc, parent_task, agenda_parent}` — `parent_task` = follow-up (inherits workdoc, services, outcome as context); `agenda_parent` = linked agenda key |
| GET | `/api/hephaestus/forge/tasks` | List (`state`, `limit`) |
| GET | `/api/hephaestus/forge/tasks/brief` | One line per task (`id6 · state · services · request`), sized to fit Oracle's tool-result cap — used by the chat tool `forge_tasks` |
| GET | `/api/hephaestus/forge/counts` | Tasks per state + `review` (awaiting_review + proposed) — Sviluppo page badge |
| GET | `/api/hephaestus/forge/tasks/export?ids=a,b` | «Copia per AI»: markdown of the tasks (forge_task/forge_tasks views + how to submit a fix via MCP), returned only |
| GET | `/api/hephaestus/forge/tasks/{id}` | Full record (history, test output, engine log) — short ids accepted |
| GET | `/api/hephaestus/forge/tasks/{id}/diff` | Unified diff (text) |
| POST | `/api/hephaestus/forge/tasks/{id}/approve` | proposed/scheduled → start (claude: waits for window unless `{"now": true}`) · awaiting_review → merge/deploy (async) |
| GET | `/api/hephaestus/forge/claude-budget` | Claude window status: phase (night/final/closed/exhausted), next reset, used tonight |
| POST | `/api/hephaestus/forge/settings/claude-schedule` | Set reset day/time, window, night interval, caps |
| POST | `/api/hephaestus/forge/tasks/{id}/reject` | Discard + delete branch |
| POST | `/api/hephaestus/forge/tasks/{id}/rollback` | Revert merged change |
| POST | `/api/hephaestus/forge/tasks/{id}/retry` | Same request again as a new task (failed, no_changes, rejected, rolled_back) |
| GET | `/api/hephaestus/forge/tasks/{id}/transcript?offset&limit` | Engine conversation, normalized (see below); live while Claude runs |
| GET | `/api/hephaestus/forge/tasks/{id}/files?diff` | Changed files (+/−, status) and diff; live worktree includes uncommitted/untracked files |
| GET | `/api/hephaestus/forge/tasks/{id}/workdoc` | Dossier `docs/work/<workdoc>/*.md` + every other `.md` the task changed |
| GET | `/api/hephaestus/forge/tasks/{id}/tests` · `logs` · `events` | Full pytest output + counts · engine/deploy logs · state timeline |
| GET | `/api/hephaestus/forge/tasks/{id}/overview` | Compact task + notes + last 20 state changes + submitted branch (tool `forge_task`) |
| POST | `/api/hephaestus/forge/tasks/{id}/notes` | `{text, by}` — analysis/hint on a task (tool `forge_task_note`); `by` = `X-Hestia-Access` when present |
| POST | `/api/hephaestus/forge/tasks/{id}/submit-branch` | `{branch, summary}` — "fixed on this branch" (tool `forge_submit_branch`), see below |
| GET | `/api/hephaestus/repo/branches` · `tags` · `log` · `commits/{sha}` · `compare` · `tree` · `file` · `dossiers` | Read-only git browser of the checkout (Sviluppo page) |
| GET | `/api/hephaestus/repo/dossiers/{name}` | SPEC, PROGRESS, CHANGELOG of `docs/work/<name>/` (tool `forge_dossier`) |

### External AIs (MCP access) — notes and "fixed on this branch"

SPEC `docs/work/2026-10-18-moduli-core-e-mcp-esterno` §B4. With an access made on the WebUI page *Accessi AI*,
an external AI (Claude Code, Cursor…) reaches the tools Forge marked `"external"`: `forge_tasks`, `forge_task`,
`forge_task_diff`, `forge_dossier`, `forge_status` (read) and `forge_develop`, `forge_task_note`,
`forge_submit_branch` (write access). Approve, reject, merge, rollback, pause and engine settings stay internal.

- Hestia-MCP sends `X-Hestia-Access: <access name>`. `POST /forge/tasks` with it → `source=external`,
  `requested_by=<name>`, `auto_start`/`auto_merge` of the body ignored: an external request is a proposal like a
  module's (permission mode, pause and duplicates apply), never "the user typed it".
- **Notes** (`notes[]`, last 30): shown with the task; the last 10 go into the engine prompt context when the task
  runs, and into the context of a retry.
- **Submit branch**: task in `proposed`, `scheduled`, `failed`, `no_changes` or `awaiting_review`; branch name
  checked (no `..`, not `auto/forge/*`). The task is queued; the worker fetches `refs/heads/<branch>` from `origin`
  (`git_ops.fetch_branch`), puts it in the task worktree on `auto/forge/<id>` (engine `external`), runs Forge's own
  tests and asks the approval as for any change ("Forge: correzione esterna pronta (<name>)"). `auto_merge` is
  forced off: every external fix waits for the owner. After the ok: merge, deploy, health check, auto rollback as
  usual. Fetch failure → `failed` with the git error; branch equal to base → `no_changes`.

### Task artifacts & transcript (Sviluppo page)

- Per task: `data/forge/tasks/<id>/` → `transcript.jsonl`, `tests.txt` (full pytest output), `engine.log`, `deploy.log`.
- **Transcript** = one normalized format for every engine: `{i, ts, kind, text, tool, id, input, is_error, meta}`
  with `kind` = `user` (task prompt / nudges) · `text` · `thinking` · `tool_use` · `tool_result` · `system` · `result` · `error`.
  - `claude`: Oracle runs `claude -p --output-format stream-json --verbose` and writes every line live to
    `/forge/worktrees/.transcripts/<id>.jsonl` (shared mount, outside the worktree so it is never committed).
    While the run lasts, `/transcript` normalizes it on read (live view); at the end Forge imports it into
    `transcript.jsonl` and deletes the raw file.
  - `oracle`: the built-in agent loop emits assistant text, reasoning (when the model returns it),
    every tool call with its arguments and every tool result.
- **Repo browser** (`forge/repo_browser.py`): only `git` plumbing, refs/paths validated (no `..`, no `.git`, no
  leading `-`), secret files (`.env`, tokens, credentials) listed as secret and never served, diffs capped at 300 KB,
  files at 400 KB.

MCP tools: `forge_develop`, `forge_tasks`, `forge_status`, `forge_set_claude_schedule`, `forge_settings`, `forge_approve`, `forge_reject`, `forge_rollback` (domain `system`).

### Deployment notes
- Compose mounts the repo at `/repo`, worktrees at `/forge/worktrees` (same paths in Oracle, where Claude
  Code runs) and the Docker socket (deploy). Images trust the mounted repo (`git safe.directory '*'`).
- **Tests**: Hephaestus and Oracle images install `requirements-forge-tests.txt` (union of every Python
  service's light deps), so any service's pytest suite runs. Add new service deps there too.
- **Deploy** `HEPHAESTUS_FORGE_DEPLOY_CMD=builtin` (`forge/deployer.py`): restart `hestia_<svc>` of the touched
  services via Docker socket (code is volume-mounted). `Hestia-Shared` change → all Python services.
  Dockerfile / requirements / WebUI changes → notified as "da ricostruire a mano: `up-all.bat --build <svc>`".
  Hephaestus restarts itself last (task state persisted). Custom shell command with `{services}` still works;
  empty = manual restart.
- **Work protocol** (prompt-enforced, see `CLAUDE.md`): every task writes `docs/work/<workdoc>/SPEC.md`,
  `PROGRESS.md`, `CHANGELOG.md` + a line in root `CHANGELOG.md`. Task field `workdoc`; pass `workdoc` on a new
  task to **continue** an interrupted one.
- Claude Code tool allowlist (Oracle): read/edit/write, pytest, py_compile, git status/diff/log/show, ls, mkdir.
  No commit/push/network/docker: Forge commits, the user approves the merge.

## Command Discovery

Hephaestus publishes assistant-executable command metadata through Hub discovery for:
- status
- runbook listing
- task listing
- remediation task creation
- remediation approval
- remediation rollback


## Documentation Synchronization (Required)

1. Any behavior, command, or contract change must update this service document in the same change set.
2. If API routes, methods, schemas, or Hub-routed command contracts change, update Hestia-Swagger/swagger.yml in the same change.
3. Ensure command metadata exposed to Hub discovery is complete and accurate (service, method, path, arguments/templates) so Oracle and clients can execute deterministically.
4. Keep canonical payloads rich at source; client-facing detail level is controlled by client rendering policy (minimal/compact/rich), not by deleting upstream semantics.

## Central settings (Themis)

Declared in `app/forge/forge_settings.py` (`SettingsClient("hephaestus")`), all **live** (read at use time;
engine/modes also applied by `Forge._apply_settings`). Endpoints `GET /api/settings/effective`,
`POST /api/settings/reload` (used by Themis). `oracle: read` = safety switch, the assistant never proposes it.

| Key | Type · default | Effect |
|---|---|---|
| `hephaestus.forge.paused` | bool · `false` (read) | manual pause: no task starts on its own (see *Manual pause*) |
| `hephaestus.forge.dedup_days` | int giorni · 7 (0–90) | module proposals similar to a task of these days are not created again |
| `hephaestus.forge.engine` | enum · `oracle` | default coding engine (`oracle` = Oracle chain of `forge.codice`, `claude`) |
| `hephaestus.forge.mode.local` / `.cloud` | enum · `auto` / `ask` (read) | permission mode per group |
| `hephaestus.forge.fallback` | list · `[oracle, claude]` | engines tried when the default is unavailable |
| `hephaestus.forge.max_turns` | int · 40 (5–300) | agent turn limit (built-in loop and Claude Code) |
| `hephaestus.forge.llm_timeout` | int s · 600 | Oracle `/api/llm/chat` timeout per turn |
| `hephaestus.forge.engine_timeout` | int s · 1800 | Claude Code session timeout |
| `hephaestus.forge.auto_merge` | bool · off (read) | default `auto_merge` of new tasks |
| `hephaestus.forge.auto_rollback` | bool · on (read) | revert + redeploy when post-deploy health fails |
| `hephaestus.forge.push_branch` | bool · off (read) | `git push` the task branch after tests |
| `hephaestus.forge.verify_delay` | int s · 20 | wait before the post-deploy health check |
| `hephaestus.forge.scheduler_interval` | int s · 300 | how often waiting Claude-window tasks are checked |
| `hephaestus.remediate.timeout` | float s · 25 | Hub-routed maintenance execution timeout |
| `hephaestus.remediate.require_approval` | bool · on (read) | non-dry-run repairs wait for approval |
| `hephaestus.remediate.auto_approve_non_prod` | bool · off (read) | allow auto-approve outside prod |
| `hephaestus.remediate.retry_minutes` | int min · 15 | retry delay × attempt of a failed repair |
| `hephaestus.remediate.max_attempts` | int · 3 | attempts before escalation to Forge |
| `hephaestus.log.level` | enum · `LOG_LEVEL` boot value | log verbosity |

Env keeps infrastructure only: service identity/Hub URL, `HEPHAESTUS_REPO_PATH`/`_WORKTREES_PATH`/`_DATA_DIR`/
`_FORGE_STATE_FILE`/`_FORGE_SETTINGS_FILE` (volumes), `HEPHAESTUS_FORGE_ENABLED` (the deployment mounts repo,
worktrees and Docker socket), `HEPHAESTUS_FORGE_BASE_BRANCH` and `_GIT_NAME/_GIT_EMAIL` (git identity),
`HEPHAESTUS_FORGE_TEST_CMD`/`_DEPLOY_CMD` (shell commands run verbatim in the container: image-dependent and a
code-execution surface, so not editable from clients), `HEPHAESTUS_NOTIFY_TARGET` (owner chat address),
`HEPHAESTUS_BASELINE_REF`, `HEPHAESTUS_MAINTENANCE_PATHS` (endpoint templates).

## Assistant presence

Forge reports its work to Chronos presence: each task runs as activity `forge.task` (heavy, claude_quota/gpu), each deploy as `hephaestus.deploy` (maintenance → «Sto mangiando»). Autonomous scheduled tasks start only when presence allows `work.heavy` and `llm.claude` (unknown → allowed). Claude limit exhausted → signal `resource.claude_quota_left=0` until the reset.

### Engine `oracle` and the context window

The built-in engine reads the model window from Oracle's `/api/llm/usecases/forge.codice`
(`context_window` of the first usable step, = Themis `oracle.provider.ollama.num_ctx` for an Ollama step) and keeps the
prompt within ~70% of it (≈3 chars/token): old tool outputs become `[old output trimmed]`, the latest
one is clipped with a hint to read a smaller range. A stop is reported precisely: `model context full`
(answer cut, `finish_reason=length` → raise num_ctx or use `claude`), `turn limit reached`, or
`model stopped calling tools`. Coding on a local model needs a large window (≥32k tokens).

## Telegram menus
Tool titles are plain Italian without emoji; each tool says where it goes on Telegram with `telegram_group` (area) and `telegram={section, primary, summary, label}` (docs/work/2026-10-23-telegram-da-zero §5.7, checked by `tools/governance/check_telegram.py`). Here: sistema › Riparazioni: 5; sviluppo › Lavori: 10; sviluppo › Avanzate: 1; sviluppo › Impostazioni sviluppo: 3 (area › section: tools).

## Redaction and Marko's rules (dossier `docs/work/2026-10-24-tutto-brainstorm-cindy`)
The context of a Forge task prompt passes through `hestia_common.redact.redact` (Cindy 19). The coding engine's
«read first» list includes `docs/REGOLE-DI-MARKO.md` (dated rules + the new-feature checklist, Cindy 11).

## Automatic review, team plan, resume after the Claude limit (dossier `docs/work/2026-10-24-tutto-brainstorm-cindy`, wave 3)
- **Reviewer** (Cindy 3, `app/forge/review.py`): after the tests the task goes to state `reviewing`. A fresh model
  with no tools and no memory of the work (Oracle `/api/llm/generate`, use case `forge.revisione`, chain potente)
  gets only labelled evidence: request, acceptance criteria of the task SPEC (`docs/work/<WORKDOC>/SPEC.md`), the
  diff, the real test output, and the engine's summary marked «autodichiarazione non verificata». Answer =
  `{verdict ok|problemi|non_disponibile, issues[{priority alta|media|bassa, file, problem, evidence}], blocking}`.
  Blocking issues (alta/media) go back to the same engine for **one** fix round (`fix_prompt`), then tests and review
  again. Saved as `review.json` in the task artifacts and `task.review`; the approval card shows «Revisione
  automatica: …». Auto-merge (permission mode) only when nothing blocking is left. Model down → step skipped `[🔄]`.
- **Team plan** (Cindy 31): a task touching ≥ `hephaestus.forge.squadra.min_servizi` services (Themis, default 3),
  not external, is split by the model (use case `forge.piano`) into 2–4 pieces run **one after the other in the same
  worktree**; `semplice` → engine `oracle` (local chain), `difficile` → `claude` (falls back to the task engine).
  `task.team` lists the pieces and their outcome; the reviewer runs on the whole result.
- **Resume after the Claude limit** (Cindy 15): when Claude stops on the usage limit Forge commits the partial work to
  `refs/forge/resume/<id>`, sets state `waiting_limit` and plans the agenda task `forge.resume.<id>` at the reset time
  (+30–90 s) → `POST /api/hephaestus/forge/tasks/{id}/resume`; the run restarts from that commit with a «RIPRESA»
  note. Three restarts without progress (`limit_restarts`) → failed. Budget-window tasks go back to `scheduled`.
- Endpoint: `POST /api/hephaestus/forge/tasks/{task_id}/resume`. Task fields: `review`, `team`, `limit_restarts`.

**2026-10-29 (texts for people, dossier `docs/work/2026-10-29-revisione-e-test-frontend`)**: Plugin title «Sviluppo»; agenda titles «Sviluppo programmato» and «Riprendi lo sviluppo: …».

## Guided setup «Benvenuto» (`app/setup/`, dossier `docs/work/2026-10-30-setup-un-click`)

Hephaestus owns the setup's writes because it already has the repo (`/repo`, where the `.env` files are) and the
Docker socket. Endpoints `/api/setup/*` (state, later, complete, brain/catalog|test|apply|pull|pulls,
telegram/token|code|claim, backup) are called by the WebUI through the Hub (`/api/webui/setup/*`) and, for
`telegram/claim` only, by the Telegram bot.

- `setup/secrets.py`: whitelist `TELEGRAM_BOT_TOKEN`, `ALLOWED_USER_ID` (→ `Hestia-Telegram/app/.env`, telegram),
  `CLAUDE_CODE_OAUTH_TOKEN`, `HF_TOKEN`, `ORACLE_KEY_<NAME>` (→ `Hestia-Oracle/app/.env`, oracle),
  `HESTIA_BACKUP_PASSPHRASE` (→ root `.env`, archive). Values: one line of printable ASCII; ids numeric; bot token
  in BotFather form. Written atomically (active line, else the commented `# KEY=` line, else appended); a value is
  never logged or returned (`event=setup_secret_set key=… file=… services=…`).
- `recreate_with_env`: `env_file` is read only when a container is created, so a restart would not see a new key.
  The container is re-created through the Docker API with the same image, mounts, ports, networks/aliases, restart
  policy and healthcheck plus the changed variables; the old one is renamed and kept until the new one starts, and
  comes back on failure (`[🔄] event=setup_recreate_failed`).
- `setup/service.py`: state in `data/setup.json` (completed, steps left for later — cervello, voce, telegram, backup, esterni —, brain choice), hardware from
  `/repo/.hestia-install/hardware.json` (written by the installer). Telegram link: a 6-digit one-time code (10
  minutes, 5 tries, compared in constant time); the bot, while `ALLOWED_USER_ID` is empty, forwards a 6-digit
  message to `telegram/claim` and the sender becomes the owner (the bot is re-created 3 s later, after its reply).
  The brain itself is Oracle's (`/api/llm/setup/*`): Hephaestus writes the keys, waits for Oracle's health, then
  forwards the choice and starts the downloads (chat model + `qwen3-embedding:0.6b`).
