# Hestia-Echo 🎙️

**Role:** Voice — the only module that listens (speech → text) and speaks (text → speech), for files and streams,
for every client. Built like Oracle a blocchi: named providers, chains, uses declared by modules, external mode.
**Node:** main host (local engines want the CPU/GPU of the PC)
**Stack:** Python · FastAPI · ffmpeg · faster-whisper · Piper · Kokoro (onnx) · Docker · WebUI plugin bundle (Lit, `ui/`)
**Port:** 19021 · Core module (`kind="core"`, page «Voce» order 125) · Dossier: `docs/work/2026-10-20-modulo-voce/`

---

## Responsibility

- **Listening** (`ascolto`): audio of any format (ogg/opus from Telegram, webm from the browser, mp3, wav, m4a…) → text.
- **Speaking** (`voce`): text → audio (`ogg_opus` for Telegram voice notes, `mp3` for browsers, `wav`, `webm`).
  Before speaking, the text is made speakable (markdown, links, code and emoji dropped; very long texts cut at
  `echo.voce.max_chars` with «il resto è nel testo»).
- **Streams in blocks**: `listen` (microphone in chunks → partial text, trailing silence for the end of a turn) and
  `say` (text while it is written → audio sentence by sentence). Live mode on every client is Oracle (the same chat,
  the same models) + Echo. **No external live service** (no OpenAI Realtime, no Gemini Live): Marko's decision.
- **Keeping audio** (rule: never throw away what cannot be made again): Marko's recordings are never deleted
  automatically; generated audio is kept while useful and made again from the text.
- Nobody else calls speech engines: Oracle's documents, Telegram, WebUI and Hermes all go through Echo
  (`hestia_common.voice_client`). Whisper left Oracle.

## Blocks (Themis settings, page «Voce → Motori»)

- **Providers** `echo.providers`: name → `{type, label, url, options}`. Standards (`app/core/standards.py`):
  `whisper_local` (faster-whisper, ascolto), `piper` (voce), `kokoro` (voce, voices `if_sara`, `im_nicola`), `openai`
  (any OpenAI-compatible audio API: OpenAI, Groq, a local speaches/LocalAI…), `google` (Cloud STT/TTS with key),
  `elevenlabs`, `wyoming` (Home Assistant's protocol: a Piper/Whisper on another machine). Every standard declares
  its own options (beam, initial prompt, speed, pauses, style…). **Keys only in env** as `ECHO_KEY_<NAME>`
  (e.g. `ECHO_KEY_GROQ`), never in Themis.
- **Chains** `echo.chains`: name → `{label, direction: ascolto|voce, steps[{provider, model, voice, options}]}`.
  The first ready step is used; a step out of quota (429) is skipped until its reset (`Retry-After` or
  `echo.chains.cooldown`), «Riprova adesso» clears it. Defaults: `ascolto` (Whisper locale small → Groq
  whisper-large-v3-turbo), `ascolto-preciso`, `voce` (Kokoro if_sara → Piper it_IT-paola-medium), `voce-naturale`.
- **Uses** `echo.usecases`: every module declares its uses in Hub capabilities `voice_usecases`
  (`hestia_common.voice_usecases.usecase(id, label, direction=, chain=, help=, mode=)`); the page chooses chain and
  mode per use. Undeclared uses still work on the default chain of their direction and are listed as «non dichiarato».
- **Mode** `echo.mode`: `interna` (Echo's chains) or `esterna` (one engine does everything, `echo.external.provider`
  + `echo.external.model`; Echo is only the door: cuts blocks, keeps audio, counts use). If the external engine fails:
  `echo.external.fallback` = `interna` (back to the chains) or `nessuno` (say it does not work). Each use may override.

Declared uses today: `echo.prova.*` (page «Prova»), `oracle.documenti` (audio in documents, chain `ascolto-preciso`),
`telegram.vocale`, `telegram.risposta`, `webui.vocale`, `webui.ascolta`, `webui.live.ascolto`, `webui.live.voce`,
`hermes.notifica`.

## Keeping audio (Archive)

Bytes in Archive blobs (owner `echo`), index in Archive `/api/echo-store/records` (`kind=audio`, `ref_id` = message or
notification id, `parent_id` = session). Classes:

| Class | What | Kept |
| --- | --- | --- |
| `recording` | Marko's voice (voice notes, «Parla») | forever (opus 16 kbps); only Marko deletes them |
| `file` | audio sent as a document | like a document |
| `generated` | replies read aloud | `echo.audio.generated_days` after the last listen, then regenerated from the text |
| `notification` | voice of a notification | as long as its notification (dropped when superseded) |

Daily agenda job `echo.audio_cleanup` (04:30): expired generated audio, then the space rule `echo.audio.space_mb`
(oldest regenerable first). If recordings alone exceed the limit nothing is deleted: Marko gets one notice.
The same text for the same message is never generated twice (`text_hash`).

## Notifications in voice

Each module decides with its own setting `<module>.notifiche.voce` (`hestia_common.reminders.voice_setting`; on for
Hercules, Hygieia, Wardrobe; off for Plutus and Scout). The event carries `_voice`; Hermes publishes the written
notification first, then asks Echo (use `hermes.notifica`) and sends an `update` with `voice`: Telegram sends a voice
message replying to the notification (deleted with it), the WebUI inbox shows «Ascolta». The written notification
never changes.

## Clients

- **Telegram**: a voice note becomes a chat message (transcript shown, then handled like typed text, recording
  kept); every reply has «Ascolta»; `/voce` switches spoken answers to voice notes on or off.
- **WebUI**: voice messages in the chat like any messenger (hold to record, release to send, slide left to cancel;
  with a mouse click to record, then bin or send), audio bubble with transcript; «Ascolta» under every reply;
  **Parla** (live): the browser notices start and end of speech (`echo.live.silence_ms`), streams the mic to `listen`,
  sends the answer to `say` while it is written and plays it sentence by sentence; speaking again interrupts.
- **Page «Voce»** (plugin): Prova (mic → text, text → voice, with provider and chain that answered), Motori
  (providers, chains, uses), Uso (operations, minutes, characters, cost from `echo.pricing`, errors by use and
  engine), Audio conservati (space by class, listen, download, delete).

## Settings (Themis, `echo.*`)

`echo.providers`, `echo.chains`, `echo.usecases`, `echo.mode`, `echo.external.provider`, `echo.external.model`,
`echo.external.fallback`, `echo.language` (it), `echo.voce.max_chars` (1200), `echo.ascolto.max_seconds` (600),
`echo.live.silence_ms` (900), `echo.chains.cooldown` (60 min), `echo.audio.space_mb` (2048),
`echo.audio.generated_days` (30), `echo.pricing`.

## API (via Hub `/route/echo/...`, prefix `/api/voice`)

| Method | Path | What |
| --- | --- | --- |
| POST | `/transcribe` | `{audio_b64, mime_type, use_case, language?, keep?}` → `{text, language, duration_s, provider, model, chain, mode, fallback, blob_id?}` |
| POST | `/speak` | `{text, use_case, format?, voice?, keep?}` → `{audio_b64, mime_type, duration_s, provider, voice, blob_id?}` (reuses kept audio of the same message + text) |
| POST | `/listen`, `/listen/{sid}/chunk`, `/listen/{sid}/end` | mic stream: open · chunk `{seq, audio_b64, partial?}` → `{partial, silence_ms, duration_s}` · end → like `/transcribe` |
| POST | `/say`, `/say/{sid}/text`, `/say/{sid}/end` | voice stream: open `{use_case, format}` · text `{delta}` → `{blocks[{seq, text, audio_b64, mime_type}]}` · end `{keep?}` |
| GET | `/live` | `{silence_ms, language}` for clients' live mode |
| GET | `/standards`, `/providers`, `/providers/options`, `/chains`, `/usecases` | blocks and their state |
| PUT | `/blocks/{providers\|chains\|usecases}` | the page's edit, stored through Themis |
| POST | `/providers/{name}/retry` | forget the quota state |
| GET | `/usage?days=`, `/recent` | use and cost |
| GET | `/audio`, `/audio/{id}?format=`, `/audio-for?ref_id=` | kept audio (list with space, one, the one of a message) |
| DELETE | `/audio/{id}`, `/audio?notification_id=\|message_id=` | delete one; drop regenerable audio of a removed notification |
| POST | `/audio/cleanup` | agenda job |

`keep` = `{kind: recording|file|generated|notification, message_id?|notification_id?, session_id?, client?}`.

## Configuration (infrastructure only)

`ECHO_KEY_<NAME>` (keys of cloud providers, `Hestia-Echo/app/.env`), `ECHO_MODELS_DIR` (`/models`, volume
`hestia_echo_models`: Whisper, Piper and Kokoro files are downloaded on first use), `HUB_API_URL`, `TZ`.

## Tests

```
python -m pytest -q -m "unit or api or format" Hestia-Echo/tests
```
Fake engines and a fake Archive: chains and fallback, quota skip, external mode and its fallback, streams (partials,
silence, seq dedupe, sentence blocks), keeping (reuse, cleanup, space rule, warning, forget), endpoints, manifest.
