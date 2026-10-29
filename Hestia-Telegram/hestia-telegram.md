# Hestia-Telegram

**Role:** User Interface — Telegram client (chat, every assistant function, notifications)
**Node:** Raspberry Pi (Always-On)
**Stack:** Python · pyTelegramBotAPI · requests · Docker
**Design dossier:** `docs/work/2026-10-23-telegram-da-zero` (SPEC v3.2, section 10 = as built)

---

## Responsibility

The human-facing client on Telegram. It must:
- relay chat messages to Oracle (streamed, one answer message);
- make **every assistant function** usable without typing commands: all module tools (MCP catalog) through menus
  and guided actions, plus a few local actions;
- show results without the model (module `display` blocks or a generic renderer);
- deliver Hermes notifications and answer their buttons;
- keep one calm visual grammar everywhere (below).

Telegram never decides domain things: modules own their tools and data, Oracle is the brain, Hermes sends.

---

## Visual grammar (`telegram_bot/ui.py`)

- **Markers (hybrid)**: tone dots 🔴🟠🟢🔵 only on a title line (errors, warnings, outcomes, notifications);
  one emoji per area only on area buttons and result titles; 👍 / 👎 for the vote. No other emoji in texts or buttons
  (tests scan the strings; module titles are checked by `tools/governance/check_telegram.py`).
- **Card** = bold title (optional crumbs `Aree › Spese`), italic subtitle, `•` lines, footer. HTML parse mode only.
- **Buttons**: labels ≤ 24 characters cut on a word, two per row (longer than 18 alone); Telegram styles
  `primary` / `success` / `danger` (Conferma, Elimina), disabled buttons for states («Fatto · da WebUI»), copy buttons.
- **Errors** say what failed in plain Italian (`ui.error`), never an exception, id or module name.

## Navigation (configuration, not code)

- **Bottom keyboard** (always there): Oggi · Aree · Notifiche · Impostazioni. Tapping a key during a guided action
  leaves it.
- **`/` menu** (8): `oggi`, `aree`, `notifiche`, `impostazioni`, `nuova`, `voce`, `stato`, `aiuto`. Old names keep
  working (`ALIASES`: `/start`, `/clear`, `/settings`, `/comandi`…); any tool name typed as `/name k=v free text`
  starts that action with the values given.
- **Cards**: Home (greeting, notifications to see), Oggi (agenda + weather + actions), Aree (11 areas + «Usate
  spesso»), area card (summary tool + primary actions + «Tutte le azioni» by section, «Avanzate» last). One live
  navigation message edited in place; an old message's buttons answer «Questo menu è vecchio» and open a fresh one.
- **Where the menu comes from** (`telegram_bot/menu/`), later wins:
  1. `defaults.py` — data only: keyboard, doors, commands, aliases, areas (key, label, emoji, order, aliases),
     `SERVICE_AREAS`, «Oggi» content;
  2. module hints on each tool: `telegram_group` (area), `telegram: {section, primary, summary, label}`;
  3. Themis setting **`telegram.menu.layout`** (system scope, same shape as the defaults, every part optional):
     edited from Telegram (Impostazioni › Menu: rename, emoji, order, move an action, pin primaries, new area, reset),
     from the WebUI settings panel, or proposed by the assistant (the user confirms).
  A tool that nothing mentions still appears (area from module group, else module, else «Altro»); only section
  `interno` is hidden. Reachability: primary actions ≤ 2 taps, every action ≤ 5 taps plus paging.
- **Catalog** (`catalog.py`): Hestia-MCP `tools/list` as client `telegram` through Hub (input schema + hints),
  refreshed on Hub `registry-changed`; local actions from `local_actions.py`.

## Guided actions (`telegram_bot/actions.py`, `inputs.py`)

- Fields come from the tool's JSON schema: label in words, help, «Es.» example, «Passo i di n»; enum/boolean/
  `arg_picker` → buttons; numbers, dates («domani», «25/10»), times («18.30»), amounts («12,50 €») parsed in Italian;
  a date alone for a date-time asks the time. Indietro · Salta · Annulla on every step.
- Writes get a **confirmation card** (Conferma); destructive tools get «Elimina» in red and «Non si può annullare».
- Result: «Un attimo…» then the result card with the module's next-step buttons, «Cambia», «‹ Area», «Di nuovo».
  Images come as photo / album, exports as a document.
- A file sent while an action waits for one is the answer (Archive blob when the schema asks `blob_id`).
- Writing a sentence during an action asks «Vuoi uscire da X?»; a spoken answer works like a typed one.
- Flows, pending confirmations and short callback ids are persisted in `data/telegram_ui.json`
  (`TELEGRAM_UI_STATE_FILE`), so buttons keep working after a restart.

## Results without the model (`render.py`)

A tool result is drawn by Telegram, never sent to Oracle for formatting:
- **`display` block** (`hestia_common.display`) when the module returns one: title, subtitle, lines, items (with link
  and tone), up to 6 next-step actions (tool + preset args + style), images. Today: Hercules (summary, next
  workout), Chronos (agenda, agenda today), Hygieia (today, overview), Plutus (summary, search, add), Wardrobe
  (summary, suggest), Scout (listings, stats). Hestia-MCP strips `display` for every other client.
- otherwise a **generic renderer**: lists → `•` lines (title + 2–3 meta, no ids, no «n/d»), money/date fields in
  Italian, errors red, plain text as is.

## Local actions (`local_actions.py`)

Actions that belong to the client itself, declared like tools (`T(name, title, description, …)`, checked by
`check_command_contracts`): `nuova` (new conversation: Oracle `DELETE /api/chat/{session}`), `voce` / `voce_on` /
`voce_off`, `aiuto`, `webui_token` / `webui_status` / `webui_revoke`, `documenti` / `documento_fissa` /
`documento_elimina`, `nuovo_promemoria` / `nuova_attivita` (Archive calendar items), `nuovo_avviso` (Oracle
subscription compile), `pausa_voto`.

## Chat (`services/chat_service.py`, `reply_renderer.py`)

- One Oracle stream → **one answer message** (status → steps «• Uso: <azione>» → streamed tokens → final); split
  only above 4000 characters. Reasoning in an expandable quote «Ragionamento · N passi».
- Notices from Oracle are italic lines inside the answer (🔴 only for errors), per the notice setting.
- **Reply or quote = context**: replying to (or quoting part of) any message sends
  `quoted: {text, from: assistant|user|notification, at, ref}` with `/api/chat`; Oracle uses it for that turn only.
- Under an answer: Ascolta · 👍 · 👎 on one row (vote shown at `telegram.feedback.prompt_rate`).
- Requests carry `"client": "telegram"`; Oracle adds tone and personal instructions itself.

### Voice (`services/voice_service.py`, dossier `docs/work/2026-10-20-modulo-voce`)
- A voice note is transcribed by Echo (use `telegram.vocale`) and shown as «*testo*», then handled like the same
  sentence typed (or as the answer of an open guided action). Echo down → «Non riesco ad ascoltare il vocale adesso,
  puoi scrivermelo?» (`[🔄]`).
- «Ascolta» (`voice:play`): Echo reads the reply (use `telegram.risposta`), kept so a second tap does not regenerate.
- `/voce` toggles spoken answers to voice notes (session setting `voice_live`); the written reply always stays.
- Hermes `update` with `voice.audio_b64` → voice message replying to the notification.

### Settings (`services/chat_settings.py`)
Impostazioni opens one panel edited in place: tone (`oracle.chat.tone`), mode (`oracle.chat.mode`), reasoning
display, notices, voice, personal instructions (`oracle.chat.instructions`), plus «Menu» (the editor above). Tone,
mode and instructions are central settings (Themis, layer client `telegram`) through `personal_settings.py`.

### Confirm cards and assistant questions
- An Oracle `question` with `question_id` (e.g. a Themis proposal made in this chat) becomes a card with two
  buttons; the answer goes to `POST /api/chat/question-answer` (`client: telegram`).
- `ask_user` questions (`services/assistant_questions.py`): Sì/No, single choice, multiple choice (toggles +
  «Invia»), «Altro…» / free text; a question no longer open answers «Questa domanda non è più aperta».

## Notifications (`services/notifications.py`)

- Hermes `/api/notify`: `notification` → message with tone dot and buttons `na:<short id>` (old `ntf:` still
  accepted), «Apri» opens the WebUI page as Mini App when there is a public https address; `update` → buttons
  replaced by a disabled state button («Vista su WebUI», «Approva · da WebUI»); `retract` → deleted; repeat chains
  in italics, superseded ones deleted (over 48 h: «Sostituito»).
- Button → Hermes `/api/notifications/{id}/answer` (first answer wins; 409 → «Già gestita»).
- Any message of the owner marks the notifications shown here as seen (`/api/notifications/seen-all`).
- Secret form (`secret` in the body, Cindy 4): an «Inserisci» button opens the WebUI Notifiche page as Mini App
  (`/p/hermes/notifiche?secret=<id>`); without a public address a line says to open the WebUI. The value is never
  asked or typed in the chat.
- `silent` (held, quiet, or another client in use: Hermes rings only where the owner is) → not sent here, inbox only.

## Mini App (`telegram_bot/webapp.py`)

With `WEBUI_PUBLIC_URL` (or `CLOUDFLARE_TUNNEL_HOSTNAME`) on https: chat menu button «Apri Hestia» and «Apri»
buttons open WebUI pages inside Telegram (`?tg=1`). The page logs in by itself: WebUI
`POST /api/webui/auth/telegram` asks this module `POST /api/webapp/verify` (via Hub) to check Telegram's signed
`initData` with the bot token (fresh ≤ 24 h, user in `ALLOWED_USER_ID`); the WebUI then issues a 12-hour session
token. With http the button is a plain link; with no public address no button is drawn.

## Access control (fail closed)
- `ALLOWED_USER_ID` (one id or comma-separated) is **required**: unset → the bot answers nobody and tells the sender
  their id. Checked on every message and every callback (`telegram_runtime`).

## Owner notification alias
- Services notify `target: "owner"`; Telegram resolves it to the first `ALLOWED_USER_ID`
  (`core.resolve_notify_target`). The chat id lives only in `Hestia-Telegram/app/.env`.

## OAuth paste shortcut
- A pasted `/api/gateway/auth/callback/<provider>?code=…` URL goes straight to Hecate
  (`POST /api/gateway/auth/complete/<provider>` via Hub); reply 🟢 / 🔴 without raw errors (`services/oauth_paste.py`).

## Module settings (Themis, `app/telegram_settings.py`)
Env keeps only secrets/infrastructure: `TELEGRAM_BOT_TOKEN`, `ALLOWED_USER_ID`, `HUB_API_URL`, `TELEGRAM_BASE_URL`,
`TELEGRAM_CONTROL_PORT`, `FEEDBACK_ARCHIVE_URL`, `WEBUI_API_URL`, `WEBUI_PUBLIC_URL`, `WEBUI_ADMIN_SECRET`,
`TELEGRAM_UI_STATE_FILE`.

| Key | Default |
|---|---|
| `telegram.feedback.prompt_rate` | 0.15 |
| `telegram.feedback.snooze_days` | 7 |
| `telegram.chat.locale` | `it` |
| `telegram.chat.client_instructions` | Telegram format contract (no emoji, HTML) |
| `telegram.oracle.stream_timeout` | 600 s |
| `telegram.menu.layout` | `{}` (system scope; see Navigation) |
| `telegram.log.level` | `LOG_LEVEL` at boot |

Removed with the redesign: `telegram.alerts.buffer_window`, `telegram.commands.hidden*`, `telegram.signals.*`.

## API Endpoints (control server, `services/control_service.py`)

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/notify` | Hermes notification client (notification / update / retract, see Notifications) |
| `POST` | `/api/webapp/verify` | WebUI via Hub: `{init_data}` → `{ok: true, user_id}` or 403 `{ok: false, reason}` (Mini App login) |
| `POST` | `/api/events/registry-changed` | Hub: tools changed → catalog refresh |
| `POST` | `/api/chat-queue/drain` | Chronos: Oracle is back, answer queued messages |
| `GET` | `/health` | Service health |
| `GET` | `/api/settings/effective` | Themis: values in use |
| `POST` | `/api/settings/reload` | Themis: push changed values |
| `GET` | `/api/logs` | Log buffer |

`/api/dispatch/send` (legacy) was removed: every notification goes through Hermes `/api/notify`.

## WebUI token actions
`webui_token`, `webui_status`, `webui_revoke` call the WebUI admin API directly (`WEBUI_API_URL`, security exception:
not via Hub) with `X-WebUI-Admin-Secret` when `WEBUI_ADMIN_SECRET` is set. The token comes with «Apri» and «Copia».

## Assistant presence
Every allowed message, file and button pings Chronos presence (`telegram`, debounced 60 s, `services/presence.py`).
`/stato` shows the assistant state.

## Oracle offline (chat queue)
SPEC `docs/work/2026-10-19-oracle-offline`, `services/chat_queue.py`. A message Oracle does not accept is stored in
Archive (`/api/chat-queue`, client `telegram`) and the reply is «🟠 Non disponibile: messaggio in coda, ti rispondo
appena possibile.» `POST /api/chat-queue/drain` and startup answer the queue chat by chat in one turn (`queued`).

## Constraints
- Domain decisions stay in modules; Telegram only presents and asks.
- No database access, no LLM formatting of tool results, no module names in user texts.
- Service calls go through Hub (exceptions: Oracle chat streaming, WebUI admin API).

## Tests
`python -m pytest -q -m "unit or api or format" Hestia-Telegram/tests` — grammar, store, inputs, renderer, menu
reachability over every module tool, action flow, notifications, settings, Mini App signature.
`python tools/governance/check_telegram.py` — no emoji in tool titles, every tool in an area, labels fit.

## Questions from the assistant (v3 A, `services/assistant_questions.py`)

When the assistant asks (Oracle tool `ask_user`, question id `ask_…`) the question arrives as a message with inline
buttons: confirm (Sì/No), single choice, multiple choice (toggles + «Invia»), «Altro…» or free text (the next text
message is the answer). The callback is answered at once, then the answer goes to Oracle
`/api/chat/question-answer`; its `resume` message is sent as the next chat turn, so the reply comes as usual. A
question no longer open answers «⌛ Questa domanda non è più aperta».

## Answer extras (dossier `docs/work/2026-10-24-tutto-brainstorm-cindy`, wave 1)
`services/answer_extras.py` + `ReplyRenderer`:
- ```` ```hestia-ui ```` components in an answer are shown as plain text (`ui_blocks.to_text`); their buttons
  become an inline keyboard «Scegli» whose tap sends the button's text as the next chat message (callback `uisend:`).
- `final.origin` not from the owner (`routine`, `autonomo`) adds its label in italics above the answer.
- The `changes` frame becomes «📝 Ho fatto» with one «↩️ Annulla: …» button per change that has an undo; the tap
  (callback `undo:`, same chat only, 24 h) runs the undo tool through Hestia-MCP; on failure the button stays.
- `goal.progress` notices («🎯 Obiettivo») follow the normal notice settings.

## Data and backup (`app/telegram_bot/transfer_actions.py`, dossier `docs/work/2026-10-24-tutto-brainstorm-cindy`, wave 3, parity F)
- «Esporta i dati»: Telegram (a client, like the WebUI page) asks every module with the `transfer` capability for its
  export through Hub and sends `hestia-AAAA-MM-GG.hestia` (gzip JSON, same format, no photos) as a document.
- «Importa dati»: asks for the file, shows the preview (dry run), «Importa» merges (adds/updates, never deletes) and
  first sends back the current data of the same modules as `hestia-prima-….hestia` (import it to go back). The file
  waits in memory 30 min at most, one use, same chat only.
- «Ripristina un backup» (list of Drive backups → «Ripristina <data>», destructive confirm) and «Annulla ripristino»
  call Archive `/api/backup/restore` · `/undo`; status, list and «Backup adesso» are Archive tools.
