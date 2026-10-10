# SPEC — Assistant activity state (presence: active / waiting / deep sleep)

| | |
|---|---|
| **Version** | 1.0 |
| **Source** | User via external chat (Claude Code cloud session, project thread "Stato di attività dell'assistente") · 2026-10-10 |
| **Status** | Draft — waiting for user approval; implementation starts only after the central-settings work is finished |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).

User's words (summary, Italian original in the thread): Forge and chat share the same Claude usage limits, so
heavy work should run at certain hours (the agenda already allows that). Track a **general state of the
assistant**: when the user last interacted, whether Hestia is active, idle or in "deep sleep", always available
to the assistant itself (e.g. Athena). Decision on the card: deep sleep starts from **both** the agenda night
window **and** long inactivity; any interaction wakes it up.

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
- State machine + persistence + API, owned by **Chronos** (it owns the assistant's time and windows), state
  stored in **Archive** (only DB owner) so it survives restarts.
- Interaction pings from Oracle (chat), Telegram (any command/message), WebUI (any user action, debounced).
- New agenda window `assistant.sleep` (default nightly, user-editable in the calendar).
- Event `assistant.state_changed` to Hermes on every transition.
- Consumers: Athena (replaces its own idle check), Oracle (one line of context + tool), Forge, Metis.
- Clients show it: Telegram `/stato`, WebUI badge (+ module card in the settings panel).
- Thresholds as settings in the central settings registry (see `docs/work/2026-10-10-central-settings/`).

### Out (later, if wanted)
- Hermes holding non-urgent notifications during deep sleep → morning digest.
- Provider/thinking handling for Claude in Oracle (other thread: "Claude Haiku in Oracle").

## 4. Design

### 4.1 States
| State | Meaning | Enters when | Allowed work |
|---|---|---|---|
| `active` | user is interacting | any interaction | only user work; background waits |
| `waiting` | user away for a short while | no interaction for `idle_after` (default 5 min) | Athena thinking, light jobs |
| `deep_sleep` | user away / night | `assistant.sleep` window opens **or** no interaction for `sleep_after` (default 3 h) | heavy work: Forge autonomous Claude tasks, Metis training, consolidation |
| `dnd` | manual "non disturbare" | user command, optional end time | like `deep_sleep` for work; only urgent notices |

- Any interaction → `active` (except `dnd`, which ends only by command, end time, or explicit user action).
- `deep_sleep` from the window ends at window close → `waiting` (not `active`: the user hasn't come back yet).
- Paused/cancelled `assistant.sleep` window = user decision: only inactivity can lead to deep sleep.

### 4.2 Record (Archive, single row `assistant_state`)
`state`, `since`, `reason` (`interaction` | `inactivity` | `sleep_window` | `manual`), `last_interaction_at`,
`last_interaction_client` (telegram | webui | oracle), `last_interaction_kind` (chat | command | ui),
`dnd_until`, `updated_at`. Small history (last 50 transitions) for the WebUI and Athena retrospective.

### 4.3 Chronos API (via Hub; swagger updated)
- `POST /api/presence/ping {client, kind}` — records an interaction; cheap, idempotent; callers debounce 60 s.
- `GET /api/presence` — `{state, since, reason, last_interaction_at, idle_seconds, next_change_hint}`.
- `POST /api/presence/dnd {until?}` · `DELETE /api/presence/dnd`.
- `GET /api/presence/history?limit=`.
- Transitions computed by Chronos' existing agenda worker tick (no new loop) + on ping.
- `hestia_common.presence_client`: `get()`, `ping()`, `allows(kind)` (`light` | `heavy`), with fallback when
  Chronos is down: `[🔄]` log, treated as `waiting` (light work yes, heavy work only inside its own window).

### 4.4 Who uses it
- **Oracle**: one short line in the system context, e.g. `Stato: in attesa · ultima interazione 2 h fa (Telegram)`
  (computed at chat start, before the ping — so the assistant can say "bentornato"); tool `assistant_state`
  for details/history. Keeps `/api/activity` as a thin alias for compatibility, then pings Chronos.
- **Athena**: `presence_client.allows("light")` replaces `_user_idle_seconds`; the state goes into its
  observation context; consolidation/skill curation require `deep_sleep` **and** their window.
- **Forge (Hephaestus)**: autonomous Claude tasks require `deep_sleep` in addition to the budget windows, so they
  don't eat the Claude limit while the user is chatting. User-requested tasks unchanged (run any time).
- **Metis**: non-user trainings start only in `deep_sleep` inside `metis.training`.
- **Clients**: Telegram `/stato` (state, since when, last interaction, what is running) and `/nondisturbare`;
  WebUI status badge in the header + presence card in the settings panel (central-settings §3.7).

### 4.5 Settings (everything configurable — central registry, Chronos module, group "Presenza")
User requirement: the whole behaviour must be configurable from the central settings, so this work **starts only
after the central-settings implementation is finished** (`docs/work/2026-10-10-central-settings/`); no env-only
interim. Settings:
`chronos.presence.enabled` (bool, true) · `chronos.presence.idle_after` (duration, 5 min) ·
`chronos.presence.sleep_after` (duration, 3 h; 0 = only the window) · `chronos.presence.use_sleep_window`
(bool, true) · `chronos.presence.heavy_requires_sleep` (bool, true) · `chronos.presence.count_ui_actions`
(bool, true) · `chronos.presence.oracle_context_line` (bool, true) · `chronos.presence.dnd_default_duration`
(duration, 8 h). The hours of the `assistant.sleep` window live in the agenda (default daily 01:00–07:00),
editable from the calendar and linked from the settings panel. Per-consumer switches (Athena/Forge/Metis "aspetta
il sonno profondo") are declared by each module in its own group.

## 5. Acceptance criteria
- Chat or command from Telegram/WebUI → state `active` everywhere within seconds; survives a Chronos/Oracle restart.
- No interaction for 5 min → `waiting`; 3 h or sleep window opens → `deep_sleep`; event `assistant.state_changed` emitted.
- Athena thinks only when not `active`; Forge autonomous Claude tasks and Metis trainings start only in `deep_sleep`.
- Oracle's answer can refer to the last interaction (context line); `assistant_state` tool returns the state.
- `/stato` on Telegram and the WebUI badge show the same state.
- Every threshold/switch in 4.5 is changeable from the settings panel and applies live.
- Chronos down → modules log `[🔄]` and fall back as in 4.3; nothing stops.

## 6. Open points (to confirm at approval)
- Defaults: `sleep_after` 3 h and sleep window 01–07?
- Should WebUI page views count as interaction, or only actions (send, click a command)? Proposal: actions only.
