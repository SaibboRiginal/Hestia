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

## «La tua voce»: voiceprint and personal dictionary (W4, dossier `2026-10-24-tutto-brainstorm-cindy`)

- **Voiceprint** (Cindy 10, `app/core/voiceprint.py`): Marko records ~10 s once (page «Voce», Telegram «Registra la
  mia voce», tool `voce_impronta_registra`, at least 6 s of speech). Echo keeps a speaker embedding (WeSpeaker
  ResNet34 ONNX, downloaded on first use into `ECHO_MODELS_DIR/speaker`) in `echo-store` (`kind=voiceprint`) and the
  recording as a kept `recording`. On the uses in `echo.impronta.usi` (default the WebUI live listening) every 1.5 s
  window of speech under `echo.impronta.soglia` (cosine, 0.45) becomes silence **before** transcription and before
  the live end-of-turn check: the TV or other people neither enter the message nor keep a turn open. All windows
  muted → «non ho sentito la tua voce». No voiceprint = no filter; engine missing → audio unchanged (`[🔄]`).
- **End of turn**: live mode closes a turn after `echo.live.silence_ms` (1250 ms) of real silence of the owner.
- **Personal dictionary** (Cindy 17, `app/core/dictionary.py`): names and terms passed to every listening engine as
  a hint (Whisper `initial_prompt`, OpenAI `prompt`, ≤ 80 words). Words added by hand are confirmed at once; a
  correction of a transcript (`POST /dictionary/learn`, tool `voce_correzione`) makes the new words candidates,
  confirmed after `echo.dizionario.conferme` (2) corrections. Rows `kind=word` (id = normalised word).

## Clients

- **Telegram**: a voice note becomes a chat message (transcript shown, then handled like typed text, recording
  kept); every reply has «Ascolta»; `/voce` switches spoken answers to voice notes on or off.
- **WebUI**: voice messages in the chat like any messenger (hold to record, release to send, slide left to cancel;
  with a mouse click to record, then bin or send), audio bubble with transcript; «Ascolta» under every reply;
  **Parla** (live): the browser notices start and end of speech (`echo.live.silence_ms`), streams the mic to `listen`,
  sends the answer to `say` while it is written and plays it sentence by sentence; speaking again interrupts.
- **Page «Voce»** (plugin): Prova (mic → text, text → voice, with provider and chain that answered), Motori
  (providers, chains, uses), Uso (operations, minutes, characters, cost from `echo.pricing`, errors by use and
  engine), Audio conservati (space by class, listen, download, delete). **La tua voce** (`<echo-your-voice>`, W7): record the voiceprint
  (≥ 6 s, a sentence to read, «Togli l'impronta»), the personal dictionary (sure words and candidates «n di N»,
  add, remove with «Annulla»). In Prova «Correggi la trascrizione» sends `{heard, corrected}` to `/dictionary/learn`.

## Settings (Themis, `echo.*`)

`echo.providers`, `echo.chains`, `echo.usecases`, `echo.mode`, `echo.external.provider`, `echo.external.model`,
`echo.external.fallback`, `echo.language` (it), `echo.voce.max_chars` (1200), `echo.ascolto.max_seconds` (600),
`echo.live.silence_ms` (1250), `echo.chains.cooldown` (60 min), `echo.audio.space_mb` (2048),
`echo.audio.generated_days` (30), `echo.pricing`; group «La tua voce»: `echo.impronta.soglia` (0.45),
`echo.impronta.usi` (`["webui.live.ascolto"]`), `echo.dizionario.conferme` (2).

## API (via Hub `/route/echo/...`, prefix `/api/voice`)

| Method | Path | What |
| --- | --- | --- |
| POST | `/transcribe` | `{audio_b64, mime_type, use_case, language?, keep?}` → `{text, language, duration_s, provider, model, chain, mode, fallback, blob_id?}` |
| POST | `/speak` | `{text, use_case, format?, voice?, keep?}` → `{audio_b64, mime_type, duration_s, provider, voice, blob_id?}` (reuses kept audio of the same message + text) |
| POST | `/listen`, `/listen/{sid}/chunk`, `/listen/{sid}/end` | mic stream: open · chunk `{seq, audio_b64, partial?}` → `{partial, silence_ms, duration_s}` · end → like `/transcribe` |
| POST | `/say`, `/say/{sid}/text`, `/say/{sid}/end` | voice stream: open `{use_case, format}` · text `{delta}` → `{blocks[{seq, text, audio_b64, mime_type}]}` · end `{keep?}` |
| GET | `/live` | `{silence_ms, language, voiceprint}` for clients' live mode |
| GET, POST | `/dictionary` | personal dictionary: list · add `{word}` (confirmed) |
| DELETE | `/dictionary/{word}` | remove a word |
| POST | `/dictionary/learn` | `{heard, corrected}` → `{confirmed, candidates}` |
| GET, POST, DELETE | `/voiceprint` | status · record `{audio_b64\|audio:{data_b64, mime}}` (≥ 6 s) · forget |
| GET | `/standards`, `/providers`, `/providers/options`, `/chains`, `/usecases` | blocks and their state |
| PUT | `/blocks/{providers\|chains\|usecases}` | the page's edit, stored through Themis |
| POST | `/providers/{name}/retry` | forget the quota state |
| GET | `/usage?days=`, `/recent` | use and cost |
| GET | `/audio`, `/audio/{id}?format=`, `/audio-for?ref_id=` | kept audio (list with space, one, the one of a message) |
| DELETE | `/audio/{id}`, `/audio?notification_id=\|message_id=` | delete one; drop regenerable audio of a removed notification |
| POST | `/audio/cleanup` | agenda job |
| POST | `/models/prefetch` | queue the local models of the first local step of the «ascolto» and «voce» chains (guided setup «Voce», Download page) → `{queued, downloads}` |

Downloads (`/api/downloads`, `hestia_common.downloads`, state `/models/downloads.json`): Whisper (source `whisper`,
faster-whisper's own download, no byte progress), Piper voices and Kokoro files (source `http`, resumable), the
voiceprint model. A model still missing on first use is downloaded through the same manager (`standards.fetch`),
so it shows on the Download page and the call waits for it.

`keep` = `{kind: recording|file|generated|notification, message_id?|notification_id?, session_id?, client?}`.

Audio plumbing note: ffmpeg writing WAV to a pipe cannot fill the header sizes (0xFFFFFFFF); `to_pcm16k`
rewrites the header and `wav_duration` counts the frames really there (bench 2026-10-30: a 2.5 s reply was read as
134217 s and rejected as «audio troppo lungo»).

## Configuration (infrastructure only)

`ECHO_KEY_<NAME>` (keys of cloud providers, `Hestia-Echo/app/.env`), `ECHO_MODELS_DIR` (`/models`, volume
`hestia_echo_models`: Whisper, Piper and Kokoro files are downloaded on first use or by `/models/prefetch`), `HUB_API_URL`, `TZ`.

## Tests

```
python -m pytest -q -m "unit or api or format" Hestia-Echo/tests
```
Fake engines and a fake Archive: chains and fallback, quota skip, external mode and its fallback, streams (partials,
silence, seq dedupe, sentence blocks), keeping (reuse, cleanup, space rule, warning, forget), endpoints, manifest;
`test_your_voice.py`: dictionary (add, learn to confirmation, hint in the engine options), voiceprint (enroll,
other voices muted, live cache, unchanged without print or engine).

MCP tools (Telegram + WebUI, section «Voce»): `voce_dizionario`, `voce_parola`, `voce_parola_togli`,
`voce_correzione`, `voce_impronta`, `voce_impronta_registra` (a voice note), `voce_impronta_togli`.
Echo's Hub capabilities declare `owns_tool_domains: ["voice"]`, so Oracle's domain gate keeps these tools in chat
(without it they never reached the assistant; found on the real-model bench, 2026-10-30).
