# SPEC — Assistant activity state (presence: signals → combinable states → effects)

| | |
|---|---|
| **Version** | 2.1 |
| **Source** | User via external chat (Claude Code cloud session, project thread "Stato di attività dell'assistente") · 2026-10-10 |
| **Status** | Draft — waiting for user approval; implementation starts only after the central-settings work is finished |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).

User's words (summary, Italian original in the thread): Forge and chat share the same Claude usage limits, so
heavy work should run at certain hours (the agenda already allows that). Track a **general state of the
assistant**: when the user last interacted, whether Hestia is active, idle or in "deep sleep", always available
to the assistant itself (e.g. Athena). Decision on the card: deep sleep starts from **both** the agenda night
window **and** long inactivity; any interaction wakes it up.
v2.0 (user, same thread): the state must have **real effects on the system**; think of a person — awake, asleep,
but also tired, napping, eating — so **more states and hybrids** (e.g. working in Forge while answering the user);
SOLID: it must always be possible to **add new states** without changing the code that uses them.

---

## 1. Goal

One persistent, shared activity state that every module and client can read, so that heavy or autonomous
work (Forge with Claude, Metis training, Athena consolidation/thinking) runs when the user is away, and the
assistant itself knows when it last talked with the user.

## 2. Today (starting point)
- Oracle keeps `_LAST_USER_ACTIVITY` **in memory** (`Hestia-Oracle/app/main.py`, `GET /api/activity`), set only
  by chats that carry `notify_target`. Lost at every restart; Telegram commands and WebUI actions don't count.
- Athena polls it via Hub and runs thinking cycles only after `ATHENA_IDLE_SECONDS` (300 s) of inactivity.
- Everything else uses only agenda windows (`metis.training` 01–06, `athena.consolidation` 03–05,
  `forge.claude_nights`/`forge.claude_final`), regardless of whether the user is actually there.

## 3. Scope

### In
- Engine + persistence + API owned by **Chronos** (it owns the assistant's time and windows), data stored in
  **Archive** (only DB owner) so everything survives restarts.
- Three layers: **signals** (facts reported by modules) → **states** (data-defined, combinable) → **effects**
  (named policies consumers ask for). Consumers never test state names.
- Built-in states declared by modules; user can add/edit states from the settings panel.
- Interaction pings from Oracle (chat), Telegram (any command/message), WebUI (user actions, debounced).
- New agenda window `assistant.sleep` (default nightly, user-editable in the calendar).
- Event `assistant.state_changed` to Hermes on every change of the composite state.
- Consumers: Athena, Oracle, Forge, Metis, Hermes (notification level), clients.

### Out (later, if wanted)
- Free-form code/expressions in conditions (only the structured rules of 4.3).
- Provider/thinking handling for Claude in Oracle (other thread: "Claude Haiku in Oracle").

## 4. Design

### 4.1 Signals (facts) — reported, never interpreted by the reporter
| Signal | Source | Example |
|---|---|---|
| `user.idle_seconds`, `user.last_client` | pings (Oracle, Telegram, WebUI) | 7200, telegram |
| `agenda.window.<key>` open/closed | Chronos | `assistant.sleep` open |
| `activity.<key>` running, with `load` light/heavy and `resource` (gpu, claude_quota, cpu) | modules via `presence_client.activity_start/stop` | `forge.task` heavy/claude_quota, `metis.training` heavy/gpu, `athena.thinking` light/gpu, `hephaestus.deploy` heavy |
| `resource.claude_quota_left`, `resource.gpu_busy` | Hephaestus budget, Oracle | 0.15, true |
| `health.degraded_services` | Argus | 2 |
| `manual.<key>` | user command | `manual.dnd` until 18:00 |
Activities have a TTL (auto-expire if a module dies without `stop`), so a crash never leaves a stale state.

### 4.2 States — data, two kinds
- **Base** (exactly one at a time, like awake/asleep): picked by priority among those whose conditions match.
- **Overlay** (zero or more, combinable): added on top → hybrids such as *Sveglio · occupato in Forge*.

Two tiers (user, v2.1: some states are "key", like activity and inactivity):
- **Core** — always present, cannot be deleted or disabled; only thresholds, labels and effects are editable.
  They guarantee the system always has a valid base state: `awake`, `idle`, `dnd` (manual command).
- **Optional** — built-in or user-made; can be edited, disabled, deleted, or reset to the built-in definition.
  With every optional state off, Hestia still works on `awake`/`idle` alone.

Default definitions (proposal by Claude, v2.1; every number is a setting):
| Key | Tier | Kind | Label | When | Effects (only what differs from `awake`) |
|---|---|---|---|---|---|
| `awake` | core | base | Sveglio | interaction in the last 5 min | light **defer**, heavy **defer**, Claude **save** (user chats only), notify **all**, style normal |
| `idle` | core | base | In attesa | no interaction for 5 min | light **allow** |
| `nap` | optional | base | Pisolino | no interaction for 45 min, outside the night window | light allow, heavy **allow** only local (Claude **save**), notify **important** |
| `deep_sleep` | optional | base | Sonno profondo | `assistant.sleep` window open (01:00–07:00) **or** no interaction for 3 h | light allow, heavy allow, Claude **allow**, notify **urgent** (rest in a digest on wake) |
| `dnd` | core | base | Non disturbare | `/nondisturbare` (default 2 h, or until a time) — highest priority | light allow, heavy allow only local, notify **urgent** |
| `busy` | optional | overlay | Occupato in … | a heavy activity is running (label names it: Forge, addestramento) | other heavy work **defer** (one at a time); notice "sto lavorando in …, rispondo un po' più lento" |
| `eating` | optional | overlay | Sto mangiando | maintenance: deploy/restart, model loading, training holding the GPU | heavy **defer**; notice "mi sto aggiornando, la risposta può tardare" |
| `tired` | optional | overlay | Stanco | Claude quota < 25 % before the reset, or ≥ 2 services degraded | Claude **save**, Forge autonomous **defer**, style **brief** |
Precedence among bases: `dnd` > `awake` > `deep_sleep` > `nap` > `idle` (a chat at 03:00 wakes it up; when the
user stops, the window puts it back to deep sleep after `idle_after`). Overlays never change the base.
Interaction = chat, Telegram command, WebUI action (send, click, save). Page views don't count.

### 4.3 Definition format (open for extension, closed for modification)
```
key, kind (base|overlay), label, emoji, priority, owner (module|user)
conditions: [ {signal, op (< <= > >= == != in open), value}, … ]   all must match (AND); several
            condition groups = OR
effects:    { "<effect>": value, … }
```
A new state = a new definition (declared by a module at startup like settings/agenda rules, or created by the user
in the panel by picking signals and effects from lists). No consumer changes. Unknown signals → condition false.

### 4.4 Effects — what consumers ask for
| Effect | Values | Used by |
|---|---|---|
| `work.light` | allow / defer | Athena thinking, light agenda jobs |
| `work.heavy` | allow / defer | Forge autonomous tasks, Metis training, consolidation |
| `llm.claude` | allow / save / deny | Forge autonomous, Oracle provider choice (save = only user chats) |
| `notify.level` | all / important / urgent | Hermes (others held for a digest when the state ends) |
| `chat.style` | normal / brief | Oracle answer length |
| `chat.notice` | text template | Oracle/clients: "sto lavorando in Forge, la risposta può essere più lenta" |
Combination: the base state gives the starting values, overlays override by priority; for allow/defer the most
restrictive wins. `presence_client.effect("work.heavy")` returns value + which states decided it (for logs/UI).

### 4.5 Record and API (Chronos via Hub; Archive tables; swagger updated)
- Archive: `presence_signals` (live signals/activities), `presence_states` (definitions; built-ins re-asserted
  idempotently, user edits win), `presence_snapshot` (current composite + effects) + last 100 changes.
- `POST /api/presence/ping {client, kind}` · `POST /api/presence/activity {key, load, resource, ttl}` ·
  `DELETE /api/presence/activity/{key}` · `GET /api/presence` → `{base, overlays[], label ("Sveglio · occupato in
  Forge"), effects{}, since, last_interaction_at, idle_seconds}` · `GET|PUT|DELETE /api/presence/states[/{key}]` ·
  `POST|DELETE /api/presence/dnd` · `GET /api/presence/history`.
- Re-evaluation on every ping/activity change and on Chronos' existing agenda worker tick (no new loop).
- `hestia_common.presence_client`: `get()`, `ping()`, `activity()` (context manager), `effect(name, default)`.
  Chronos down → `[🔄]` log, documented safe defaults (light allow, heavy only inside its own window).

### 4.6 Who uses it
- **Oracle**: one short line in the system context, e.g. `Stato: Sveglio · occupato in Forge · ultima interazione
  2 h fa (Telegram)` (computed before the ping, so it can say "bentornato"); applies `chat.style`/`chat.notice`/
  `llm.claude`; tool `assistant_state` for details/history. `/api/activity` stays as a thin alias.
- **Athena**: `effect("work.light")` replaces `_user_idle_seconds`; state in its observation context; reports
  `athena.thinking` as an activity.
- **Forge**: autonomous tasks need `work.heavy` and `llm.claude` allowed, on top of the budget windows; reports
  `forge.task` and `hephaestus.deploy`. User-requested tasks unchanged.
- **Metis**: trainings need `work.heavy`; reports `metis.training`.
- **Hermes**: filters by `notify.level`; held notices go out as one digest when the level opens again.
- **Clients**: Telegram `/stato` and `/nondisturbare`; WebUI badge in the header + presence card and state
  editor in the settings panel (central-settings §3.7).

### 4.7 Settings (everything configurable — central registry, Chronos module, group "Presenza")
User requirement: the whole behaviour must be configurable from the central settings, so this work **starts only
after the central-settings implementation is finished** (`docs/work/2026-10-10-central-settings/`); no env-only
interim. Settings:
`chronos.presence.enabled` (bool, true) · `chronos.presence.idle_after` (duration, 5 min) ·
`chronos.presence.sleep_after` (duration, 3 h; 0 = only the window) · `chronos.presence.use_sleep_window`
(bool, true) · `chronos.presence.heavy_requires_sleep` (bool, true) · `chronos.presence.count_ui_actions`
(bool, true) · `chronos.presence.oracle_context_line` (bool, true) · `chronos.presence.dnd_default_duration`
(duration, 2 h); thresholds used by built-in states (`nap_after` 45 min, `sleep_after` 3 h,
`tired_quota` 25 %, `tired_degraded` 2) are settings too, and every state definition (conditions, effects, on/off) is editable in the
panel. The hours of the `assistant.sleep` window live in the agenda (default daily 01:00–07:00),
editable from the calendar and linked from the settings panel. Per-consumer switches (Athena/Forge/Metis "aspetta
il sonno profondo") are declared by each module in its own group.

## 5. Acceptance criteria
- Core states `awake`/`idle`/`dnd` cannot be deleted or disabled; optional ones can, and the system keeps working.
- Chat or command from Telegram/WebUI → base state `awake` everywhere within seconds; survives a Chronos/Oracle restart.
- No interaction for 5 min → `idle`; 45 min → `nap`; 3 h or sleep window opens → `deep_sleep`; event emitted.
- A Forge task running while the user chats → `Sveglio · occupato in Forge`, and Oracle mentions it when relevant.
- Athena thinks only with `work.light` allowed; Forge autonomous tasks and Metis trainings only with `work.heavy`.
- A new state added from the panel (or declared by a module) changes behaviour through its effects with no change
  to Athena/Forge/Metis/Oracle/Hermes code.
- Oracle's answer can refer to the last interaction (context line); `assistant_state` tool returns the state.
- `/stato` on Telegram and the WebUI badge show the same state.
- Every threshold/switch in 4.5 is changeable from the settings panel and applies live.
- Chronos down → modules log `[🔄]` and fall back as in 4.3; nothing stops.

## 6. Decisions
- v2.1 (user: "fammi una proposta tu"): defaults in §4.2 chosen by Claude; core vs optional tiers; Hermes digest
  of held notices is in v1; WebUI counts actions, not page views.
- No open points left; approval of the spec pending.
