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
agenda.plan(key, title, start_at, parent="user:abc")  # linked: parent cancelled → this cancelled
agenda.fail(key, "tests red")                         # work failed → item failed, parent marked
agenda.link(key, parent)                              # (re)link later; parent=None unlinks
agenda.agenda(days=7, owner=None)                    # see every module's plans
```

Wizard templates (what the user can create for your module from the WebUI calendar):

```python
from hestia_common.agenda_client import template
agenda.register_async(rules, templates=lambda: [template(
    "recheck", "Ricontrolla un servizio", service="argus", path="/api/argus/recheck/{service}",
    type="task", types=["task", "job"], icon="refresh",
    fields={"service": {"type": "string", "label": "Servizio", "in": "path"}}, required=["service"],
    title="Argus: ricontrolla {service}")])
```
Registered today: Scout (controllo email extra), Athena (rifletti su un tema), Argus (ricontrolla un servizio),
Hephaestus (sviluppo programmato).

Rules are idempotent by `key`; edits made by the user (`user_modified`) are never overwritten. A paused or
cancelled rule is a user decision: `is_open` → closed, `should_self_run` → False. Every call fails soft.

## Response packets (standard for every client)

Oracle streams NDJSON; every client (Telegram, WebUI, future apps/voice) renders the same packets.
Emitters: `Hestia-Oracle/app/core/services/stream_emitter.py`.

| `type` | Fields | Client rendering |
|---|---|---|
| `status` | `content` | transient progress line (replaced, never kept) |
| `thinking` | `action` (reasoning/tool_call/tool_result), `content`, `tool`, `turn`, `metadata` | collapsible reasoning box |
| `token` | `text` | streamed answer |
| `final` | `reply`, `session_id`, `domain` | the answer (exactly once) |
| `notice` | `kind`, `level`, `icon`, `emoji`, `title`, `detail`, `data` | **system message**: visually distinct from chat (icon/pill), filtered by user settings |
| `question` | `question_id`, `header`, `prompt`, `kind`, `options`, `required`, `timeout_sec` | interactive card |
| `needs_input` | `missing_fields` | ask for missing data |
| `signal` | `event`, `content`, `data` | legacy machine event (audit); clients show its `notice` twin instead |

`notice.kind` → `memory.saved · memory.removed · memory.updated · subscription.added|changed|removed ·
action.done · action.failed · action.needs_approval · agenda.planned · forge.task · document.saved · info ·
warning · error`. `level` = `info|success|warning|error`; `icon` = WebUI `hx-icon` name; `emoji` for text
clients. Notices may arrive **after** `final` (background memory) — attach them to the last answer.
Add a kind: one line in `NOTICE_KINDS` (+ `_SIGNAL_TO_NOTICE` if it mirrors a signal); clients need no change.

## Constraints

- No domain logic — pure library code.
- No service registration or Hub contracts.
- No runtime dependencies beyond Python stdlib + common third-party packages.
