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

## Daily recap piece (`hestia_common.recap`)

A module with something to say about the user's day serves one piece (contract: `docs/work/2026-10-20-recap-giornaliero/SPEC.md` §3.2):

```python
from hestia_common import recap
app.include_router(recap.recap_router("hercules", lambda day, nxt: recap.piece(
    "hercules", "Allenamento", icon="dumbbell", emoji="🏋️", order=30,
    done=[recap.item("Push day: 5 esercizi, 18 serie")], next=[...], note="")))
capabilities = {**recap.capabilities(), ...}       # recap_endpoint → /api/module/recap
```

`GET /api/module/recap?day=&next=` → the piece, or `{module, empty: true}` when there are no lines (also when the
builder raises: logged, never a 500; bad date → 400). Pass `today=lambda: svc.today()` so the default day is the module's
local day, not the container's. Plain facts only, never an LLM call; Athena writes the text.
`job_rule(..., flex={"earliest": "20:00", "latest": "23:30"})` makes a recurring job fire around the user's events.
`piece(..., actions=[{label, command}|{label, service, path, method?, body?}])` (max 2) adds buttons under the recap
message, even on an empty piece; Athena puts them in the Hermes event (e.g. Hygieia «Racconta la giornata»).

## Module skeleton (`hestia_common.module_kit`)

The common skeleton of the W5 modules (Hera, Kairos, Demeter, Lares, Calliope, Apollo, Aphrodite), so each one holds
only its own domain code. `ModuleKit(name, port=, api=, domain=, title=, store=, when_to_use=, manual=, tags=)` builds
the FastAPI app (CORS, `/health` with mirror state, log router, errors: `Invalid` → 422, `NotFound` → 404,
`StoreUnavailable` → 503), the Hub client `kit.hub` (`ok`/`call` through `/route`, `notify(event)` = Hermes ingest,
`llm(prompt, use_case=)` = Oracle `/api/llm/chat`, None on failure), the Archive mirror `kit.store`
(`Store`: LWW rows by cursor, `items/data/upsert/delete`, epoch reset), `kit.settings` (Themis) and `kit.caps`.
`kit.tools(list, prefix=)` mounts the MCP router and one REST path per tool (`{api}/tools/<name without prefix>`,
arguments coerced by the schema, errors as `{"error": …}`); `kit.finish()` mounts them **before** the module's own
`{api}/{id}/…` routes (so `tools/done` is never read as an id) plus the settings router. `agenda_rules(fn)`,
`on_warm(fn)` (after the first mirror load), `capabilities(fn)`; startup = Hub registration + keepalive, settings,
agenda rules, warm-up. `kit.webui(icon=, color=, description=, pages=, widgets=, quick_actions=)` declares the
module's WebUI plugin (`PluginClient`: entry `<name>.js`, `api_prefix` = `{api}/`, bundle folder `<NAME>_UI_DIST`,
default `/code/ui/dist`, built from `ui/` in the image), mounts `/api/ui/manifest` + `/ui/…` and adds `ui_manifest`/
`ui_version` to the Hub capabilities; `kit.ui` keeps the client. Tests use `FakeArchive` (store protocol, blobs, recorded Hermes/other calls).

## Device feeds (`hestia_common.feeds`)

Data from the owner's devices, pushed by Hecate to the modules that asked for it (dossier
`2026-10-24-tutto-brainstorm-cindy` W4). A module declares `caps.update(feeds.capabilities({"wearable.daily":
"/api/hercules/wearable"}))`; Hecate's `FeedPublisher(HUB).publish(kind, item)` discovers subscribers on the Hub
(cache 60 s; the first publish always reads the registry, also right after boot) and POSTs the item through the Hub → `{delivered, failed}`. Kinds: `wearable.daily`,
`phone.notification`, `phone.state`. A failure is logged `[🔄]`; the next sync or push carries the data again.

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

## Module signals (`hestia_common.signals_client`)

First layer of the reflection (`docs/work/2026-10-20-riflessione-a-livelli`): each domain module judges its own data
with deterministic rules and publishes short **signals** + **weekly metrics** to Archive `signals-store`; Athena
reads only those (links between areas, then details through `/api/module/context?topic=`).

```python
from hestia_common.signals_client import Signals, signal, metric, signals_rule, iso_week, last_weeks

signals = Signals("hercules", "fitness", evaluate=svc.signals)   # svc.signals() -> (signals, metrics)
signal("stall:panca", "Allenamento: panca ferma da 3 sedute", kind="trend", severity="attenzione", page="progressi")
metric("fitness.sessions", iso_week(day), 3, label="Allenamenti")
signals.changed()     # after a write: debounced re-evaluation in background (push, never poll)
signals.run()         # agenda job POST <api>/signals/run → evaluate + sync
rules.append(signals_rule("hercules", "Allenamento", path="/api/hercules/signals/run", tz=TZ))   # daily 17:30
```

`kind` = trend · streak · anomaly · goal · milestone; `severity` = info · attenzione · alta (ranks the topics).
`key` is stable inside the module (republishing updates the row); `sync` writes only what changed and retracts
signals no longer present; signals expire after `ttl_days` (7). Texts are Italian, short, and name the area
(«Allenamento», «Spese»), never the module. `SignalReader` (Athena) reads active signals and weekly series.
Fails soft (`[🔄] event=signals_sync_*_failed`).

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

## Voice (`hestia_common.voice_client`, `hestia_common.voice_usecases`)

Only Echo calls speech engines (dossier `docs/work/2026-10-20-modulo-voce`). A module declares its voice uses
(direction `ascolto` or `voce`, suggested chain) and calls Echo through the Hub; failures return `None` so the caller
keeps its own fallback.

```python
from hestia_common.voice_client import VoiceClient
from hestia_common.voice_usecases import usecase, capabilities as voice_capabilities

VOICE_USECASES = [usecase("telegram.vocale", "Telegram · vocali", direction="ascolto")]
payload["capabilities"].update(voice_capabilities(VOICE_USECASES))   # Hub registration
voice = VoiceClient(HUB_API_URL)
heard = voice.transcribe(audio, "audio/ogg", use_case="telegram.vocale",
                         keep={"kind": "recording", "message_id": "tg:1:2"})      # {text, ...} | None
spoken = voice.speak("Ciao", use_case="telegram.risposta", fmt="ogg_opus")      # {audio: bytes, ...} | None
voice.forget(notification_id="…")                                              # drop regenerable audio
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
`themis.personal.week_start` (monday/sunday), `themis.personal.currency`, `themis.personal.places` (Casa, Lavoro,
Palestra…; editor `places`, options from `hecate:/api/gateway/weather/places`) and `themis.personal.birth_date`
(`AAAA-MM-GG`, Chronos turns it into the owner's birthday among the special events). A module never declares its own copy:
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

Voice: `voice_setting("<m>", default)` declares `<m>.notifiche.voce` («Notifiche anche a voce»; each module picks its
default) and `reminder_event(..., voice=settings.get("<m>.notifiche.voce"))` sets `_voice`: Hermes then adds the
audio made by Echo to the same notification (Telegram voice message, WebUI «Ascolta»). The text never changes.

## Plugin client (`hestia_common.plugin_client`) + WebUI SDK (`webui-sdk/`)

`<hxk-icon name size tone>`: same icon names and paths as the WebUI `hx-icon` (checked by `tools/governance/check_icons.py`); `tone` = success · warning · danger · info · accent · muted. Plugins draw no emoji. Added 2026-10-20: `bookmark` (Oracle Memoria page).

A module with a UI ships it inside the module and advertises it to the clients (contract:
`docs/work/2026-10-17-client-plugins/SPEC.md` §4):

```python
from hestia_common.plugin_client import PluginClient, page, widget, quick_action, settings_panel

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

`settings_panels=[settings_panel("backup", "Backup", element="archive-backup-panel", icon="history")]` (2026-10-21)
adds a panel that clients show **inside the module's own settings** (WebUI *Impostazioni → Sistema → <module>*),
below its Themis settings; the element calls only the module's `api_prefix` like any plugin element.

## Encryption (`hestia_common.crypto`)

One format for every encrypted file Hestia writes (backup, later export files): passphrase → scrypt (N=2^16) →
AES-256-GCM in 1 MB chunks, header `HESTIA-ENC1` + salt + KDF params + nonce prefix; chunk counter in the nonce and
last-chunk flag in the authenticated data, so truncation, reordering and tampering fail with `DecryptError`.
`encrypt_stream(src, dst, passphrase)` / `decrypt_stream(...)` (file objects, constant memory),
`encrypt_bytes` / `decrypt_bytes`, `is_encrypted(head)`. Needs `cryptography`. A lost passphrase means the file
cannot be opened: nobody stores it except the user (`.env` + password manager).

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

## Display blocks (`hestia_common.display`)
Optional card next to a tool's data, so Telegram shows the result without the model (docs/work/2026-10-23-telegram-da-zero §6).
```python
from hestia_common.display import action, display, item, money
return {**data, "display": display("Spese · ottobre", lines=[f"Speso {money(812.4)}"],
                                   items=[item("Spesa", [money(320)], tone="warning")],
                                   actions=[action("Aggiungi spesa", "finance_add", style="primary")])}
```
`item(title, meta, url=, tone=)`, `action(label, tool, args, style=)` (≤ 6 drawn, missing args are asked),
`display(title, subtitle=, lines=, items=, actions=, footer=, tone=, image=, images=, files=)`, `strip(payload)` (used by
Hestia-MCP for non-Telegram clients), `money(value)` → «1.234,50 €». Plain Italian, no emoji, no ids, existing tool
names only. Contract: swagger `DisplayBlock`. `file(blob_id, name, mime)` (≤ 10 in `files`): a file kept in Archive
blobs (a generated document, an image); Telegram fetches it through Hub (`archive api/blobs/{id}/base64`) and sends
it under the card, as a photo when the mime is `image/*`, otherwise as a document (W5).

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

## Export and import (`hestia_common.transfer`)

One contract for «Esporta e importa» (dossier `docs/work/2026-10-20-import-export`): a module lists *sections* of its
own data; the client (WebUI Impostazioni → Esporta e importa, `tools/hestia_transfer.py`) builds one `.hestia` file and
imports it elsewhere with a mode — `append` (Aggiungi: new only), `merge` (Unisci, default: new + newer `updated_at`),
`replace` (Sostituisci: the file wins, target-only records deleted, never for a partial section). Every import can be a
dry run (the preview).

```python
from hestia_common.transfer import StoreSection, Section, Transfer

transfer = Transfer("hercules", hub, sections=[
    StoreSection("esercizi", "Esercizi", store, ["exercise"], icon="dumbbell"),
    StoreSection("sessioni", "Sessioni", store, ["session", "set"], item_kinds=["session"],   # sets travel with
                 depends_on=["esercizi", "schede"]),                                          # pulled when named
    StoreSection("foto", "Foto", store, ["photo"], file_fields=["original", "medium", "thumb"]),  # Archive blobs
])
app.include_router(transfer.router())       # /api/transfer/describe|items|export|import|files
caps.update(transfer.capabilities())        # Hub registration: capabilities.transfer
```

- `StoreSection` covers the module stores (`hercules-store` & co.); other data subclasses `Section`
  (`records`, `write`, `title`/`subtitle`, optional `check`, `same`, `refs`, `migrate`) — see Scout (listings),
  Oracle (memories), Chronos (agenda), Themis (settings, `sections=lambda: …` built per call).
- Never secrets, tokens, logs or runtime state: a section lists only what the user made. Settings travel only
  through Themis. Files only with `include_files` (or the section chosen by hand); `POST /api/transfer/files` stores a
  blob of the module and the import rewrites the ids (`files_map`).
- Versioning: file `format` and a `schema` per section; newer than this Hestia → refused with «aggiorna Hestia».

## Coach contract (`hestia_common.coach`)

A domain module becomes a coach of the weekly plan (Chronos) with the Hub tag `coach` and one router:
`CoachRouter(module, domain, label, needs=, fit=, placed=, review=).router` serves `GET /api/coach/needs?start=&end=`
(`{module, domain, label, state, needs, refused}`), `POST /api/coach/fit`, `POST /api/coach/placed`,
`GET /api/coach/review`. `need(id, title, **fields)` / `validate_need` give the canonical need (kind
block/slot/target, count still to do, per week|day, minutes/min_minutes, days, fixed_dates, time_of_day,
not_before/not_after, min_gap_days, not_same_day, with{tag, relation}, tags, priority must|should|could, reason,
link, value/unit/progress); unknown fields are refused. `CoachClient(module).done(need_id, at)` / `.skipped(...)` /
`.changed()` push events to `POST /route/chronos/api/agenda/coach/report` (fails soft, `[🔄] event=coach_report_failed`).
`week_bounds(day, week_start)` → `[start, end)`. Dossier `docs/work/2026-10-20-coach-di-ogni-tipo`.

## Weather client (`hestia_common.weather_client`)

`WeatherClient(hub_api_url).now(place)`, `.forecast(place, date_from, date_to, hourly=False)`, `.at([{id, place, at}])`
call Hecate through Hub (`/api/gateway/weather/*`); `is_rainy(day_or_hour)` and `day_summary(day)` give one shared
reading. Failures answer `{status: "unavailable"}`; never raises. Place = saved place name/id, a city, or empty = Casa.

## Constraints

- No domain logic — pure library code.
- No service registration or Hub contracts.
- No runtime dependencies beyond Python stdlib + common third-party packages.

## Wave 1 helpers (dossier `docs/work/2026-10-24-tutto-brainstorm-cindy`)
- `hestia_common.redact` (Cindy 19): `redact(text)` / `redact_obj(obj)` replace secrets and personal data (keys,
  tokens, passwords in assignments and URLs, emails, phone numbers, IBAN, card numbers, chat ids, home paths, private
  IPs) with `[segreto]`, `[email]`, … before text leaves the house (Argus → Oracle, Forge task prompts).
- `hestia_common.origin` (Cindy 6): `X-Hestia-Origin: <kind>[:<ref>]` + `X-Hestia-Origin-Label`; `headers()`,
  `parse(headers, client)` (no header: user client = `utente`, else `autonomo`), `prompt_line`, `blocks_write`
  (autonomo: only proposals/notifications/questions; routine: no deletes). `MCPClient.call(origin=…)` puts it in
  `hestia.origin`; `tool_call.build_request` turns `ctx["origin"]` into the header.
- `hestia_common.ui_blocks` (Cindy 9): ```` ```hestia-ui ```` blocks in answers (card, stat, table, list, chart,
  checklist, button; tones primary/success/warning/danger/info); `segments`, `to_text` (plain text for Telegram),
  `buttons`.
- `hestia_common.mcp_helpers.undo(tool, label="Annulla", **args)` (Cindy 13): what a write tool puts in its result as
  `"undo"`, so clients can show «Annulla» under «Ho fatto».
