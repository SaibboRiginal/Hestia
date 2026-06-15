# Hestia — Master Test Index

> Each service owns its test plan at `Hestia-<name>/tests/TESTING.md`.
> This file is the cross-service index and execution order reference.

## Test Marker Reference

```
pytest -m unit          Fast mocked tests (no LLM, no network)
pytest -m llm_live      Live LLM tests (requires local Ollama)
pytest -m api           FastAPI TestClient endpoint tests (no LLM)
pytest -m integration   Cross-service integration (Ollama + mocked Hub/Archive)
pytest -m format        Message formatting and output contract tests
```

Run everything: `pytest --tb=short -v` or `run-tests.bat`
Run critical only: `pytest -m "unit or api or format" --tb=short -v`

## Per-Service Test Plans

| Service | Test Plan | Priority |
|---------|-----------|----------|
| Oracle | [Hestia-Oracle/tests/TESTING.md](Hestia-Oracle/tests/TESTING.md) | 🔴 CRITICAL |
| Telegram | [Hestia-Telegram/tests/TESTING.md](Hestia-Telegram/tests/TESTING.md) | 🔴 CRITICAL |
| Athena | [Hestia-Athena/tests/TESTING.md](Hestia-Athena/tests/TESTING.md) | 🔴 CRITICAL |
| Hub | [Hestia-Hub/tests/TESTING.md](Hestia-Hub/tests/TESTING.md) | 🟡 HIGH |
| Archive | [Hestia-Archive/tests/TESTING.md](Hestia-Archive/tests/TESTING.md) | 🟡 HIGH |
| Hermes | [Hestia-Hermes/tests/TESTING.md](Hestia-Hermes/tests/TESTING.md) | 🟡 HIGH |
| Hecate | [Hestia-Hecate/tests/TESTING.md](Hestia-Hecate/tests/TESTING.md) | 🟡 HIGH |
| Chronos | [Hestia-Chronos/tests/TESTING.md](Hestia-Chronos/tests/TESTING.md) | 🟡 HIGH |
| Iris | [Hestia-Iris/tests/TESTING.md](Hestia-Iris/tests/TESTING.md) | 🟡 HIGH |
| Argus | [Hestia-Argus/tests/TESTING.md](Hestia-Argus/tests/TESTING.md) | 🟢 NORMAL |
| Hephaestus | [Hestia-Hephaestus/tests/TESTING.md](Hestia-Hephaestus/tests/TESTING.md) | 🟢 NORMAL |
| Scout | [Hestia-Scout/tests/TESTING.md](Hestia-Scout/tests/TESTING.md) | 🟢 NORMAL |
| Atlas | [Hestia-Atlas/tests/TESTING.md](Hestia-Atlas/tests/TESTING.md) | 🟢 NORMAL |
| Dummy | [Hestia-Dummy/tests/TESTING.md](Hestia-Dummy/tests/TESTING.md) | 🟢 NORMAL |

## Critical Regressions Log

> Any time a test is written because of a real user-facing bug, document it here.

| Date | Symptom | Test Added | Root Cause |
|------|---------|-----------|------------|
| _first entry TBD_ | LLM returns `**bold**` instead of `<b>bold</b>` | Telegram 2.1.1, Oracle 1.8.13 | Format contract not enforced on all paths |
| _first entry TBD_ | Tool not called for calendar query | Oracle 1.8.1 | Agent loop pattern matching failed |
| _first entry TBD_ | "non voglio notifiche" not persisted | Oracle 1.8.6, 1.4.2 | Control extraction not triggered |

## Execution Order (Priority)

1. **Oracle** — unit tests first (agent_loop, chat_classifier, memory_intent)
2. **Telegram** — message format is the most user-visible path
3. **Oracle** — live LLM tool-calling (requires Ollama)
4. **Telegram** — all user paths (bot handlers, commands, formatters)
5. **Athena** — proactive cognition tests
6. **Hub → Archive → Hermes** — core infrastructure
7. **Hecate → Chronos → Iris** — gateway services
8. **Argus → Hephaestus** — organ services
9. **Scout → Atlas → Dummy** — domain/support modules
10. **Governance** — check_test_sync.py gate

---

_Each service's `tests/TESTING.md` is that service's single source of truth for test status._
_Update the per-service file with every test change — not this index._
