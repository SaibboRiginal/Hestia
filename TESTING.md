# Hestia — Master Test Index

> Each service owns its test plan at `Hestia-<name>/tests/TESTING.md`.
> This file is the cross-service index and execution order reference.

## Test Marker Reference

```
pytest -m unit          Fast mocked tests (no LLM, no network)
pytest -m llm_live      Live LLM tests (requires local Ollama)
pytest -m api           FastAPI TestClient endpoint tests (no LLM)
pytest -m integration   Cross-service integration (Ollama + mocked Hub/Archive)
pytest -m format        Message formatting and output contract tests
```

Run everything: `pytest --tb=short -v` or `run-tests.bat`
Run critical only: `pytest -m "unit or api or format" --tb=short -v`

## Per-Service Test Plans

| Service | Test Plan | Priority |
|---------|-----------|----------|
| Oracle | [Hestia-Oracle/tests/TESTING.md](Hestia-Oracle/tests/TESTING.md) | 🔴 CRITICAL |
| Telegram | [Hestia-Telegram/tests/TESTING.md](Hestia-Telegram/tests/TESTING.md) | 🔴 CRITICAL |
| Athena | [Hestia-Athena/tests/TESTING.md](Hestia-Athena/tests/TESTING.md) | 🔴 CRITICAL |
| Hub | [Hestia-Hub/tests/TESTING.md](Hestia-Hub/tests/TESTING.md) | 🟡 HIGH |
| Archive | [Hestia-Archive/tests/TESTING.md](Hestia-Archive/tests/TESTING.md) | 🟡 HIGH |
| Hermes | [Hestia-Hermes/tests/TESTING.md](Hestia-Hermes/tests/TESTING.md) | 🟡 HIGH |
| Hecate | [Hestia-Hecate/tests/TESTING.md](Hestia-Hecate/tests/TESTING.md) | 🟡 HIGH |
| Chronos | [Hestia-Chronos/tests/TESTING.md](Hestia-Chronos/tests/TESTING.md) | 🟡 HIGH |
| Iris | [Hestia-Iris/tests/TESTING.md](Hestia-Iris/tests/TESTING.md) | 🟡 HIGH |
| Argus | [Hestia-Argus/tests/TESTING.md](Hestia-Argus/tests/TESTING.md) | 🟢 NORMAL |
| Hephaestus | [Hestia-Hephaestus/tests/TESTING.md](Hestia-Hephaestus/tests/TESTING.md) | 🟢 NORMAL |
| Scout | [Hestia-Scout/tests/TESTING.md](Hestia-Scout/tests/TESTING.md) | 🟢 NORMAL |
| Atlas | [Hestia-Atlas/tests/TESTING.md](Hestia-Atlas/tests/TESTING.md) | 🟢 NORMAL |
| Dummy | [Hestia-Dummy/tests/TESTING.md](Hestia-Dummy/tests/TESTING.md) | 🟢 NORMAL |
| Metis | [Hestia-Metis/tests/TESTING.md](Hestia-Metis/tests/TESTING.md) | 🟢 NORMAL |

## Banco di prova cloud (whole stack, no local PC)

Runs every service for real (WebUI .NET + Angular included) in a **Claude cloud session** or a **GitHub Codespace**,
then checks it like a user. Dossier: `docs/work/2026-10-19-banco-prova-cloud/`.

```
python tools/cloud_test.py          # no argument: starts Hestia if it is off, prints the login link + a short Italian guide (also `help`)
python tools/cloud_test.py all      # prepare (Docker, base images, .env) + up (build, start) + check
python tools/cloud_test.py check    # again: health, Hub registry, smoke calls, WebUI screenshots
python tools/cloud_test.py start    # up + login link in .cloud-test/login.txt (Codespaces: automatic on every start)
python tools/cloud_test.py token    # login link (Codespaces forwards the port through a proxy → token needed)
python tools/cloud_test.py logs oracle · down
python tools/cloud_test.py flows [area…]   # real user flows end to end (after `all`)
```

- Output: `.cloud-test/report.md` + `.cloud-test/screens/*.png` (git-ignored).
- `flows` (`tools/cloud_test/flows.py`, dossier `docs/work/2026-10-19-prove-reali-banco/`): areas hercules, hygieia, wardrobe,
  agenda, presence, settings, plugins, mcp, webui, transfer, vita (new modules), shell (Adesso, Scopri, chats, push) (none = all); report `.cloud-test/flows.md`, screenshots `.cloud-test/flows/`.
  Chat steps use the fake LLM's scripted tools: a message with `#tool <name> {json}` makes it call that tool once.
- Brain: `GEMINI_API_KEY` in the environment (cloud environment variable / Codespaces secret, never in the repo)
  → Oracle's models switch to Gemini; otherwise `tools/cloud_test/fake_ollama.py` answers «[LLM finto] …».
  The bench overlay passes it to Oracle as `ORACLE_KEY_GEMINI` (Oracle reads only `ORACLE_KEY_<NAME>`): on the bench
  the secret keeps the name `GEMINI_API_KEY`; on the real stack the key goes in `Hestia-Oracle/app/.env` as `ORACLE_KEY_GEMINI`.
- Telegram starts only with a (test) `TELEGRAM_BOT_TOKEN`; Google/Microsoft OAuth needs a person in a browser.
- Claude cloud network: Docker Hub rate-limits (429) and Debian's apt servers are blocked, Ubuntu's are allowed.
  The script takes images from `mirror.gcr.io`, builds Ubuntu 24.04 stand-ins for `python:3.12-slim` and
  `dotnet/aspnet:9.0` (same Python 3.12, same .NET runtime) and layers the session's interception CAs
  (`/root/.ccr/ca-bundle.crt`) into the base images. Codespaces: official images, untouched.
- Start a Codespace: *Code → Codespaces → «…» → New with options* (4-core, `.devcontainer/devcontainer.json`); the
  page asks for the optional test secrets `GEMINI_API_KEY`, `TELEGRAM_BOT_TOKEN` + `ALLOWED_USER_ID`, `GOOGLE_CLIENT_ID` +
  `GOOGLE_CLIENT_SECRET` (or set them once on GitHub → *Settings → Codespaces → Secrets*). Every start runs
  `cloud_test.py start` (output in `.cloud-test/start.log`, it waits up to 120 s for Docker); open the link in
  `.cloud-test/login.txt`. Ports stay private. «Docker is not installed» = the container was not built from
  the devcontainer: *Ctrl+Shift+P → Codespaces: Full Rebuild Container*. «Recovery mode» = the devcontainer failed to build
  (until 2026-10-22: the base image moved to Debian 13, where docker-in-docker does not install; now pinned to bookworm). No `.cloud-test` folder = the setup failed: see *Ctrl+Shift+P → Codespaces: View Creation Log*,
  or run `python tools/cloud_test.py start` in the terminal.
  Browser «ERR_INVALID_RESPONSE» on the link = the forwarded port talks HTTPS to the WebUI (plain HTTP): *Ports* tab →
  row 19015 → right click → *Change Port Protocol → HTTP* (the devcontainer now sets HTTP for 19015/19000).

## Setups that need Marko's devices (dossier `docs/work/2026-10-24-tutto-brainstorm-cindy`)

- **Garmin** (W4 B10): `pip` gets `garminconnect` with the Hecate image (`up-all.bat --build`). Telegram → Sistema →
  Dispositivi → «Collega Garmin» → «Inserisci» → email + password (+ the code Garmin mails, second form). Then
  «Leggi Garmin ora»: yesterday's run appears in Allenamento → attività, the night in Cura di sé → diario (sonno).
- **Phone** (W4 Cindy 32): put a long random `HECATE_PHONE_TOKEN` in `Hestia-Hecate/app/.env`; Tasker profile
  «Wi-Fi connesso/disconnesso» → HTTP Request POST `https://<tunnel>/api/gateway/phone/push`, header
  `X-Hestia-Phone-Token: <token>`, body `{"type":"state","wifi":"%WIFII_SSID","charging":%BATT_CHARGING}` (Wi-Fi names
  in Themis «Wi-Fi di casa»); profile «Notifica» of the bank app → body `{"type":"notification","app":"%an",
  "title":"%ntitle","text":"%ntext"}` → Spese shows a transaction to review. Telegram «Telefono» shows the last state.
- **Voice** (W4 Cindy 10/17): Telegram → Voce → «Registra la mia voce» (≥ 6 s); WebUI «Parla» with the TV on: the TV
  must not end in the transcript. «Parole» → add a name; after two corrections of the same word it is confirmed.
- **Spoken diary** (W4 B9): after the evening recap tap «Racconta la giornata», send a voice note → Cura di sé → diario.
- **.NET WebUI build** (W7): never built in the cloud sessions (no `dotnet` there; the bench builds it in Docker).
  `up-all.bat --build`, then open the WebUI: new sidebar (Cerca, Parla, Conversazioni, Sistema), Home «Adesso»,
  Chat «Cronologia» + «Detta». The `changes` frame («Ho fatto … Annulla») and the origin label need the new
  `OracleEvent.items` / `origin` fields: a reply from a routine must show «Avviato da …».
- **Images / ComfyUI** (W5 A1): on the PC with the GPU start ComfyUI with `--listen 0.0.0.0`; root `.env`
  `APOLLO_COMFYUI_URL=http://<pc>:8188`. ComfyUI → your txt2img workflow → *Save (API Format)* → WebUI Immagini →
  Flussi → upload it as «generico» (and «mascotte» for the pet). Then «Nuova immagine»: the job goes queued → running →
  done and Hermes says «Immagine pronta». Aspetto → pet → «Genera» uses the «mascotte» flow.
- **House / Home Assistant** (W5 A3): root `.env` `LARES_HA_URL` + `LARES_HA_TOKEN` (HA → profile → Security →
  Long-lived access tokens). WebUI Casa shows the rooms; star a light → it appears as a Home chip and in Telegram Casa.
  Themis «Tu in Home Assistant» = your `person.*` → leaving home sets the presence.
- **Web Push** (W2/W7 C15): `npx web-push generate-vapid-keys` once → root `.env` `HERMES_VAPID_PUBLIC_KEY`,
  `HERMES_VAPID_PRIVATE_KEY`, `HERMES_VAPID_SUBJECT=mailto:…`. WebUI Impostazioni → Personali → «Notifiche sul
  dispositivo» → Attiva (needs HTTPS or localhost). Close the tab, ask a reminder in 1 minute: the system notification
  opens the right page.
- **llama-server** (W1 D17, optional): `.gguf` in `LLAMACPP_MODELS_DIR`, `LLAMACPP_MODEL=<file>`, then
  `docker compose -f docker-compose.global.yml --profile llamacpp up -d llamacpp`; Sistema → Modelli shows the provider
  online and it goes first in the local chains.
- **Real Telegram** (all waves): every new area is in the menu (Scadenze, Persone, Alimentazione, Documenti, Immagini
  e aspetto, Casa, Oggi with /adesso and /scopri, Conversazioni with chat_tag/chat_list).

## Critical Regressions Log

> Any time a test is written because of a real user-facing bug, document it here.

| Date | Symptom | Test Added | Root Cause |
|------|---------|-----------|------------|
| 2026-10-19 | Coach plans the bodyweight as kg on an inverted row | Hercules `test_bodyweight_exercise_never_suggests_the_bodyweight_as_load` | Progression used the bodyweight-based load for every kind |
| 2026-10-19 | Self care suggests the AHA the evening after the retinol | Hygieia `test_after_a_retinol_evening_the_aha_says_not_today` | Steps done today sorted after the others, so the clash was never seen |
| 2026-10-19 | «Cosa mi metto … ufficio» ignores the occasion | Wardrobe `test_italian_labels_become_vocabulary_keys` | Occasions/styles saved and matched as labels, rules use vocabulary keys |
| 2026-10-19 | Chatting in the WebUI leaves the assistant «In attesa» | Oracle `test_webui_chat_counts_as_user_activity` | Presence pinged only when `notify_target` was set (Telegram) |
| 2026-10-19 | Coach/Self care sidebar entries show the «info» icon | `cloud_test.py flows plugins` (icon check) | Plugin manifests used icons the WebUI did not draw |
| 2026-10-19 | *Mappa* shows WebUI and Hermes offline after 3 min; a Hub restart forgets them | Hermes `TestHubKeepalive` | Hermes started its keepalive only if every first registration failed; the WebUI had none |
| 2026-10 | Google OAuth always failed (`Error 400 invalid_request`) | Hecate 7.13–7.25 | OOB redirect blocked by Google since 2023 |
| _first entry TBD_ | LLM returns `**bold**` instead of `<b>bold</b>` | Telegram 2.1.1, Oracle 1.8.13 | Format contract not enforced on all paths |
| _first entry TBD_ | Tool not called for calendar query | Oracle 1.8.1 | Agent loop pattern matching failed |
| _first entry TBD_ | "non voglio notifiche" not persisted | Oracle 1.8.6, 1.4.2 | Control extraction not triggered |

## Execution Order (Priority)

1. **Oracle** — unit tests first (agent_loop, chat_classifier, memory_intent)
2. **Telegram** — message format is the most user-visible path
3. **Oracle** — live LLM tool-calling (requires Ollama)
4. **Telegram** — all user paths (bot handlers, commands, formatters)
5. **Athena** — proactive cognition tests
6. **Hub → Archive → Hermes** — core infrastructure
7. **Hecate → Chronos → Iris** — gateway services
8. **Argus → Hephaestus** — organ services
9. **Scout → Atlas → Dummy** — domain/support modules
10. **Governance** — check_test_sync.py gate

---

_Each service's `tests/TESTING.md` is that service's single source of truth for test status._
_Update the per-service file with every test change — not this index._
