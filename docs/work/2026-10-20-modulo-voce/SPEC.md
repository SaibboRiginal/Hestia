# SPEC — Voice module (Hestia-Echo): speech-to-text and text-to-speech for every client

| | |
|---|---|
| **Version** | 3.2 |
| **Source** | user via external chat → project brainstorm 2026-10-19, item 4 of the final list (`/mnt/project-files/brainstorm/2026-10-19-idee-e-cloud.md` §0); routed by the project coordinator 2026-10-20 |
| **Status** | Approved by Marko 2026-10-20 (v3.1, answers in §10); V1–V10 implemented (v3.2 notes in §11), PR open, Marko's real run pending |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).

User's words (summary, Italian original in the brainstorm): a module that is Hestia's "vocal cords": transcription and
synthesis, files and stream, for every client (Telegram, WebUI with the microphone), local profiles (Whisper,
Piper/Kokoro) and cloud ones (Google…), like Oracle does for models. Whisper leaves Oracle; the rule becomes
**only Oracle calls the LLMs, voice belongs to the voice module**. «Note vocali? Entrambe: tu mandi un vocale → trascritto
e trattato come messaggio; l'assistente può rispondere a voce. Sì, anche sul sito: microfono nel browser.»
Vision check (Marko): an open personal Jarvis, usable from any client; talking to it must feel as natural as writing.

---

## 1. Today (verified in code, 2026-10-20)

- A Telegram voice note is handled like any file: `chat_service.py` downloads it and posts it to Oracle
  `/api/chat/document` with the caption «Trascrivi questo messaggio vocale.». The answer is a transcript, **not** a reply
  to what was said: the voice note never becomes a chat message.
- Oracle transcribes with WhisperX (`core/document/local_models.py`, setting `oracle.documents.whisper_model`) inside
  document analysis and archiving. `whisperx` is commented out in `requirements.txt`, so in the real stack there is no
  local transcription; it only works when the document model hears audio natively (`oracle.documents.audio_models`,
  Gemini).
- No text-to-speech anywhere. The WebUI chat has no microphone and no playback.
- No service owns audio: the WebUI cannot transcribe, Hermes cannot speak.

## 2. Goal

1. **Hestia-Echo** (port 19021): one module owns speech. `POST /api/voice/transcribe` (audio → text) and
   `POST /api/voice/speak` (text → audio), reached through the Hub like every service.
2. **Built in blocks like Oracle a blocchi**: named **providers** (Themis: name, standard, address; env: key only),
   named reusable **chains** with a direction (*ascolto* = speech→text, *voce* = text→speech), **uses** declared by the
   callers and pointed at a chain, **per-provider options** declared by each standard, and an **external mode** where
   Echo is only the door and proxies to an external (or self-hosted) voice engine, exactly like Oracle's brain mode.
3. **Echo is the audio transport**: it handles whole files and **streams in blocks** (audio chunks in, sentences out),
   so every client gets live dictation and replies that start speaking after the first sentence.
4. **Two ways of talking**: **chat** stays text (a voice message is transcribed and answered in text, like a typed
   one; every reply has «ascolta»), and a new **live** mode answers by voice, like a call (§7).
5. **Voice in notifications**: Hermes can add a voice version of a notification (the written notification stays; the
   audio is an addition, §7).
6. **Oracle drops Whisper**: audio inside documents is transcribed by asking Echo; Oracle keeps only what is an LLM
   (models that hear audio natively).
7. **Plugin «Voce»** (core): providers, chains, uses, mode, tests and a usage panel like Oracle's.
8. **Audio is kept with judgement** (§7.4): what Marko recorded is never thrown away; what Hestia generated lives as
   long as the message or notification it belongs to, and space never fills up.

Out of scope (later, if wanted): wake word / always-listening, speaker
identification, phone calls, voice cloning.

## 3. Architecture

```
Telegram ──voice.ogg──▶ Hub ▶ Echo /api/voice/transcribe ──text──▶ normal chat (Oracle) ──reply──▶ Telegram
                                                                                │ «ascolta» / live / notification
                                         Echo /api/voice/speak ◀───────────────┘ ──ogg/opus──▶ sendVoice
WebUI mic (webm/opus) ─▶ WebUI backend ─▶ Hub ▶ Echo transcribe ─▶ text in composer, sent
WebUI reply (streamed) ─ sentence ─▶ WebUI backend ─▶ Hub ▶ Echo speak ─▶ audio queue in the browser
Oracle document with audio ─▶ Hub ▶ Echo transcribe ─▶ transcript ─▶ Oracle LLM as today
```

- **Module boundaries**: Echo converts sound ↔ text and nothing else. It never calls Oracle and never decides what to
  answer. Clients (Telegram, WebUI) decide when to transcribe and when to speak; Oracle stays the brain.
- **Rule change** in `CLAUDE.md` and `docs/ARCHITECTURE.md`: «Oracle is the only caller of **LLM** providers;
  speech providers (STT/TTS) belong to Echo».
- **Transport**: JSON through the Hub envelope, audio as base64 (`audio_b64`). Files are small (a minute of opus ≈
  100 KB; limit `echo.ascolto.max_seconds`). Streams are **blocks**, not sockets: a stream is a sequence of Hub calls
  on one `stream_id` (§6), so the Hub stays the only door and every client (Telegram, WebUI, future ones) uses the
  same contract. No direct URLs.
- **Node**: the PC (with Oracle), because local Whisper and Kokoro want CPU/GPU; Piper also runs on a Raspberry Pi.
- **ffmpeg** in the Echo image converts any input (ogg, webm, m4a, mp3, wav, mp4) to 16 kHz mono for the engines and
  produces the output format the client asks for (`ogg_opus` for Telegram voice, `mp3`/`webm` for browsers).

## 4. Blocks (same shape as Oracle a blocchi)

### A. Named providers (Themis = name, standard, address, options · env = key only)
- **Standards** are what Echo knows how to speak to; providers are named instances of a standard:

  | Standard | Directions | Example providers | Per-provider options (declared by the standard) |
  |---|---|---|---|
  | `whisper_local` (built in, faster-whisper) | ascolto | `whisper-locale` | model size, beam size, VAD on silence, initial prompt (names, jargon), device cpu/gpu |
  | `piper` (built in) | voce | `piper` | voice, length scale (speed), noise, sentence silence |
  | `kokoro` (built in) | voce | `kokoro` | voice, speed |
  | `openai` (compatible audio API) | ascolto + voce | `openai`, `groq` (free Whisper large-v3-turbo), `speaches` / `kokoro-fastapi` / LocalAI (self-hosted) | prompt, temperature; voice, speed, `instructions` (style, for models that take it) |
  | `google` (Cloud Speech-to-Text / Text-to-Speech) | ascolto + voce | `google` | recognition model, punctuation; voice, speaking rate, pitch, audio profile |
  | `elevenlabs` | ascolto + voce | `elevenlabs` | model, voice, stability, similarity, style |
  | `wyoming` (Home Assistant voice protocol, TCP) | ascolto + voce | any Wyoming whisper/piper server on the LAN | voice |

- Setting `echo.providers` (object, live): `{name: {type, label, url, options}}`, edited from the WebUI. Defaults:
  `whisper-locale`, `piper`, `kokoro` (always present), `groq`, `google`, `openai` (used only once their key exists).
- **Keys only in env**: `ECHO_KEY_<NAME>` (upper-case, `-` → `_`, e.g. `ECHO_KEY_GROQ`, `ECHO_KEY_GOOGLE`) in
  `Hestia-Echo/app/.env`. The panel shows only «chiave ✓ / manca».
- `GET /api/voice/standards` returns each standard's option schema (type, range, options), so the WebUI draws the
  form and a new standard needs no WebUI change. `GET /api/voice/providers`: state (ready / no key / downloading /
  unreachable), models and voices (`list_models()` / `list_voices()` per standard), quota state.

### B. Named reusable chains, each with a direction
- Setting `echo.chains` (object, live): `{name: {label, direction: ascolto|voce, steps: [{provider, model|voice,
  options?}]}}`. Step options override the provider's options (e.g. the same Google provider, a slower voice for
  long readings).
- Defaults (editable, more can be added):

  | Chain | Direction | Steps (a step whose provider has no key is skipped) |
  |---|---|---|
  | `ascolto` | ascolto | whisper-locale `small` → groq `whisper-large-v3-turbo` |
  | `ascolto-preciso` | ascolto | groq `whisper-large-v3` → whisper-locale `medium` |
  | `voce` | voce | kokoro `if_sara` → piper `it_IT-paola-medium` |
  | `voce-naturale` | voce | kokoro `if_sara` → google `it-IT-Chirp3-HD` → piper `it_IT-paola-medium` |

- Fallback exactly like Oracle: on quota/rate limit the provider+model pair is skipped by every chain until its reset
  (or `echo.chains.cooldown`, 60 min); on other errors the next step for this call only. One
  `event=voice_chain_step_unavailable` per change; `[🔄]` on fallback; all steps failed → `event=voice_chain_exhausted`
  and a clear error.

### C. Uses: declared by the callers, configured in one place
- Each caller declares its uses with `hestia_common.voice_usecases([...])` in its Hub caps (same helper shape as
  `oracle_usecases`): id `<module>.<task>`, label, direction, suggested chain. First ones: `telegram.vocale` (ascolto),
  `telegram.risposta` (voce), `webui.dettatura` (ascolto, stream), `webui.risposta` (voce, stream), `webui.live`
  (both, stream), `hermes.notifica` (voce),
  `oracle.documenti` (ascolto, long files → `ascolto-preciso`), `echo.prova` (the plugin's test box).
- Setting `echo.usecases` (object, live) keeps only Marko's overrides `{use: {chain, mode}}`; undeclared uses run on
  the default chain of their direction and are listed too.

### D. External mode (a mode of its own, like Oracle's brain)
- Setting `echo.mode` = `interna` (default) | `esterna`, `echo.external.provider` (a provider whose standard does the
  needed direction(s), e.g. a self-hosted Speaches or Wyoming server, or a cloud one) and `echo.external.fallback` =
  `interna` (default) | `nessuno`. A use can override the mode (`segui` | `interna` | `esterna`).
- **Interna** = Echo's own machine: ffmpeg conversion, silence detection, cutting audio and text into blocks, chain
  with fallback, text cleaning before speaking.
- **Esterna** = Echo is only the door and a **proxy**: it passes files and streams to the external engine as they
  are (the engine does its own chunking, VAD and sentence handling) and only keeps the door work: Hub contract,
  format fit for the client (e.g. ogg/opus for Telegram), text cleaning, logs, usage rows, and the fallback to
  `interna` when the engine fails. Clients never notice the difference.
- Boundary kept: an engine reached in `esterna` must be a speech engine (sound ↔ text). **No external live / speech-to-
  speech services** (OpenAI Realtime, Gemini Live…), now or later (Marko 2026-10-20): live is rebuilt with Oracle (only
  the LLMs it already uses, no change to its architecture) + Echo.

## 5. Other settings (Themis, declared by Echo)

| Key | Type | Default | Meaning |
|---|---|---|---|
| `echo.language` | enum | `it` | language for listening (`auto` allowed) and speaking |
| `echo.voce.max_chars` | number | `1200` | longer replies: voice reads the first part and says the rest is in the text |
| `echo.ascolto.max_seconds` | number | `600` | longest audio accepted |
| `echo.chains.cooldown` | number | `60` | minutes a pair that hit its quota is skipped when the provider gives no reset |
| `echo.pricing` | object | `{}` | `provider/model` → cost per minute heard / per 1M characters spoken, for the usage panel |

| `echo.audio.space_mb` | number | `2048` | space for kept audio; over it, generated audio goes first (§7.4) |
| `echo.audio.generated_days` | number | `30` | how long a generated reply audio is kept after its last listen |

No env tunables besides keys. Voice in notifications is decided by each module (§7.3).

## 6. API (Echo, all through the Hub; `Hestia-Swagger/swagger.yml` updated)

Files:
- `POST /api/voice/transcribe` `{audio_b64, mime_type, use_case, language?}` → `{text, language, duration_s,
  provider, model}`; 422 empty/too long, 503 chain exhausted.
- `POST /api/voice/speak` `{text, format: ogg_opus|mp3|webm|wav, use_case, voice?}` → `{audio_b64, mime_type,
  duration_s, provider, voice}`. Markdown, links, code blocks and emoji are not read aloud.

Streams in blocks (one `stream_id`, closed by `end` or after 60 s idle):
- Listening: `POST /api/voice/listen` `{use_case, mime_type}` → `{stream_id}` · `POST /api/voice/listen/{id}/chunk`
  `{seq, audio_b64}` → `{partial}` · `POST /api/voice/listen/{id}/end` → final `{text, …}`.
- Speaking: `POST /api/voice/say` `{use_case, format}` → `{stream_id}` · `POST /api/voice/say/{id}/text`
  `{delta}` → `{blocks: [{seq, audio_b64, text}]}` (Echo cuts complete sentences out of the deltas it has received)
  · `POST /api/voice/say/{id}/end` → the last blocks. A client forwards the reply deltas as they stream from Oracle.

Blocks: `GET /api/voice/standards`, `GET /api/voice/providers`, `GET /api/voice/chains` (resolved, with step state),
`GET /api/voice/usecases` (declared + overrides), `GET /api/voice/usage?days=` (from Archive).
Plus `/health`, Hub registration, `hestia_common` startup and logging.

**Usage** like Oracle's panel: every operation writes a row to Archive `voice_usage` (use, chain, step, provider,
model/voice, mode, seconds heard / characters spoken, duration, ok, cost). Transcripts live in the chat session like any message;
the audio itself is kept as §7.4 says.

No MCP tools in this version: audio is not useful to an LLM, and the chat already gets the transcript as text.

## 7. Clients, modes, notifications, keeping audio

### 7.1 Chat (text, as today)
**Telegram**
- `voice` and `video_note`: download → `transcribe` (`telegram.vocale`) → the status message shows «🎙️ <i>testo
  capito</i>» → the text goes into the **normal chat path** (session, streaming, queue while unavailable); the reply is
  text.
- Every reply gets an inline «🔊 Ascolta» button: Telegram asks Echo (`telegram.risposta`, `ogg_opus`) and sends the
  voice message under the reply.
- `audio` files keep the document path (transcribe and summarize), now served by Echo through Oracle.
- Transcription fails: `[🔄]` today's document path (an LLM that hears audio, if a chain has one); then a generic
  «Non riesco ad ascoltare il vocale adesso, puoi scrivermelo?» (no module names).

**WebUI** (Angular, `DESIGN-SYSTEM.md`, stroke icons, no emoji)
- Voice messages **like WhatsApp / Telegram / the Claude app**: on the phone hold the microphone to record, release to
  send, slide to cancel; on desktop click to record, click send (or the bin to cancel). While recording, chunks go to
  a `listen` stream (`webui.dettatura`) so the text is ready when you release. The message appears in the chat as an
  **audio bubble** (play, duration) with its transcript under it; the transcript is what goes to Oracle. The reply
  is text.
- Every assistant reply gets «ascolta» (`webui.risposta`, played in blocks).
- .NET `VoiceController` only forwards to the Hub route `echo` (no audio logic in the WebUI).

### 7.2 Live (voice, like a call)
- **WebUI**: a «Parla» button next to the composer opens the live view: microphone always open, Echo's silence
  detection closes each turn, the turn goes to the chat as text, the reply streams from Oracle into a `say` stream and
  is **spoken** sentence by sentence; speaking while Hestia talks interrupts her. Text of both sides scrolls under the
  waveform, and it is the same Archive session as the chat (closing live returns to the same conversation).
- **Telegram** (no live audio in bots): `/live` switches that chat to voice replies (each voice note gets a voice
  answer, text kept under it) until `/chat`. Shown in the bot's state line.
- Live is a mode Marko enters and leaves, not a setting.

### 7.3 Voice in notifications (Hermes)
- **Each module decides** (Marko 2026-10-20): a module marks a notification `voice: true` when it reads well aloud,
  and declares its own setting `<module>.notifiche.voce` (helper in `hestia_common.reminders`) with its own default:
  e.g. Hygieia/Hercules reminders and the daily recap **on**, Scout listings and Plutus movements **off**. A setting is
  allowed here because the feature acts on its own (it sends something).
- Hermes stays the only messenger: for a notification with `voice: true` it asks Echo (`hermes.notifica`) for the
  audio and attaches it: Telegram sends the voice message right after the text; the WebUI notification gets a play
  button.
- The written notification never changes; no audio (Echo down, chain exhausted) = the notification as today.
- The notification audio belongs to the notification: it is removed when the notification is removed or retracted.

### 7.4 Keeping audio (Archive blobs, owner `echo`)
Rule: **never throw away what cannot be made again; keep what can be made again only while it is useful.**

| Kind | Example | Kept | Format |
|---|---|---|---|
| Marko's recordings | voice notes, live turns, dictation | **always** (never deleted automatically; Marko can delete them from the plugin) | re-encoded opus 16 kbps mono (≈ 7 MB per hour of speech) |
| Audio files sent in chat | an mp3 recording | always, like any document | as sent |
| Generated replies | «ascolta», live answers | `echo.audio.generated_days` after the last listen; listening again regenerates it from the text | opus |
| Notification audio | Hermes voice | as long as its notification | opus |

- Every blob has meta `{kind, use_case, session_id, message_id | notification_id, duration_s, text}` so it is found
  from its message («ascolta» of an old voice note plays the original) and cleaned with its owner.
- Space: a daily Chronos agenda job (`echo.audio_cleanup`) drops expired generated audio; if `echo.audio.space_mb` is
  still exceeded it drops the oldest generated audio first. Recordings are **never** dropped for space: if they alone
  pass the limit, Marko gets one notification (via Hermes) to raise it or export them; with the Drive backup
  (brainstorm item 8) they go into the encrypted `.hestia` backup like the rest of Archive.

**Oracle**
- WhisperX code (`local_models.transcribe_audio`) and `oracle.documents.whisper_model` are removed; analyser and
  archiver call `transcribe` with `oracle.documents`. `oracle.documents.audio_models` stays (it is about LLMs).

## 8. Plugin «Voce» (core, in Echo's `ui/`)

Same layout as Oracle's «Modelli»: **Fornitori** (add/edit, standard picker, options form from the schema, key
state), **Catene** (two groups, ascolto and voce; ↑↓ reorder, provider/model/voice pickers, step state), **Usi** (by
module: chain + mode), **Modalità** (interna/esterna, engine, fallback), **Prova** (microphone → text; text + voice →
play; shows which step answered), **Uso** (minutes heard, characters spoken, cost, by use/provider, last operations).
Everything writes through Themis. Icons mic, speaker, waveform added to the WebUI set if missing.

## 9. Phases (each: tests green, docs updated, PROGRESS ticked)

- **V1 Echo core** — service from the template, standards `whisper_local`/`piper`/`kokoro`/`openai`/`google`, providers +
  `ECHO_KEY_*`, chains with quota skip, uses (`hestia_common.voice_usecases`), ffmpeg, text cleaning, file endpoints,
  settings, usage rows (Archive `voice_usage`), Dockerfile with model volume, compose (global + cloud test), CI
  matrix, `hestia-echo.md`, swagger, `.env.example`, unit/api tests with fake engines.
- **V2 Streams in blocks** — `listen` / `say` streams, sentence cutting, idle close; standards `elevenlabs`, `wyoming`.
- **V3 External mode** — `echo.mode`, proxy path, per-use override, fallback; tests with a fake engine.
- **V4 Oracle without Whisper** — analyser/archiver call Echo; WhisperX code and setting removed; tests.
- **V5 Keeping audio** — blobs with meta, opus re-encode, `echo.audio_cleanup` agenda job, space rule, tests.
- **V6 Telegram** — voice note → chat, «Ascolta» button, `/live`, fallback, queue while unavailable; tests.
- **V7 WebUI** — `VoiceController`, composer mic with live text, WhatsApp-style voice messages (hold/release/slide, audio bubble + transcript), «ascolta», live view «Parla».
- **V8 Notifications** — `voice` flag + `<module>.notifiche.voce` helper, modules set their defaults, Hermes attaches audio on Telegram and WebUI, removed with the notification.
- **V9 Plugin «Voce»** — tabs of §8, plus «Registrazioni» (Marko's recordings: play, delete, export).
- **V10 Docs** — `CLAUDE.md` rule, `docs/ARCHITECTURE.md`, `docs/AI-GUIDE.md`, `readme.md`, `architecture-and-flow-map.md`,
  module docs (Echo, Oracle, Telegram, WebUI, Shared), root `CHANGELOG.md`; PR, CI green, merge.

**Acceptance**
1. A Telegram voice note «aggiungi al diario che oggi ho dormito male» is transcribed, shown, and handled exactly like
   the same sentence typed (the diary tool runs).
2. In chat a voice note gets a text reply; «Ascolta» sends it as voice. With `/live` (Telegram) or «Parla» (WebUI)
   replies are spoken.
3. An important notification arrives as text plus voice; removing the notification removes its audio.
4. A voice note from months ago still plays from its message; generated audio older than the limit is gone and is
   regenerated on «ascolta»; kept audio never passes `echo.audio.space_mb` because of generated audio.
5. In the WebUI the microphone shows text while speaking and sends it; the reply starts speaking after its first
   sentence.
6. A provider is added from the WebUI (name, standard, address, options) + one `ECHO_KEY_<NAME>` line and appears in
   the chain editor; a step without key is skipped and the log shows it.
7. With `echo.mode = esterna` on a self-hosted engine, Telegram and WebUI work unchanged; engine down → `interna`.
8. An audio file attached in chat is still transcribed and summarized, with no Whisper code left in Oracle.
9. Echo down: Telegram falls back or says it cannot listen right now; nothing is lost or silent.

## 10. Decisions (Marko 2026-10-20)

1. Name **Hestia-Echo**, port 19021. Default local voice **Kokoro**, Piper as backup (changeable from «Prova»).
2. Chat stays text (+ «ascolta»); **live** mode speaks (WebUI «Parla», Telegram `/live`).
3. Voice in notifications: **each module decides** with its own `<module>.notifiche.voce` setting and default.
4. WebUI voice messages work **like WhatsApp / Telegram / the Claude app** (hold, release to send, slide to cancel;
   audio bubble + transcript).
5. **No external live services**, ever: live = Oracle (its current LLMs, unchanged) + Echo.
6. Audio kept by the rule of §7.4; external mode of Echo = proxy to speech engines only.

## 11. Implementation notes (v3.2, refinements, no scope change)

- **External mode**: `esterna` sends every operation of a use to the one engine `echo.external.provider` (+ model or
  voice `echo.external.model`); the raw audio goes to it when the engine does not want PCM. Echo still cuts blocks,
  keeps audio and counts use. Fallback `interna` = the use's chain, `nessuno` = error.
- **Browsers play mp3** (Safari has no ogg/opus in `<audio>`): the WebUI asks `format=mp3`; Telegram `ogg_opus`;
  kept audio is always opus 16 kbps and converted on read (`/audio/{id}?format=`).
- **WebUI «Parla»**: the browser measures the mic level (start of speech, `echo.live.silence_ms` pause = end of turn,
  read from `GET /api/voice/live`), sends 800 ms chunks to `listen` (partial text shown), the answer's text to `say`
  every ~300 ms while it is written and plays the sentences in order; speaking again or «Interrompi» stops voice and
  answer. The turn is a normal chat message (audio bubble + transcript), the answer a normal reply.
- **Notification voice**: Hermes publishes the text first, then the audio arrives as an `update {voice}` (Telegram:
  voice message replying to the notification, deleted with it; WebUI inbox: «Ascolta» via Hermes
  `/api/ui/inbox/{id}/voice`). Defaults of `<module>.notifiche.voce`: Hercules, Hygieia, Wardrobe on; Plutus, Scout off.
- **Refs of kept audio**: Telegram `tg:<chat>:<message>`, WebUI `web:<session>:<message>`, notifications their id.
- **Page «Voce»** tabs: Prova, Motori (providers, chains, uses; saved through Themis with `PUT /api/voice/blocks/*`),
  Uso, Audio conservati.
