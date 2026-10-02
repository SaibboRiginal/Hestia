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
- POST /api/hephaestus/remediate/{task_id}/rollback
- GET /api/hephaestus/tasks
- GET /api/hephaestus/tasks/{task_id}

Execution endpoints above are implemented as policy-gated remediation flows (task creation, approval, rollback metadata) with real Hub-routed maintenance execution against target services.

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
- **Human gate on merge:** nothing merges without "approva sviluppo <id>". `HEPHAESTUS_FORGE_AUTO_MERGE=1` merges only when engine ok AND tests green.
- **Autonomy policy (who may start coding alone):** user-typed requests always start. Tasks from Athena/Argus follow a
  per-engine policy, changeable from the client (Telegram "in locale lascia fare ad Athena" → tool `forge_set_autonomy`,
  or `POST /api/hephaestus/forge/settings/autonomy {"engine","mode"}`), persisted in `data/forge/settings.json`:

  | Engine | Default mode | Meaning |
  |---|---|---|
  | `local` | `auto_start` | codes on its own branch right away; you approve the merge |
  | `cloud`, `claude` | `propose` | waits for "approva sviluppo <id>" before spending tokens; then you approve the merge |
  | `aider` | `auto_start` | as local |

### Engines — local and cloud side by side

All engines can be configured together; one is the **default**, the others are a
**fallback chain** and can be picked per task.

| Engine | What | Config |
|---|---|---|
| `local` | Built-in agent on Ollama/LM Studio (your PC) | `HEPHAESTUS_FORGE_LOCAL_BASE_URL/_MODEL/_API_KEY` (default Ollama `qwen2.5-coder:14b`) |
| `cloud` | Same built-in agent on any OpenAI-compatible API (OpenRouter, Gemini...) | `HEPHAESTUS_FORGE_CLOUD_BASE_URL/_MODEL/_API_KEY` |
| `claude` | Claude Code CLI headless | build `--build-arg INSTALL_CLAUDE_CODE=1`; Pro/Max: `claude setup-token` → `CLAUDE_CODE_OAUTH_TOKEN` (uses plan limits); or `ANTHROPIC_API_KEY` |
| `aider` | Aider CLI (optional) | `HEPHAESTUS_FORGE_AIDER_MODEL` |

- Default: `HEPHAESTUS_FORGE_ENGINE=local`. Fallback: `HEPHAESTUS_FORGE_FALLBACK=local,cloud,claude`
  (used when the chosen default is unavailable: PC off, missing key, refused auth).
- **Switch at runtime** without restart: Telegram "usa il cloud" / "passa a locale" (tool `forge_set_engine`)
  or `POST /api/hephaestus/forge/engine {"engine": "cloud"}`. Persisted in `data/forge/settings.json`.
- **Per task:** "sviluppa X con claude" → `engine` field on the task (no fallback when explicit).
- `GET /api/hephaestus/forge/engine` shows default, fallback and availability of each engine.
- Aliases accepted: `builtin`/`ollama` → `local`, `claude_code` → `claude`. Legacy `HEPHAESTUS_FORGE_LLM_*` vars feed `local`.

Agent prompt is caveman-style (`app/forge/prompts.py`): short rules, Hestia architecture constraints, docs/tests duty, no secrets.

### Forge endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/hephaestus/forge/status` | Repo, base branch, engines availability, queue |
| GET | `/api/hephaestus/forge/engine` | Default engine, fallback chain, availability |
| POST | `/api/hephaestus/forge/engine` | `{"engine": "local|cloud|claude|aider"}` — set default (persisted) |
| GET | `/api/hephaestus/forge/settings` | Default engine, fallback, autonomy per engine, auto_merge |
| POST | `/api/hephaestus/forge/settings/autonomy` | `{"engine": "...", "mode": "propose|auto_start"}` |
| POST | `/api/hephaestus/forge/tasks` | `{request, services[], engine, auto_start, auto_merge, context, source, notify_target}` |
| GET | `/api/hephaestus/forge/tasks` | List (`state`, `limit`) |
| GET | `/api/hephaestus/forge/tasks/{id}` | Full record (history, test output, engine log) — short ids accepted |
| GET | `/api/hephaestus/forge/tasks/{id}/diff` | Unified diff (text) |
| POST | `/api/hephaestus/forge/tasks/{id}/approve` | proposed → start · awaiting_review → merge/deploy (async) |
| POST | `/api/hephaestus/forge/tasks/{id}/reject` | Discard + delete branch |
| POST | `/api/hephaestus/forge/tasks/{id}/rollback` | Revert merged change |

MCP tools: `forge_develop`, `forge_tasks`, `forge_status`, `forge_set_engine`, `forge_set_autonomy`, `forge_settings`, `forge_approve`, `forge_reject`, `forge_rollback` (domain `system`).

### Deployment notes
- Compose mounts the repo at `/repo` and `data/` for state. Uncomment the docker socket only if the deploy command restarts containers.
- Global compose live-mounts service code, so a container restart applies merged code.
- If Forge changes Hephaestus itself, the deploy restarts Forge: the task stays `merged` (state is persisted).
- The container has pytest but not every service dependency; heavy services may need their deps installed or a custom `HEPHAESTUS_FORGE_TEST_CMD`.

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
