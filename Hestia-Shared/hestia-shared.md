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

## Settings client (`hestia_common.settings_client`)

Every tunable knob is a setting declared to **Themis** (never a new env var; env = secrets + infrastructure):

```python
from hestia_common.settings_client import SettingsClient, setting, preset

settings = SettingsClient("argus")
settings.declare([
    setting("argus.poll.interval", "Intervallo controlli", "int", 30, group="Controlli",
            help="Ogni quanti secondi controllo i moduli.", min=5, max=600, unit="s"),   # apply="live" (default)
    setting("argus.workers", "Worker", "int", 2, apply="restart", advanced=True),
    setting("argus.remediate.dry_run", "Solo simulazione", "bool", True,
            depends_on={"key": "argus.remediate.enabled", "equals": True}),
], presets=[preset("calmo", "Tranquillo", group="Controlli", values={"argus.poll.interval": 120})])
settings.declare_log_level()                 # standard <module>.log.level (live, replaces LOG_LEVEL)
app.include_router(settings.router())        # GET /api/settings/effective · POST /api/settings/reload
settings.start()                             # in the startup hook: first load + hourly re-assert
settings.get("argus.poll.interval")          # where you used os.getenv
settings.on_change(lambda changed: ...)      # live values changed (also fired on first load)
```

Themis down → defaults + `[🔄]` log, retried in background. `apply="restart"` values loaded at startup stay
effective until restart (Themis shows "riavvio necessario"). `oracle="none"` for safety switches the
assistant must not even propose.
`options_source` (a GET path on the owning module, `{other.key}` placeholders) gives dynamic choices, resolved by
Themis (`/api/settings/key/{key}/options`) so every client gets the same list. `row` + `column` are a table hint:
clients show the settings of a group as a grid (Oracle: use case × fornitore / modello).
`settings.put(key, value)` persists a change the **user** made through the module's own command/UI.

## Presence client (`hestia_common.presence_client`)

Assistant activity state kept by Chronos (see `Hestia-Chronos/hestia-chronos.md`). Report facts, ask effects —
never test a state name.

```python
presence = PresenceClient("hephaestus")
presence.ping("telegram", "command")                 # user interaction (debounced 60 s, background)
presence.effect("work.heavy")                         # allow | local | defer
presence.allows("work.heavy", "allow", "local")
with presence.activity("forge.task", label="Forge", load="heavy", resource="claude_quota"): ...
presence.signal("resource.claude_quota_left", 12, ttl_seconds=3600)
presence.context_line()                               # one line for a model's context
```

State cached 15 s; Chronos down → `[🔄]` log and `FALLBACK_EFFECTS` (everything allowed, every notification
delivered), so each module still follows only its own agenda windows.

## Constraints

- No domain logic — pure library code.
- No service registration or Hub contracts.
- No runtime dependencies beyond Python stdlib + common third-party packages.
