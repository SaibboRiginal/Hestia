# Hestia-Shared 📦

**Role:** Shared Runtime Library
**Type:** Python library package (not a deployable service)

---

## Responsibility

Provides cross-cutting utilities consumed by all Hestia services:
- `logging_utils.py` — Uniform service logging setup, log event helpers, and in-memory ring buffer for runtime inspection.
- `startup_utils.py` — Generic Hub readiness wait and dependency-check helpers.
- `task_lifecycle.py` — Background thread lifecycle management utilities.

---

## Usage

Installed as an editable package in each service container or virtual environment:

```bash
pip install -e /path/to/Hestia-Shared
```

Or referenced directly via `PYTHONPATH` in Docker Compose volumes.

---

## Assistant agenda client (`hestia_common.agenda_client`)

Modules plan their work in Hestia's own agenda (Chronos `/api/agenda*`, via Hub) instead of hardcoding times:

```python
from hestia_common.agenda_client import AgendaClient, job_rule, daily_window

agenda = AgendaClient("scout")                       # owner = module name
agenda.register_async(lambda: [                       # retry until Chronos answers, re-assert hourly
    job_rule("scout.email_cycle", "Scout: email", service="scout", path="/api/scout/cycle",
             recurrence="FREQ=MINUTELY;INTERVAL=30"),
    daily_window("athena.consolidation", "Athena: consolidamento", 3, 5),
])
agenda.is_open("athena.consolidation", fallback=lambda: 3 <= now.hour < 5)   # window gate
agenda.should_self_run("scout.email_cycle", 1800)    # job fallback guard (Chronos down / missing / stale)
agenda.plan("metis.train.42", "Training", start_at, action={...})            # one-off task
agenda.show(key, title, start_at); agenda.done(key); agenda.cancel(key)     # informational events
agenda.agenda(days=7, owner=None)                    # see every module's plans
```

Rules are idempotent by `key`; edits made by the user (`user_modified`) are never overwritten. A paused or
cancelled rule is a user decision: `is_open` → closed, `should_self_run` → False. Every call fails soft.

## Constraints

- No domain logic — pure library code.
- No service registration or Hub contracts.
- No runtime dependencies beyond Python stdlib + common third-party packages.
