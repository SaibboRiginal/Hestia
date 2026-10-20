# SPEC — Voice module (Hestia-Echo): speech-to-text and text-to-speech for every client

| | |
|---|---|
| **Version** | 1.0 |
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
2. **Profiles like Oracle a blocchi**: named providers (local and cloud), an ordered **chain** for listening and one for
   speaking; a step that fails or has no key is skipped and the next one is tried.
3. **Telegram**: a voice note is transcribed and then handled **as a normal chat message** (same session, same queue when
   the assistant is unavailable). The assistant answers by voice according to the reply mode (§5).
4. **WebUI**: microphone in the chat composer, «ascolta» on every assistant reply, automatic playback in the same reply
   mode; replies are spoken sentence by sentence while they stream.
5. **Oracle drops Whisper**: audio inside documents is transcribed by asking Echo; Oracle keeps only what is an LLM
   (models that hear audio natively).
6. **Plugin «Voce»** (core): try voices, test the microphone, see the chain and the last transcriptions.

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
- **Transport**: JSON through the Hub envelope, audio as base64 (`audio_b64`). Voice notes and spoken sentences are
  small (a minute of opus ≈ 100 KB); Echo refuses inputs over `echo.stt.max_seconds`. No direct URLs.
- **Node**: the PC (with Oracle), because local Whisper and Kokoro want CPU/GPU; Piper also runs on a Raspberry Pi.
- **ffmpeg** in the Echo image converts any input (ogg, webm, m4a, mp3, wav, mp4) to 16 kHz mono for the engines and
  produces the output format the client asks for (`ogg_opus` for Telegram voice, `mp3`/`webm` for browsers).

## 4. Providers and chains

Same model as Oracle a blocchi, smaller:

| Type | Listens (STT) | Speaks (TTS) | Needs |
|---|---|---|---|
| `local` (built in) | faster-whisper (`tiny`…`large-v3`, CPU int8, GPU if present) | Piper (fast, light) and Kokoro (more natural, Italian voices) | nothing; models download on first use into a volume |
| `openai` (OpenAI-compatible audio API) | `/v1/audio/transcriptions` | `/v1/audio/speech` | URL + key. Covers OpenAI, Groq (free Whisper large-v3-turbo), and self-hosted servers (Speaches, LocalAI) |
| `google` | Cloud Speech-to-Text (REST, ogg/opus native) | Cloud Text-to-Speech (Italian Neural2/Wavenet/Chirp voices) | API key |

- Env holds only addresses and keys: `ECHO_PROVIDER_<NAME>=<type>[@<url>]` and `ECHO_KEY_<NAME>` (secrets in
  `Hestia-Echo/app/.env`, documented in `.env.example`). A provider without its key is skipped by every chain.
- **Chains** (Themis, declared by Echo):
  - `echo.stt.chain` — ordered list of `provider:model`, default `["local:small"]`.
  - `echo.tts.chain` — ordered list of `provider:voice`, default `["local:piper/it_IT-paola-medium"]`.
  - A step that errors, times out or has no key is skipped (`event=voice_step_skipped`, `[🔄]` on fallback) and the
    next one is tried; quota errors skip the step until `echo.chain.cooldown_minutes`.
- `GET /api/voice/voices` lists, per provider, the models/voices available now (local ones installed + downloadable,
  cloud ones from the provider API), so the Sistema panel and the plugin show choices instead of free text.

## 5. Settings (Themis, declared by Echo with `settings_client.setting`)

| Key | Type | Default | Meaning |
|---|---|---|---|
| `echo.stt.chain` | list | `["local:small"]` | listening chain (§4) |
| `echo.tts.chain` | list | `["local:piper/it_IT-paola-medium"]` | speaking chain (§4) |
| `echo.language` | enum | `it` | language for transcription and synthesis (`auto` allowed for STT) |
| `echo.reply.mode` | enum | `mirror` | when the assistant answers by voice: `mirror` (only when I spoke), `always`, `never` |
| `echo.tts.speed` | number | `1.0` | speaking rate |
| `echo.tts.max_chars` | number | `1200` | longer replies: voice reads the first part and says the rest is in the text |
| `echo.stt.max_seconds` | number | `600` | longest audio accepted |
| `echo.chain.cooldown_minutes` | number | `60` | how long a step that hit its quota is skipped |

`echo.reply.mode` is a preference with three behaviours, not an on/off switch hiding a feature. No new env tunables.

## 6. API (Echo, all through the Hub; `Hestia-Swagger/swagger.yml` updated)

- `POST /api/voice/transcribe` `{audio_b64, mime_type, language?}` → `{text, language, duration_s, provider, model}`;
  422 on empty/too long audio, 503 when every chain step failed.
- `POST /api/voice/speak` `{text, format: ogg_opus|mp3|webm|wav, voice?}` → `{audio_b64, mime_type, duration_s,
  provider, voice}`. Text is cleaned first: markdown, links, code blocks and emoji are not read aloud.
- `GET /api/voice/voices` → providers, their state (ready / no key / downloading / failed), models and voices.
- `GET /api/voice/recent` → last 20 operations in memory (kind, provider, duration, ms, ok) for the plugin; transcripts
  themselves are **not** kept by Echo (they live in the chat session in Archive like any message).
- `/health`, Hub registration, `hestia_common` startup and logging like every module.

No MCP tools in this version: audio is not useful to an LLM, and the chat already receives the transcript as text.

## 7. Clients

**Telegram**
- `voice` and `video_note` messages: download → transcribe → the bot shows «🎙️ <i>testo capito</i>» (edited in place
  into the status message) → the text goes into the **normal chat path** (`handle_text` flow: session, streaming, queue
  while unavailable). The transcript is what is saved in the session.
- `audio` files (music, recordings sent as files) keep the document path (transcribe and summarize), now served by Echo
  through Oracle.
- Reply by voice (per `echo.reply.mode`): when the streamed reply is complete, the bot asks Echo for `ogg_opus` and sends
  it with `sendVoice` under the text reply (the text always stays, so nothing is lost).
- When transcription fails: `[🔄]` fallback to today's document path (an LLM that hears audio, if the chain has one);
  if that also fails, a generic message: «Non riesco ad ascoltare il vocale adesso, puoi scrivermelo?» (no module names).

**WebUI** (Angular, `DESIGN-SYSTEM.md`, stroke icons, no emoji)
- Composer: microphone button (tap to start, tap to stop; hold on phone). Browser `MediaRecorder` (webm/opus or mp4 on
  Safari) → WebUI backend `POST /api/voice/transcribe` → Hub → Echo. The text appears in the composer and is **sent
  automatically** after 2 s with an «annulla» chip (cancel keeps it in the composer to edit), so a voice message
  behaves like on Telegram.
- Every assistant reply gets an «ascolta» icon. In `mirror` mode (after a voice message) or `always`, playback starts on
  its own: the streaming reply is cut into sentences and each sentence is spoken as soon as it is complete
  (this is the "stream": first sound after the first sentence, not after the whole reply).
- Live dictation with partial text while speaking: chunks of 3 s sent while recording, partial transcript shown in the
  composer, final transcript replaces it on stop.

**Oracle**
- `local_models.transcribe_audio` and the WhisperX code go away; analyser and archiver call Echo through the Hub.
- `oracle.documents.whisper_model` is removed (its role moves to `echo.stt.chain`); `oracle.documents.audio_models`
  stays (it is about LLMs).

## 8. Plugin «Voce» (core, in Echo's `ui/`)

One page in the Sistema area (core order free between existing core decades, chosen at implementation):
- **Prova**: text box + voice picker + «parla»; microphone + «trascrivi» to check what the chain understands.
- **Catena**: the two chains with the state of every step (ready / no key / downloading / failed), editable through the
  usual Themis settings controls.
- **Ultime operazioni**: `GET /api/voice/recent`.
Icons: mic, speaker, waveform (added to the WebUI icon set if missing).

## 9. Phases (each: tests green, docs updated, PROGRESS ticked)

- **V1 Echo core** — service skeleton (template), providers `local`/`openai`/`google`, chains with cooldown, ffmpeg
  conversion, text cleaning for TTS, endpoints, settings, Dockerfile with model volume, compose (global + cloud test),
  CI matrix, `hestia-echo.md`, swagger, `.env.example`, unit/api tests with fake engines.
- **V2 Oracle without Whisper** — analyser/archiver call Echo; WhisperX code and setting removed; tests.
- **V3 Telegram** — voice note → chat message; voice reply per mode; fallback; queue while unavailable; tests.
- **V4 WebUI** — .NET `VoiceController` (Hub route), composer mic, auto-send with «annulla», «ascolta», sentence
  streaming playback, live dictation; icons.
- **V5 Plugin «Voce»** — page, recent operations, voice list.
- **V6 Docs** — `CLAUDE.md` rule, `docs/ARCHITECTURE.md`, `docs/AI-GUIDE.md`, `readme.md`, `architecture-and-flow-map.md`,
  module docs (Echo, Oracle, Telegram, WebUI), root `CHANGELOG.md`; PR, CI green, merge.

**Acceptance**
1. A Telegram voice note «aggiungi al diario che oggi ho dormito male» is transcribed, shown, and handled exactly like
   the same sentence typed (the diary tool runs).
2. With `echo.reply.mode = mirror` the reply comes back as text **and** a Telegram voice message; a typed message gets
   text only.
3. In the WebUI the microphone sends a voice message; the reply starts speaking after its first sentence.
4. With `echo.stt.chain = ["groq:whisper-large-v3-turbo", "local:small"]` and no Groq key, transcription works locally
   and the log shows the skipped step.
5. An audio file attached in chat is still transcribed and summarized, with no Whisper code left in Oracle.
6. Echo down: Telegram falls back (document path) or says it cannot listen right now; nothing is lost or silent.

## 10. Choices for Marko (defaults in **bold**, used if you just say ok)

1. Name: **Hestia-Echo** (the nymph who is only a voice), port **19021**.
2. Local voice: **Piper first** (fast, also on a Raspberry Pi) with Kokoro selectable in the chain; or Kokoro first
   (more natural, slower on CPU).
3. Reply by voice default: **`mirror`** (voice only when you spoke), or `always` / `never`.
4. WebUI voice message: **sent automatically with «annulla» for 2 s**, or put in the composer for you to send.
