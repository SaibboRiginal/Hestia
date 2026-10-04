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
- POST /api/hephaestus/remediate/{task_id}/rollback
- GET /api/hephaestus/tasks
- GET /api/hephaestus/tasks/{task_id}

Execution endpoints above are implemented as policy-gated remediation flows (task creation, approval, rollback metadata) with real Hub-routed maintenance execution against target services.

### Repairs in the assistant agenda

- Repair waiting for approval → event `hephaestus.repair.<id>` ("🛠️ Riparazione da approvare").
- Failed (non dry-run) repair → agenda task retry after `HEPHAESTUS_REPAIR_RETRY_MINUTES` × attempt (default 15),
  up to `HEPHAESTUS_REPAIR_MAX_ATTEMPTS` (3); fired via Hub → `/remediate/{id}/retry`.
- Last failure → **escalated to Forge** as a code-fix task (state `escalated`, `forge_task_id`); Forge applies
  your permission mode. Success/rollback completes the agenda entry.

## Safety contract (Current)
- Production mutation requires explicit approval.
- Non-production mutation can be policy-gated via `HEPHAESTUS_REQUIRE_APPROVAL_FOR_MUTATION`.
- Auto-approval can be blocked/enabled via `HEPHAESTUS_ALLOW_AUTO_APPROVE_NON_PROD`.
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
- **Deploy (optional):** `HEPHAESTUS_FORGE_DEPLOY_CMD` (`{services}` placeholder), then health check via Hub; unhealthy + `HEPHAESTUS_FORGE_AUTO_ROLLBACK=1` → revert + redeploy.
- **Notifications:** start, review request (summary + diff stat + test result), merge/deploy, rollback → Telegram via Hermes (`HEPHAESTUS_NOTIFY_TARGET`) + `system/hephaestus.forge` event.
- **Resilience:** task state persisted in `data/forge/tasks.json`; queued/running/approved tasks resume after restart.
- **Human gate on merge:** nothing merges without "approva sviluppo <id>" unless the group is in `full_auto`.
- Who may start/merge alone: see *Permission modes* below.

### Engines — local and cloud side by side

| Engine | What | Where configured |
|---|---|---|
| `local` | Built-in agent; LLM = Oracle profile `local` (Ollama) | **Oracle**: `ORACLE_LLM_PROFILE_LOCAL_BASE_URL/_MODEL/_API_KEY` (default Ollama `qwen2.5-coder:14b`) |
| `cloud` | Built-in agent; LLM = Oracle profile `cloud` (OpenRouter, Gemini...) | **Oracle**: `ORACLE_LLM_PROFILE_CLOUD_*` |
| `claude` | Claude Code (Pro/Max subscription) run **by Oracle** in the shared task worktree (`POST /api/llm/code`) | **Oracle**: build `--build-arg INSTALL_CLAUDE_CODE=1`, `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token` in Oracle's `.env` (plan limits) |

**Microservice boundary:** Forge never holds LLM URLs or keys. The built-in agent sends each turn
(messages + tools) to Oracle `POST /api/llm/chat {profile}` via Hub; Oracle owns providers.
Claude Code also lives in Oracle (the LLM core holds every credential, including the Pro token). Task worktrees
are mounted at the same absolute path `/forge/worktrees` in Hephaestus and Oracle, and the repo at `/repo` in both,
so git worktree links resolve. Hephaestus keeps orchestration: branch, independent tests, merge, deploy, rollback.
All other calls also go through Hub: Hermes (notifications), service `/health` (deploy check).
Requests reach Forge only via Hub: user → Telegram → Oracle → Hub → Hephaestus; Athena/Argus → Hub → Hephaestus.

- Default: `HEPHAESTUS_FORGE_ENGINE=local`; fallback `HEPHAESTUS_FORGE_FALLBACK=local,cloud,claude`.
- Switch default from Telegram ("usa il cloud") → tool `forge_set_engine`, persisted.
- Per task: "sviluppa X con claude" → `engine` field (no fallback when explicit).

### Permission modes (like Claude Code / Codex)

One mode per group, set from Telegram ("modalità sviluppo auto", "cloud in ask") → tool `forge_set_mode`
or `POST /api/hephaestus/forge/settings/mode {"mode", "group"}`. Persisted in `data/forge/settings.json`.

| Mode | Athena/Argus tasks | Your tasks | Merge/deploy |
|---|---|---|---|
| `ask` | wait for "approva sviluppo <id>" | start | waits for you |
| `auto` | start on their own branch | start | waits for you |
| `full_auto` | start | start | automatic if engine ok + tests green (health check, auto rollback) |

Groups: `local` = local engine (default `auto`); `cloud` = cloud profile + claude (default `ask`: no tokens spent without your ok).

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
- Configure from Telegram ("il reset di Claude è lunedì alle 10") → tool `forge_set_claude_schedule`, or
  `POST /api/hephaestus/forge/settings/claude-schedule {reset_day, reset_time, tz, window_hours, night,
  night_max_tasks, final_hours}`. Status: `GET /api/hephaestus/forge/claude-budget`. Persisted in `settings.json`.
  Check the real reset moment in claude.ai → Settings → Usage.

### Forge endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/hephaestus/forge/status` | Repo, base branch, engines availability, queue |
| GET | `/api/hephaestus/forge/engine` | Default engine, fallback chain, availability |
| POST | `/api/hephaestus/forge/engine` | `{"engine": "local|cloud|claude"}` — set default (persisted) |
| GET | `/api/hephaestus/forge/settings` | Default engine, fallback, permission modes |
| POST | `/api/hephaestus/forge/settings/mode` | `{"mode": "ask|auto|full_auto", "group": "local|cloud|"}` |
| POST | `/api/hephaestus/forge/tasks` | `{request, services[], engine, auto_start, auto_merge, context, source, notify_target, workdoc, parent_task}` — `parent_task` = follow-up (inherits workdoc, services, outcome as context) |
| GET | `/api/hephaestus/forge/tasks` | List (`state`, `limit`) |
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
| GET | `/api/hephaestus/repo/branches` · `tags` · `log` · `commits/{sha}` · `compare` · `tree` · `file` · `dossiers` | Read-only git browser of the checkout (Sviluppo page) |

### Task artifacts & transcript (Sviluppo page)

- Per task: `data/forge/tasks/<id>/` → `transcript.jsonl`, `tests.txt` (full pytest output), `engine.log`, `deploy.log`.
- **Transcript** = one normalized format for every engine: `{i, ts, kind, text, tool, id, input, is_error, meta}`
  with `kind` = `user` (task prompt / nudges) · `text` · `thinking` · `tool_use` · `tool_result` · `system` · `result` · `error`.
  - `claude`: Oracle runs `claude -p --output-format stream-json --verbose` and writes every line live to
    `/forge/worktrees/.transcripts/<id>.jsonl` (shared mount, outside the worktree so it is never committed).
    While the run lasts, `/transcript` normalizes it on read (live view); at the end Forge imports it into
    `transcript.jsonl` and deletes the raw file.
  - `local` / `cloud`: the built-in agent loop emits assistant text, reasoning (when the model returns it),
    every tool call with its arguments and every tool result.
- **Repo browser** (`forge/repo_browser.py`): only `git` plumbing, refs/paths validated (no `..`, no `.git`, no
  leading `-`), secret files (`.env`, tokens, credentials) listed as secret and never served, diffs capped at 300 KB,
  files at 400 KB.

MCP tools: `forge_develop`, `forge_tasks`, `forge_status`, `forge_set_engine`, `forge_set_mode`, `forge_set_claude_schedule`, `forge_settings`, `forge_approve`, `forge_reject`, `forge_rollback` (domain `system`).

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
