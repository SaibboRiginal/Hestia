# One-click setup: Hestia installs, configures and updates itself on Windows, Linux and macOS

| | |
|---|---|
| **Version** | 1.0 |
| **Source** | user via Project thread (Marko 2026-10-30: «possiamo fare un setup in one click per windows e linux e mac os? che fa letteralmente tutto con fallback e no fail? magari si puo pensare che hestia si costruisce da sola? si mette su da sola ma essendo su docker magari non so se ha accesso al host?») |
| **Status** | Draft — waiting for Marko's ok |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).

## 1. Today (verified in code, main `1e8bc9b`)

- **Windows only, by hand.** `up-all.bat` checks that Docker answers, creates `hestia_net`, runs
  `docker compose -f docker-compose.global.yml up -d [--build]`. `make_env.bat` makes a venv with `py -3.12`.
  `up-rpi.bat` for the Pi. No `.sh` equivalent for Linux/macOS (only `Hestia-Atlas/run_host.sh`).
- **Prerequisites are the user's job**: Docker Desktop, git, Python 3.12 (for `tools/init_env.py`), Ollama on the
  host (`OLLAMA_URL=http://host.docker.internal:11434`, compose line 133), NVIDIA driver for the optional
  `llamacpp` profile.
- **`.env` by hand**: `tools/init_env.py` copies every `.env.example`; then the user edits `TELEGRAM_BOT_TOKEN`,
  `ALLOWED_USER_ID`, `HESTIA_DB_PASSWORD` (default `super_secret_local_password`!), keys of cloud models, Google
  OAuth… (`docs/SETUP.md`). Nothing generates random secrets.
- **Hestia already has a hand on the host's Docker**: `hestia_hephaestus` mounts `/var/run/docker.sock` (rw) and the
  repo at `/repo` (Forge merges and restarts `hestia_<svc>`); `hestia_argus` mounts the socket read-only (logs) and
  the immune system restarts a module that stays down. So "Hestia rebuilds itself" exists in part already.
- `tools/cloud_test.py` already knows how to prepare Docker + `.env` + build + health check in a cloud session or
  Codespace: useful code to reuse, and a free test bench for the installer.
- No first-run wizard in WebUI or Telegram.

## 2. Can it be done? (the honest answer)

| Question | Answer |
|---|---|
| One click on Windows, Linux, macOS? | **Yes, almost.** One command (or one double-clickable file) does everything. The limits are the OS's, not ours: the **admin password once**; on Windows a **reboot** if WSL2 was missing (the installer resumes by itself after it); on Windows/macOS Docker Desktop wants its **licence accepted the first time** it opens. |
| "No fail"? | **No silent fail.** Nobody can promise success without internet, with virtualization off in the BIOS or a full disk. What we promise: every step checks before acting (idempotent), retries with backoff, has a fallback, saves where it got to, and rerunning the same command resumes/repairs. If it really cannot go on it stops with **one sentence saying the one thing to do** (e.g. «attiva la virtualizzazione nel BIOS»). |
| Can Hestia install itself, from inside Docker? | **Not the first time**: a container cannot install Docker (it needs Docker to exist). So a small script on the host is unavoidable for the bootstrap. |
| After that, can it build/configure/update itself? | **Yes.** Hephaestus already has the Docker socket and the repo: it can pull updates, rebuild, health check, roll back. Ollama models can be pulled through Ollama's own API from a container (`/api/pull`), no host access needed. |
| Does it have host access? | Through the Docker socket it has **Docker** on the host, which is equivalent to root. That is why we **do not give it to any new container**: it stays only on Hephaestus (rw) and Argus (ro), as today. Things that truly live outside Docker (installing Docker/Ollama/drivers) stay in the host installer, run by the user. |

## 3. Goal

A person with a fresh PC types one line (or double-clicks one file), says yes to the admin prompt, and ends up in
the browser on Hestia's welcome wizard, with everything running. From then on nothing is edited by hand: the wizard
asks for the few secrets, Hestia updates itself from the WebUI.

## 4. Scope and design

### 4.1 Host installer (bootstrap) — `install.sh` (Linux + macOS) and `install.ps1` (Windows)

How you start it:

- Windows: `irm https://raw.githubusercontent.com/SaibboRiginal/Hestia/main/install.ps1 | iex` in PowerShell, or
  double-click `Installa-Hestia.cmd` (downloaded from the README; it only launches the `.ps1` with
  `-ExecutionPolicy Bypass`).
- Linux / macOS: `curl -fsSL https://raw.githubusercontent.com/SaibboRiginal/Hestia/main/install.sh | bash`;
  macOS also `Installa Hestia.command` (double-click).
- Same script for: first install, repair (`--repair`, also the default when it finds an install), update
  (`--update`), uninstall (`--uninstall`, keeps data; `--purge` deletes them after a typed confirmation).

Steps (each one = check → act → verify, 3 tries with backoff 2/4/8 s, then the fallback, then stop with a clear
sentence). State in `<install dir>/.hestia-install/state.json` + log `install.log` (no secrets in either).

| # | Step | Windows | Linux | macOS |
|---|---|---|---|---|
| 0 | Preflight: OS/arch, RAM ≥ 8 GB (warn), disk ≥ 30 GB free, internet, virtualization, ports 19000-19030/5432 free | ✔ | ✔ | ✔ |
| 1 | git (fallback: download the zip of `main`, switch to git later) | winget `Git.Git` → direct installer | apt/dnf/pacman/zypper | `xcode-select --install` → Homebrew |
| 2 | Docker | WSL2 (`wsl --install`, reboot + resume via RunOnce) → winget `Docker.DockerDesktop` → direct installer | `get.docker.com` → distro package; add user to `docker` group | Homebrew cask → `.dmg` → **Colima** (no GUI, no licence) as last fallback |
| 3 | Start Docker and wait until `docker info` answers (up to 5 min, progress shown) | ✔ | systemd | ✔ |
| 4 | GPU: detect NVIDIA; Linux installs `nvidia-container-toolkit`; none = CPU + cloud models (said once, not an error) | driver check | ✔ | Metal via native Ollama |
| 5 | Ollama on the host (native, so Mac uses Metal and Windows the GPU without extra setup) | winget `Ollama.Ollama` | official `install.sh` | Homebrew → app |
| 6 | Hestia: clone into `C:\Hestia` / `~/Hestia` (asks only if it exists and is not Hestia) or `git pull` | ✔ | ✔ | ✔ |
| 7 | `.env` files: `tools/init_env.py` run **inside** a throwaway `python:3.12-slim` container (no Python on the host); random `HESTIA_DB_PASSWORD`, `WEBUI_SECRET_KEY`, `WEBUI_ADMIN_SECRET`, `WEBUI_ICS_KEY` generated only where empty | ✔ | ✔ | ✔ |
| 8 | `hestia_net`, `docker compose build` (retry per service, then `--no-cache` for the one that failed), `up -d` | ✔ | ✔ | ✔ |
| 9 | Wait until the Hub reports every core module healthy (up to 10 min); otherwise say which one and show its last 20 log lines | ✔ | ✔ | ✔ |
| 10 | Open the browser on `http://localhost:19015/benvenuto` and add a desktop shortcut «Hestia» | ✔ | ✔ | ✔ |

- Docker Desktop and Ollama set to start at login; containers already have `restart: unless-stopped`, so after a
  reboot Hestia comes back alone.
- `up-all.bat` stays (Marko's habit) and gets a twin `up-all.sh`; both become thin wrappers of the same logic.
- What the installer never does: write personal data or tokens, touch an existing `.env` value, delete data
  without `--purge` + typed confirmation, disable antivirus/firewall.
- Not in v1: signed `.exe`/`.pkg` installers (code signing costs money; the `.cmd`/`.command` launchers cover the
  double-click). Can wrap the same scripts later.

### 4.2 First-run wizard «Benvenuto» (WebUI, replaces editing `.env`)

Shown while setup is not complete (no WebUI admin account yet). Steps, each skippable except the first:

1. **Account**: create the WebUI admin login.
2. **Cervello**: local (lists the models Ollama has; suggests one by detected VRAM; «Scarica» pulls it with a
   progress bar through Oracle → Ollama `/api/pull`) and/or cloud (paste a key, «Prova» does one real call).
   Choices become Themis values (the user is the one choosing, so no extra confirmation).
3. **Telegram**: paste the BotFather token, «Prova» checks it; then the wizard shows a one-time code «scrivi questo
   codice al bot»; the bot, in setup mode, answers only to that code and gives the wizard the sender's id → no need
   to know your own Telegram id. `ALLOWED_USER_ID` stays fail-closed for everyone else.
4. **Google** (optional): link Calendar/Gmail with the existing Hecate OAuth flow.
5. **Backup** (optional): passphrase, shown with «salvala nel tuo password manager».
6. **Controllo finale**: health of every module (Hub registry) in plain words, «Tutto pronto».

Where secrets go: env stays the home of secrets (rule). The wizard sends them through the Hub to a **small setup
endpoint of Hephaestus** (it already owns `/repo` and the Docker socket): it writes **only whitelisted keys** into
the right `.env`, never echoes them back, then restarts only the affected container and waits for its health.
Every write logs `event=setup_secret_set key=<name> service=<svc>` (never the value). After setup is complete the
endpoint accepts writes only from a logged-in admin (Impostazioni → Sistema → «Chiavi e collegamenti» reuses the
same screen, so changing a key later is also not a `.env` edit).

### 4.3 Hestia updates itself — «Aggiorna Hestia»

- Hephaestus checks `origin/main` once a day as an **agenda job** (Chronos rule, user-editable) and, if there is
  something new, Hermes asks «C'è un aggiornamento (N novità). Installo?».
- On yes: `git pull` in `/repo`, rebuild **only the services whose folder changed**, health check, automatic
  rollback to the previous commit on failure (same machinery as the Forge deploy). Local Forge work is never lost:
  if `main` diverged it asks instead of forcing.
- Also a button in Sistema and a Telegram command. Host-side things (new Docker/Ollama version) stay with the
  installer's `--update`, which the notice suggests when needed.

### 4.4 Tests

- CI: `shellcheck install.sh`, PowerShell parse + `-DryRun` on `windows-latest`, `install.sh --dry-run` on
  `ubuntu-latest` and `macos-latest`.
- Real run of `install.sh` end to end on `ubuntu-latest` (Docker available) and in the cloud bench.
- Unit/api tests for the Hephaestus setup endpoint (whitelist, no value in logs/responses, restart called) and the
  self-update (changed-folder → services map, rollback).
- Playwright flow `setup` in `tools/cloud_test/flows.py` for the wizard.
- Windows/macOS real install: **Marko** (we cannot run Docker Desktop in CI).

### 4.5 Phases

- **P1** `install.sh` (Linux + macOS) + `up-all.sh` + CI checks.
- **P2** `install.ps1` + `Installa-Hestia.cmd` (Windows, WSL2 resume).
- **P3** Hephaestus setup endpoint + wizard «Benvenuto» + Telegram one-time code.
- **P4** «Aggiorna Hestia» (agenda job, notice, selective rebuild, rollback).
- **P5** Docs: README quick start becomes one line; `docs/SETUP.md`, `TESTING.md`, module docs, swagger, ARCHITECTURE.

## 5. New feature checklist (`docs/REGOLE-DI-MARKO.md`)

1. Real job for the owner: install on any PC without touching files; update without a terminal.
2. Owner module (R1): host installer = repo tool (outside the stack); secrets writer + self-update = Hephaestus
   (already owns repo + socket + deploy); wizard UI = WebUI; Telegram code = Telegram; model download = Oracle.
3. Configuration: no new env tunables; update check time = agenda rule; installer flags are CLI arguments.
4. Push or poll: update check is an agenda job, the notice is a Hermes push; manual button + Telegram command.
5. Who confirms: the user does every step of the wizard and says yes to every update; the assistant never installs
   or writes keys by itself.
6. WebUI pages with stroke icons, no emoji; Telegram command «aggiorna» + the setup code.
7. Stop, correct, undo: rerun the installer (`--repair`); keys changeable from Sistema; update = automatic rollback
   and manual «Torna alla versione prima».
8. Docs that change: `readme.md`, `docs/SETUP.md`, `TESTING.md`, `Hestia-Hephaestus/hestia-hephaestus.md`,
   `Hestia-WebUI/hestia-webui.md`, `Hestia-Telegram/hestia-telegram.md`, `Hestia-Swagger/swagger.yml`,
   `docs/ARCHITECTURE.md`, `.env.example` comments.

## 6. Acceptance criteria

- Fresh Ubuntu VM: one `curl … | bash` → browser on «Benvenuto», all core modules healthy, no file edited.
- Same command run again on a working install: nothing broken, ends with «Hestia è già a posto».
- Kill the network mid-install, rerun: resumes from the step it reached.
- Windows without WSL2: installer reboots once, resumes alone, ends on «Benvenuto».
- Wizard done → Telegram answers Marko and nobody else; no secret visible in logs, API responses or git status.
- «Aggiorna Hestia» with a broken commit → rollback, Hestia healthy on the previous version, notice says so.
- No personal data in any tracked file.

## 7. Open points for Marko

1. Ok to go with P1–P5 as above?
2. Secrets written by Hephaestus into `.env` (proposed) vs an encrypted secret store in Archive (bigger change of a
   global rule).
3. macOS last fallback Colima (no Docker Desktop licence) — ok?
