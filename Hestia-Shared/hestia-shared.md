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

agenda = AgendaClient("hecate")                      # owner = module name
agenda.register_async(lambda: [                       # retry until Chronos answers, re-assert hourly
    job_rule("hecate.mail_watch", "Hecate: controlla nuove email", service="hecate",
             path="/api/gateway/mail/watch/run", recurrence="FREQ=MINUTELY;INTERVAL=15"),
    daily_window("athena.consolidation", "Athena: consolidamento", 3, 5),
])
agenda.is_open("athena.consolidation", fallback=lambda: 3 <= now.hour < 5)   # window gate
agenda.should_self_run("hecate.mail_watch", 900)     # job fallback guard (Chronos down / missing / stale)
agenda.retire(["scout.email_cycle"])                 # cancel own default rules no longer declared (POST /api/agenda/retire)
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
Registered today: Athena (rifletti su un tema), Argus (ricontrolla un servizio),
Hephaestus (sviluppo programmato).

Rules are idempotent by `key`; edits made by the user (`user_modified`) are never overwritten. A paused or
cancelled rule is a user decision: `is_open` → closed, `should_self_run` → False. Every call fails soft.
`retire(keys)` cancels only rules the module itself created (user items stay; marked `params.retired_by_module`).

## Mail subscriptions client (`hestia_common.mail_client`)

Modules get mail by **push** from Iris, never by polling (one watcher in Hecate → Iris dispatch):

```python
from hestia_common.mail_client import MailClient, mail_rule

mail = MailClient("scout")                           # owner = module name, calls go /route/iris/...
mail.subscribe_async(lambda: [mail_rule(              # retry until Iris answers, re-assert hourly
    "listings", "Annunci immobiliari", path="/api/scout/mail", domain="real_estate",
    senders=["portal.example"], subject_contains=None, labels=None, queries=None)])
mail.refresh()                                       # re-send now (settings behind the rules changed)
mail.subscribe(rules)                                # one synchronous call (full rule set; missing keys removed)
mail.backfill("listings", days=1)                    # "check now": Iris re-delivers matching mail of last days
```

Matching: `senders` = addresses or domains (`b.it` / `@b.it`), `subject_contains` = words, `labels` = Gmail labels;
filled groups AND-ed, values OR-ed; `queries` = Gmail searches evaluated by Hecate. Iris stores each match in
Archive under `domain` (`reference_id = mail:<domain>:<gmail id>`) and calls `POST <path> {owner, key, domain,
count, reference_ids, source}`. The module processes its unevaluated records there **and once at startup** (mail
that arrived while it was down). Fails soft (`[🔄] event=mail_subscribe_failed`).

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

## Oracle use cases (`hestia_common.oracle_usecases`)

A module that asks Oracle for text declares each kind of task as a **use case** `<module>.<task>` with a suggested
chain (`veloce`, `potente`, `codice`, `visione`); Marko picks chain, mode (interna/esterna) and thinking for all of them
in Oracle → Cervello → Modelli. The module never names a provider or a model (dossier
`docs/work/2026-10-19-oracle-a-blocchi`).

```python
from hestia_common.oracle_usecases import usecase, capabilities as llm_capabilities

LLM_USECASES = [usecase("scout.annunci", "Scout · lettura annunci", chain="veloce",
                        help="Estrae i dati degli annunci dalle mail.")]
payload["capabilities"].update(llm_capabilities(LLM_USECASES))   # Hub registration (re-sent by the keepalive)
# call: POST {HUB}/route/oracle/api/llm/generate  body {"prompt": ..., "use_case": "scout.annunci"}
```

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

**Personal settings shared by every module** (owner Themis, group «Personali», `settings_client.PERSONAL`):
`themis.personal.week_start` (monday/sunday) and `themis.personal.currency`. A module never declares its own copy:
`settings.follow_personal()` (or `follow({...})`) sends `follows` on register, Themis answers `shared` and pushes
it again on every change; `settings.get("themis.personal.week_start")` then works like an own key
(`week_start_index()` gives 0 = Monday … 6 = Sunday).

## Reminders (`hestia_common.reminders`)

One reminder model for every module; the schedule is a Chronos agenda job, delivery is Hermes.

```python
from hestia_common.reminders import reminder_settings, reminder_event
settings.declare([..., *reminder_settings("hercules", help="…")])   # <m>.reminder.enabled (off) + .max_per_week
hub.call("hermes", "POST", "api/events/ingest", body=reminder_event(
    module="hercules", domain="fitness", key="hercules.reminder", title="Allenamento", text="…",
    actions=[{"id": "skip", "label": "Salta oggi"}], page="allenamento"))
```

The body is a `service.action_required` event on domain `system` (where Hermes' owner subscription listens; the
module domain travels in the payload) with `target: owner`, `replaces: <key>` (one live notification per key) and
`_link` to the module page. Modules send at most one reminder a day and respect `max_per_week`.

## Plugin client (`hestia_common.plugin_client`) + WebUI SDK (`webui-sdk/`)

`<hxk-icon name size tone>`: same icon names and paths as the WebUI `hx-icon` (checked by `tools/governance/check_icons.py`); `tone` = success · warning · danger · info · accent · muted. Plugins draw no emoji.

A module with a UI ships it inside the module and advertises it to the clients (contract:
`docs/work/2026-10-17-client-plugins/SPEC.md` §4):

```python
from hestia_common.plugin_client import PluginClient, page, widget, quick_action

ui = PluginClient("scout", title="Scout", icon="home", color="amber", dist="/code/ui/dist")
ui.webui(entry="scout.js", api_prefix="/api/ui/",
         pages=[page("case", "Case", element="scout-listings", icon="home")],
         widgets=[widget("nuove", "Nuove case", element="scout-new-widget", sizes=["m", "l"], auto=True)],
         quick_actions=[quick_action("fetch", "Controlla email", "POST", "/api/ui/cycle", icon="refresh")])
app.include_router(ui.router())                       # GET /api/ui/manifest · GET /ui/<client>/<file>
registration["capabilities"].update(ui.capabilities(base_url))   # ui_manifest + ui_version
```

`PluginClient(..., kind="core")` marks a system module (WebUI shows its pages under *Sistema*; default `domain`).
`page(..., badge={"source": "/api/…", "field": "unread"})` adds a counter next to the sidebar entry (GET under
`api_prefix`, a number in `field`).

Validation at declare time: element names `<module>-…`, every path under `api_prefix`, known parents/sizes/param
types. Hub aggregates manifests into `/api/discovery/catalog` (client × type). The browser side is
`Hestia-Shared/webui-sdk/` (`@hestia/webui-sdk`: host API types, `HestiaElement`, shared Lit kit `hxk-*`, build
script) — see its `README.md`.
`hxk-icon` names match the WebUI icon set (2026-10-18: `pulse`, `host` added for the core module plugins;
2026-10-19: `wallet`, `upload`, `target`, `mail` for Iris «Email» and Plutus «Spese»).

## Tools: MCP client (`hestia_common.mcp_client`) + call rules (`hestia_common.tool_call`)

Every client reaches tools only through Hestia-MCP `/mcp` (through Hub):

```python
from hestia_common.mcp_client import MCPClient, as_command
mcp = MCPClient(HUB_API_URL, client="telegram")         # oracle | telegram | webui …
tools = mcp.list_tools()                                 # MCP tools; Hestia details in tool["_meta"]["hestia"]
cmd = as_command(tools[0])                               # old command shape (service, method, path, telegram_*…)
ok, payload = mcp.call("forge_tasks", {"limit": 5}, session_id=sid, notify_target=chat_id,
                       origin_client="webui")             # origin_client → X-Hestia-Client towards the module
```

`tool_call.build_request(tool, args, ctx)` is the one implementation of how a tool becomes a Hub request (path
`$x`/`{x}`, templates `$session_id` · `$chat_id`/`$owner` · `$arg.x`, the rest to query or JSON body; `ctx.access`
→ `X-Hestia-Access`, the access name of an external AI);
`tool_call.resolve` / `template_vars` / `is_write` are the pieces. Hestia-MCP uses it; Telegram reuses `resolve`
for `arg_picker` sources (data reads declared by a tool).

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

Effects include `chat.reply` (`live` | `queued`: Oracle offline, chat clients queue messages; fallback `live`).
State cached 15 s; Chronos down → `[🔄]` log and `FALLBACK_EFFECTS` (everything allowed, every notification
delivered), so each module still follows only its own agenda windows.

## Constraints

- No domain logic — pure library code.
- No service registration or Hub contracts.
- No runtime dependencies beyond Python stdlib + common third-party packages.
