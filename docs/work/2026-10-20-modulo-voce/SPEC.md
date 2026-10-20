# SPEC — Voice module (Hestia-Echo): speech-to-text and text-to-speech for every client

| | |
|---|---|
| **Version** | 2.0 |
| **Source** | user via external chat → project brainstorm 2026-10-19, item 4 of the final list (`/mnt/project-files/brainstorm/2026-10-19-idee-e-cloud.md` §0); routed by the project coordinator 2026-10-20 |
| **Status** | Draft — waiting for Marko's approval (§10) before any code |

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
4. **Telegram**: a voice note is transcribed and then handled **as a normal chat message** (same session, same queue when
   the assistant is unavailable). The assistant answers by voice according to the reply mode (§5).
5. **WebUI**: microphone in the chat composer, «ascolta» on every assistant reply, automatic playback in the same reply
   mode; replies are spoken sentence by sentence while they stream.
6. **Oracle drops Whisper**: audio inside documents is transcribed by asking Echo; Oracle keeps only what is an LLM
   (models that hear audio natively).
7. **Plugin «Voce»** (core): providers, chains, uses, mode, tests and a usage panel like Oracle's.

Out of scope (later, if wanted): wake word / always-listening, voice notifications from Hermes, speaker
identification, phone calls, voice cloning.

## 3. Architecture

```
Telegram ──voice.ogg──▶ Hub ▶ Echo /api/voice/transcribe ──text──▶ normal chat (Oracle) ──reply──▶ Telegram
                                                                                │ reply mode says «voice»
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
  | `voce` | voce | piper `it_IT-paola-medium` → kokoro `if_sara` |
  | `voce-naturale` | voce | kokoro `if_sara` → google `it-IT-Chirp3-HD` → piper `it_IT-paola-medium` |

- Fallback exactly like Oracle: on quota/rate limit the provider+model pair is skipped by every chain until its reset
  (or `echo.chains.cooldown`, 60 min); on other errors the next step for this call only. One
  `event=voice_chain_step_unavailable` per change; `[🔄]` on fallback; all steps failed → `event=voice_chain_exhausted`
  and a clear error.

### C. Uses: declared by the callers, configured in one place
- Each caller declares its uses with `hestia_common.voice_usecases([...])` in its Hub caps (same helper shape as
  `oracle_usecases`): id `<module>.<task>`, label, direction, suggested chain. First ones: `telegram.vocale` (ascolto),
  `telegram.risposta` (voce), `webui.dettatura` (ascolto, stream), `webui.risposta` (voce, stream),
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
- Boundary kept: an engine reached in `esterna` must be a speech engine (sound ↔ text). Speech-to-speech models that
  also *think* (OpenAI Realtime, Gemini Live) are brains: if wanted later they go under Oracle's external mode, with
  Echo only carrying the audio.

## 5. Other settings (Themis, declared by Echo)

| Key | Type | Default | Meaning |
|---|---|---|---|
| `echo.language` | enum | `it` | language for listening (`auto` allowed) and speaking |
| `echo.reply.mode` | enum | `mirror` | when the assistant answers by voice: `mirror` (only when I spoke), `always`, `never` |
| `echo.voce.max_chars` | number | `1200` | longer replies: voice reads the first part and says the rest is in the text |
| `echo.ascolto.max_seconds` | number | `600` | longest audio accepted |
| `echo.chains.cooldown` | number | `60` | minutes a pair that hit its quota is skipped when the provider gives no reset |
| `echo.pricing` | object | `{}` | `provider/model` → cost per minute heard / per 1M characters spoken, for the usage panel |

`echo.reply.mode` is a preference with three behaviours, not an on/off switch. No env tunables besides keys.

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
model/voice, mode, seconds heard / characters spoken, duration, ok, cost). Transcripts are **not** stored by Echo
(they live in the chat session like any message).

No MCP tools in this version: audio is not useful to an LLM, and the chat already gets the transcript as text.

## 7. Clients

**Telegram**
- `voice` and `video_note`: download → `transcribe` (`telegram.vocale`) → the status message shows «🎙️ <i>testo
  capito</i>» → the text goes into the **normal chat path** (session, streaming, queue while unavailable).
- `audio` files keep the document path (transcribe and summarize), now served by Echo through Oracle.
- Reply by voice (per `echo.reply.mode`): the reply deltas go to a `say` stream (`telegram.risposta`, `ogg_opus`);
  the blocks are joined and sent with `sendVoice` under the text reply (the text always stays).
- Transcription fails: `[🔄]` today's document path (an LLM that hears audio, if a chain has one); then a generic
  «Non riesco ad ascoltare il vocale adesso, puoi scrivermelo?» (no module names).

**WebUI** (Angular, `DESIGN-SYSTEM.md`, stroke icons, no emoji)
- Composer microphone (tap to start/stop; hold on phone). `MediaRecorder` sends 2–3 s chunks to the WebUI backend →
  Hub → `listen` stream (`webui.dettatura`): the partial text appears while speaking; on stop the final text is **sent
  automatically** after 2 s with an «annulla» chip (cancel keeps it in the composer).
- Every assistant reply gets «ascolta». In `mirror` (after a voice message) or `always`, the streaming reply feeds a
  `say` stream (`webui.risposta`) and the browser plays blocks in order: first sound after the first sentence.
- .NET `VoiceController` only forwards to the Hub route `echo` (no audio logic in the WebUI).

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
- **V5 Telegram** — voice note → chat; voice reply per mode; fallback; queue while unavailable; tests.
- **V6 WebUI** — `VoiceController`, composer mic with live text, auto-send + «annulla», «ascolta», block playback.
- **V7 Plugin «Voce»** — tabs of §8.
- **V8 Docs** — `CLAUDE.md` rule, `docs/ARCHITECTURE.md`, `docs/AI-GUIDE.md`, `readme.md`, `architecture-and-flow-map.md`,
  module docs (Echo, Oracle, Telegram, WebUI, Shared), root `CHANGELOG.md`; PR, CI green, merge.

**Acceptance**
1. A Telegram voice note «aggiungi al diario che oggi ho dormito male» is transcribed, shown, and handled exactly like
   the same sentence typed (the diary tool runs).
2. With `echo.reply.mode = mirror` the reply comes back as text **and** a Telegram voice message; typed → text only.
3. In the WebUI the microphone shows text while speaking and sends it; the reply starts speaking after its first
   sentence.
4. A provider is added from the WebUI (name, standard, address, options) + one `ECHO_KEY_<NAME>` line and appears in
   the chain editor; a step without key is skipped and the log shows it.
5. With `echo.mode = esterna` on a self-hosted engine, Telegram and WebUI work unchanged; engine down → `interna`.
6. An audio file attached in chat is still transcribed and summarized, with no Whisper code left in Oracle.
7. Echo down: Telegram falls back or says it cannot listen right now; nothing is lost or silent.

## 10. Choices for Marko (defaults in **bold**, used if you just say ok)

1. Name: **Hestia-Echo**, port **19021**.
2. Default `voce` chain: **Piper first** (fast, also on a Raspberry Pi), Kokoro next; or Kokoro first (more natural,
   slower on CPU).
3. Reply by voice default: **`mirror`** (voice only when you spoke), or `always` / `never`.
4. WebUI voice message: **sent automatically with «annulla» for 2 s**, or left in the composer.
5. Speech-to-speech brains (Realtime / Gemini Live): **later, under Oracle's external mode** (Echo carries the audio),
   or nothing.
