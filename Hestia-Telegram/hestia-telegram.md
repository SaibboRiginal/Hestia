# Hestia-Telegram 💬

**Role:** User Interface — Telegram Relay + Command Renderer
**Node:** Raspberry Pi (Always-On)
**Stack:** Python · pyTelegramBotAPI · requests · Docker

---

## Responsibility

Primary human-facing interface for chat, commands, and proactive notifications.

Telegram must:
- Relay user chat messages to Oracle.
- Render command outputs discovered from Hub.
- Deliver Hermes proactive alerts.
- Enforce user-facing formatting rules consistently across chat, commands, and alerts.

---

## Core Features

### Message Relay
- Receives messages from Telegram user.
- Forwards to Oracle (`POST /api/chat`) with session-aware context.
- Streams status and renders final Oracle reply.

### Command Rendering (Hub-discovered)
- Loads command catalog dynamically via Hub discovery.
- Executes commands by routing through Hub.
- Supports `oracle_natural` response mode: command payloads must be formatted by Oracle for user display.
- `/avvisi_recenti` must always be user-formatted text, never raw JSON in chat output.

### Session Clear Command
- The user can send `/clear` to reset active Oracle session.
- Telegram confirms with inline buttons and supports cancel.
- On confirm, history and local session settings are reset.

### Delivery Formatting Contract (Global)
- Applies to chat replies, proactive alerts, and command outputs.
- Known commands (`scout_listings`, `avvisi_recenti`, `notifiche_attive`) use **dedicated formatters** — not Oracle. Oracle is only used for unknown command payloads.
- Never show "n/d" for missing data — omit the field entirely.
- Minimal emojis: one per section header, none on detail lines.
- HTML parse mode is the default render mode for user-facing rich content.
- No markdown bold (`**`) inside HTML output — use `<b>` tags only.
- Outbound HTML is normalized to Telegram-supported tags before send (for example `<em>` → `<i>`, `<strong>` → `<b>`) to avoid parse errors.
- If Telegram rejects an HTML fragment (`can't parse entities`), delivery retries automatically as plain text for that message part.
- If output contains property blocks separated by blank lines and any block has a link, each block becomes its own Telegram message (enables Telegram native link preview).
- Raw JSON is allowed only as technical fallback when no formatter path exists.

### Signal Rendering Policy (Client-Specific, Standardized)
- Signal payloads remain canonical and information-rich in the backend for audit and cross-client reuse.
- Telegram applies a client-side policy to choose what to display: `minimal`, `compact`, or `rich`.
- Default behavior is minimal one-line outcome cards for operational events.
- Optional per-family overrides are supported (`memory`, `subscription`, `action`, `other`) through env configuration.
- Unknown/generic signal content is suppressed in minimal mode to avoid chat noise.

Environment knobs:
- `TELEGRAM_SIGNAL_STYLE=minimal|compact|rich`
- `TELEGRAM_SIGNAL_STYLE_BY_FAMILY=action=compact,memory=minimal,subscription=minimal`

### Input Collection Contract (Global)
- Commands must not rely on technical `key=value` syntax as primary UX.
- When a command requires missing input, Telegram asks for it via the next user message.
- Every text-input workflow must expose an inline `Annulla` action to stop the flow immediately.
- Rule applies to local and dynamic commands (for example: `/set`, notification creation, and any future command requiring manual text input).

### Commands (Examples)

| Command | Action |
|---|---|
| `/clear` | Clear active Oracle session |
| `/avvisi_recenti` | Show recent alerts in natural formatted text |
| `/notifiche_attive` | Show active subscriptions in readable format |
| `/scout_listings` | Show property list with HTML links |
| `/snooze_feedback` | Suspend feedback prompts for 7 days |
| `/feedback good` / `/feedback bad` | Rate last Oracle response |

### Feedback Collection
- Inline 👍/👎 buttons appear after eligible chat responses (configurable rate, default ~15%).
- Never on greetings, trivial messages, or during snooze periods.
- Feedback is submitted to Archive's `feedback_submit` MCP tool via Hub routing.
- Snooze via `/snooze_feedback` — writes a durable preference to Archive; auto-expires after 7 days.

---

## API Endpoints

Telegram is event-driven and also exposes an internal control endpoint for Hermes dispatch.

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/dispatch/send` | Receive dispatch payloads from Hermes via Hub routing |
| `GET` | `/health` | Service health |

---

## Constraints

- Domain/business decisions remain in core/module services (Oracle/Hermes/Archive/Scout).
- Telegram does not evaluate domain events or matching logic.
- Telegram may perform presentation-layer formatting and message splitting.
- Telegram does not access database directly.


## Documentation Synchronization (Required)

1. Any behavior, command, or contract change must update this service document in the same change set.
2. If API routes, methods, schemas, or Hub-routed command contracts change, update Hestia-Swagger/swagger.yml in the same change.
3. Ensure command metadata exposed to Hub discovery is complete and accurate (service, method, path, arguments/templates) so Oracle and clients can execute deterministically.
4. Keep canonical payloads rich at source; client-facing detail level is controlled by client rendering policy (minimal/compact/rich), not by deleting upstream semantics.
