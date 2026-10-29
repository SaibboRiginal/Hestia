# CI stabile

| Version | Source | Status |
|---|---|---|
| 1.0 | user via external chat (Marko: «la ci continua spesso a fallire») | done |

## 1. Goal
Fewer red CI runs that are not real bugs, and the real ones found before the push.

## 2. What the runs said (300 runs read, 2026-10-18 → 2026-10-29)
Main has been green since 2026-10-18: every red run is on a PR branch. Causes, by count:

| Cause | Runs | Kind |
|---|---|---|
| Docs sync gate: `docs/ARCHITECTURE.md` or a service doc not touched (also when only tests changed) | 8 | forgotten doc / gate too strict |
| Command contract gate: `architecture-and-flow-map.md` not touched | 3 | forgotten doc |
| Hub refuses a new module's tags (Hygieia, Plutus, Echo) | 4 | real bug, found late |
| Oracle test polluted by another test's mock of `main.engine` | 2 | order-dependent test (fixed in W3) |
| Hecate feed cache «fresh» right after boot (`monotonic()` from 0) | 1 | flaky on fresh runners (fixed in W6) |
| Others (Telegram reachability, emoji in a title, Wardrobe, Athena, collection errors on a WIP push) | 7 | real bugs caught before merge |

No network or install failure and no timeout was seen. Each test failure also turned the
«Publish test results» step red, so one failure showed as two.

## 3. Scope and design
- Gates: test files, `.github/` and `tools/governance/` are not behaviour (docs sync and contract gate).
- New gate `check_hub_tags.py`: compose files + `app/main.py` defaults + `ModuleKit` modules against the Hub
  vocabulary, in the governance workflow (seconds, before the 29-service matrix).
- `check_test_sync.py` now runs in the governance workflow (it existed but no workflow ran it).
- `tools/governance/precheck.py`: every gate locally against `origin/main`, before the push (CLAUDE.md step 7).
- Workflows: `concurrency` cancels a superseded PR run (never on main), `timeout-minutes`, pip cache +
  `PIP_RETRIES`/`PIP_TIMEOUT`, test reporter `fail-on-error: false`, every governance gate runs even after a failed one.

## 4. New feature checklist
1. Real job for the owner: main always ready for his `git pull`, threads stop looping on red CI.
2. Owner module: none (CI and `tools/governance`).
3. Configuration: none.
4. Push or poll: n/a.
5. Who confirms: the thread merges when CI is green (Marko 2026-10-22).
6. WebUI / Telegram: n/a.
7. Stop, correct, undo: revert the PR.
8. Docs that change: CLAUDE.md, docs/ARCHITECTURE.md (governance), TESTING.md, root CHANGELOG.

## 5. Acceptance criteria
- Governance and test workflows green on the PR; precheck prints 0 failed on the branch.
- A PR changing only tests does not ask for docs.
