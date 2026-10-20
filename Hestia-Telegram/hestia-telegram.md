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

### Command Rendering (tools from Hestia-MCP)
- Loads the command catalog from Hestia's one MCP server (`tools/list` as client `telegram`, through Hub) —
  `services/registry.py` with `hestia_common.mcp_client`; tool names with dots become `_` commands.
- Runs a command with `tools/call` (session id + chat id as notify target); `arg_picker` sources (data reads a tool
  declares) use the shared template rules (`hestia_common.tool_call`) and a plain Hub route.
- Supports `oracle_natural` response mode: command payloads must be formatted by Oracle for user display.
- `/avvisi_recenti` must always be user-formatted text, never raw JSON in chat output.

### Access control (fail closed)
- `ALLOWED_USER_ID` (one id or comma-separated list) is **required**: when unset the bot answers nobody and tells
  the sender their numeric id. Previously an unset value let anyone use the bot — unacceptable now that it can
  command Forge to change Hestia's code.
- Checked on every message handler and, centrally, on every button callback (`telegram_runtime._allowed`).

### Owner notification alias
- Services notify the user, not a chat: Hermes, Chronos and Argus send `target: "owner"` (no config). Telegram,
  as the client, decides the chat: the first `ALLOWED_USER_ID` (`core.resolve_notify_target`). The chat id lives
  only in `Hestia-Telegram/app/.env`. Single-user for now; more recipients would be the client's job.

### OAuth Paste Shortcut
- If a message contains a URL with `/api/gateway/auth/callback/<provider>?code=...` (the page a phone
  cannot open at the end of Google consent), Telegram forwards it straight to Hecate
  (`POST /api/gateway/auth/complete/<provider>` via Hub) and replies with the outcome.
- No LLM in the loop: deterministic even with small local models. Module: `telegram_bot/services/oauth_paste.py`.

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
- Leaked markdown patterns (`**bold**`, `-`/`*` bullets) in HTML text are converted to HTML equivalents **without** escaping existing HTML tags (markdown conversion uses targeted regex, never the full `format_for_telegram()` path that would turn `<a href>` into `&lt;a href&gt;`).
- Outbound HTML is normalized to Telegram-supported tags before send (for example `<em>` → `<i>`, `<strong>` → `<b>`) to avoid parse errors.
- If Telegram rejects an HTML fragment (`can't parse entities`), delivery retries automatically as plain text for that message part.
- If output contains property blocks separated by blank lines and any block has a link, each block becomes its own Telegram message (enables Telegram native link preview).
- Raw JSON is allowed only as technical fallback when no formatter path exists.

### Reply rendering (Claude-like, `services/reply_renderer.py`)
- One Oracle stream → **one answer message**: the status message is reused (live status → optional live steps →
  streamed tokens → final). Never sent twice; split only above 4000 chars.
- Reasoning = `<blockquote expandable>` above the answer (open when *Dettagliato*).
- System notices (Oracle `notice` packets) are rendered **distinct from the answer** (emoji + italic, or bold
  title + detail in *rich* style) under the answer, in a separate message, only important ones, or hidden.
- Stream consumption: `chat_service.consume_oracle_stream()` (shared by text and file messages).

### Settings (`services/chat_settings.py` — single schema)
`/settings` opens one panel edited in place (menu ↔ options with ✓, Indietro, Ripristina, Chiudi). Adding a
`Setting` to `SETTINGS` adds it to the panel automatically.

| Key | Options (default **bold**) |
|---|---|
| `tone` | **warm** · neutral · direct · formal — central setting `oracle.chat.tone` (Themis, layer client `telegram`); Oracle applies it |
| `mode` | **auto** · quick · thinking · cot (Rapida, Pensata, CoT) — central setting `oracle.chat.mode` (layer client `telegram`); Oracle uses it when no mode is sent |
| `thinking_display` | hidden · **compact** · detailed · live |
| `stream_answer` | **on** · off |
| `split_mode` | **single** · paragraphs |
| `notice_mode` | **inline** · separate · important · hidden |
| `notice_style` | **compact** · rich |
| `notice_memory` / `notice_actions` / `notice_subscriptions` / `notice_other` | **on** · off (errors always shown unless hidden) |
| `custom_prompt` | free text, central setting `oracle.chat.instructions` (layer client `telegram`); `-` removes it |

Nothing from this table is forwarded to Oracle: `build_client_instructions_for_chat` sends only the Telegram
presentation contract, and Oracle requests carry `"client": "telegram"` so Oracle adds tone and instructions
itself. `tone`/`custom_prompt` are read and written through `services/personal_settings.py` (Themis via Hub,
20 s cache, local value if Themis is down); the other keys stay in the local settings file. `/thinking <mode>` is a shortcut; `/retry` regenerates the last answer.

### Signal cards (legacy, non-stream paths only)
The notification-compile path (`/api/subscriptions/compile` response `signals`) still uses signal cards:
central settings `telegram.signals.style` (`minimal`|`compact`|`rich`) and per family
`telegram.signals.style_memory|subscription|action|other` (empty = general style).

### Module settings (Themis, `app/telegram_settings.py`)
Tunables are central settings (`SettingsClient("telegram")`, all `apply=live`, read at use time). Env keeps only
secrets/infrastructure: `TELEGRAM_BOT_TOKEN`, `ALLOWED_USER_ID`, `HUB_API_URL`, `TELEGRAM_BASE_URL`,
`TELEGRAM_CONTROL_PORT`, `FEEDBACK_ARCHIVE_URL`, `WEBUI_API_URL`, `WEBUI_PUBLIC_URL`, `WEBUI_ADMIN_SECRET`.
Separate from the personal chat settings (`oracle.chat.*`, see Settings above).

| Key | Default | Was env |
|---|---|---|
| `telegram.alerts.buffer_window` | 0.8 s | `ALERT_BUFFER_WINDOW_SECONDS` |
| `telegram.feedback.prompt_rate` | 0.15 | `TELEGRAM_FEEDBACK_PROMPT_RATE` |
| `telegram.feedback.snooze_days` | 7 | `FEEDBACK_SNOOZE_DEFAULT_DAYS` |
| `telegram.commands.hidden_services` | `[]` | `TELEGRAM_HIDDEN_COMMAND_SERVICES` |
| `telegram.commands.hidden` | `notifica_attiva, notifica_disattiva, notifiche_attive` | `TELEGRAM_HIDDEN_DYNAMIC_COMMANDS` |
| `telegram.chat.locale` | `it` | `TELEGRAM_LOCALE` |
| `telegram.chat.client_instructions` | Telegram style/format contract | `TELEGRAM_ORACLE_CLIENT_INSTRUCTIONS` |
| `telegram.oracle.stream_timeout` | 600 s | `TELEGRAM_ORACLE_STREAM_TIMEOUT` |
| `telegram.signals.style` / `.style_<family>` | `minimal` / empty | `TELEGRAM_SIGNAL_STYLE`, `TELEGRAM_SIGNAL_STYLE_BY_FAMILY` |
| `telegram.log.level` | `LOG_LEVEL` at boot | — |

`settings.start()` runs at boot (background register, hourly re-assert); the control server answers
`GET /api/settings/effective` and `POST /api/settings/reload` so Themis pushes changes at once.

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
| `/snooze_feedback` | Suspend feedback prompts (`telegram.feedback.snooze_days`, default 7) |
| `/feedback good` / `/feedback bad` | Rate last Oracle response |

### Feedback Collection
- Inline 👍/👎 buttons appear after eligible chat responses (setting `telegram.feedback.prompt_rate`, default 0.15).
- Never on greetings, trivial messages, or during snooze periods.
- Feedback is submitted to Archive's `feedback_submit` MCP tool via Hub routing.
- On button press, the feedback prompt message is **deleted from chat** immediately — no lingering acknowledgment text.
- Snooze via `/snooze_feedback` — writes a durable preference to Archive; auto-expires after `telegram.feedback.snooze_days` (default 7).

### Confirm cards from the chat (2026-10-18, client plugins)
- An Oracle `question` with `question_id` (no approval `id`), e.g. a Themis proposal made in this chat ("crea una
  dashboard…", "cambia l'impostazione…"), becomes a message with two buttons; the answer goes to Oracle
  `POST /api/chat/question-answer` (`client: telegram`), which routes the module's action. The Hermes copy of such a
  proposal is quiet, so the card in the chat is where you answer.

---

## API Endpoints

Telegram is event-driven and also exposes an internal control endpoint for Hermes dispatch.

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/notify` | Hermes notification client (`capabilities.notify_endpoint`): `notification` → message + buttons `ntf:<id>:<action>` (`silent` ones skipped, `ref` = `chat:message_id` returned), `update` → buttons replaced by "✓ Vista su WebUI" / "✅ Approva · da WebUI", `retract` → message deleted; repeat chains: `repeat.text` shown in italics («↻ Saltato 2 volte»), `update superseded` → old message deleted (over 48 h: «↻ Sostituito»), button on a replaced one → «Sostituita da un promemoria più recente» |
| `POST` | `/api/dispatch/send` | Legacy (no longer called by Hermes): dispatch payloads via Hub routing. `target` = chat id, or `owner` / empty = first `ALLOWED_USER_ID` (the only place the owner's chat id lives) |
| `GET` | `/health` | Service health |
| `GET` | `/api/settings/effective` | Themis: values Telegram is using now (`hestia_common.settings_client` contract) |
| `POST` | `/api/settings/reload` | Themis: push changed values (`{values, shared}`) or re-fetch them (empty body) |

---

### Notifications (Hermes global notifications, `services/notifications.py`)

- Button `ntf:<notification_id>:<action_id>` → Hermes `/api/notifications/{id}/answer` (first answer wins;
  409 → "Già gestita da WebUI" and the buttons are replaced). Legacy command actions are run here and the
  outcome is reported to Hermes.
- Any message of the allowed user in the chat marks the notifications shown here as seen
  (`/api/notifications/seen-all` with `delivered_to=telegram`) — read state is global across clients.

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

## WebUI token commands

`/webui_token`, `/webui_revoke`, `/webui_status` call the WebUI admin API directly (`WEBUI_API_URL`, security
exception: not via Hub). When `WEBUI_ADMIN_SECRET` is set (same value as the webui container) it is sent as
`X-WebUI-Admin-Secret`. No local fallback: if the WebUI is down the user gets an error (a locally minted token was
never accepted and was stored in clear text in Archive memory). The message is HTML with the real lifetime.

## Assistant presence

Every allowed command, file and chat message pings Chronos presence (`telegram`, debounced 60 s) through `telegram_bot/services/presence.py`. `/stato`, `/nondisturbare`, `/disturbami` come from Chronos MCP tools (group sistema).

## Oracle offline (chat queue)

SPEC `docs/work/2026-10-19-oracle-offline`, code `telegram_bot/services/chat_queue.py`. A text message Oracle does not
accept (connection refused, timeout before the answer, HTTP 502/503/504) is stored in Archive (`/api/chat-queue`,
client `telegram`, the message id as `client_ref`) and the reply is «⏳ Non posso rispondere adesso: messaggio in coda,
ti rispondo appena possibile.» A file while offline gets «rimandamelo più tardi» (not queued). Archive down too → the
usual error. `POST /api/chat-queue/drain` (capability `chat_queue_drain`, called by Chronos when Oracle is back) and
startup answer the queue oldest first, each as a reply to the original message, with a note to Oracle about when it
was written; one header line when a chat had more than one; the first Oracle failure stops the drain. The Hermes
notice «Non disponibile» and `/stato` show the state.
