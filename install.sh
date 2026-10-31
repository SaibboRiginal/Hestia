#!/usr/bin/env bash
# Hestia installer for Linux (main target) and macOS (only the simple path: Homebrew + Docker Desktop).
# Written for bash 3.2 too (macOS): no mapfile, no ${var,,}, empty arrays expanded with ${a[@]+"${a[@]}"}, and
# ${VAR} in braces before a non-ASCII character (3.2 glues the first UTF-8 byte to the name).
#
#   curl -fsSL https://raw.githubusercontent.com/SaibboRiginal/Hestia/main/install.sh | bash
#   bash install.sh [--dir PATH] [--channel stabile|novita] [--update] [--uninstall [--purge]] [--dry-run] [--yes]
#
# Every step checks before acting, retries (2/4/8 s), has a fallback, and records where it got to: running the same
# command again resumes or repairs. When it truly cannot go on it stops with one sentence saying what to do.
# It never prints or logs secrets, never overwrites an existing .env value, never deletes data without --purge.
# SPEC: docs/work/2026-10-30-setup-un-click
set -Eeuo pipefail

HESTIA_REPO_URL="${HESTIA_REPO_URL:-https://github.com/SaibboRiginal/Hestia.git}"
HESTIA_TARBALL_URL="${HESTIA_TARBALL_URL:-https://codeload.github.com/SaibboRiginal/Hestia/tar.gz/refs/heads/main}"
HESTIA_DIR="${HESTIA_DIR:-$HOME/Hestia}"
CHANNEL="${HESTIA_CHANNEL:-stabile}"
ACTION="install"
RAM_GB=0
FREE_GB=0
PURGE=0
DRY_RUN=0
OPEN_BROWSER=1
WEBUI_URL="http://localhost:19015"
SETUP_URL="$WEBUI_URL/benvenuto"
HUB_URL="http://localhost:19001"
PROJECT="hestia"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/hestia-install"
LOG_FILE="$STATE_DIR/install.log"
STATE_FILE="$STATE_DIR/state"
SUDO=""
DOCKER=(docker)
OS=""
PKG=""
VERSION_TAG=""
NOTES=()

# ── output ─────────────────────────────────────────────────────────────────────────────────────────────────────
say()  { printf '\033[1;33m[Hestia]\033[0m %s\n' "$*"; log "say msg=\"$*\""; }
ok()   { printf '\033[1;32m[Hestia]\033[0m %s\n' "$*"; log "ok msg=\"$*\""; }
note() { NOTES+=("$*"); }
log()  { mkdir -p "$STATE_DIR" 2>/dev/null && printf '%s event=%s\n' "$(date -u +%FT%TZ)" "$*" >> "$LOG_FILE" || true; }

fail() {
  printf '\n\033[1;31m[Hestia] Mi sono fermato:\033[0m %s\n' "$1"
  printf '         Rilancia lo stesso comando quando hai fatto: riprendo da qui.\n'
  printf '         Dettagli: %s\n' "$LOG_FILE"
  log "install_failed reason=\"$1\""
  exit 1
}

trap 'log "[🔄] unexpected_error line=$LINENO cmd=\"$BASH_COMMAND\""' ERR

usage() {
  cat <<'TXT'
Hestia installer (Linux, macOS)
  --dir PATH            install folder (default ~/Hestia)
  --channel stabile     latest release, ready-made images (default)
  --channel novita      latest code on main, built here
  --update / --repair   same as no option: resume, repair, update
  --uninstall [--purge] stop Hestia (data kept); --purge also deletes data after typing CANCELLA
  --dry-run             only print what it would do
  --no-browser          do not open the browser at the end
TXT
  exit 0
}

# ── helpers ────────────────────────────────────────────────────────────────────────────────────────────────────
run() {  # run a command (array form); in --dry-run only print it
  if [ "$DRY_RUN" = 1 ]; then printf '  [dry-run] %s\n' "$*"; return 0; fi
  log "run cmd=\"$*\""
  "$@" >> "$LOG_FILE" 2>&1
}

run_sh() {  # run a shell string (pipes); in --dry-run only print it
  if [ "$DRY_RUN" = 1 ]; then printf '  [dry-run] %s\n' "$1"; return 0; fi
  log "run_sh cmd=\"$1\""
  bash -c "$1" >> "$LOG_FILE" 2>&1
}

retry() {  # retry <what> <cmd...>: 3 tries, backoff 2/4/8 s
  local what="$1"; shift
  local delay=2 i
  for i in 1 2 3; do
    if "$@"; then return 0; fi
    [ "$i" = 3 ] && break
    log "[🔄] retry what=\"$what\" attempt=$i next_in=${delay}s"
    say "$what: non è andata, riprovo tra ${delay}s…"
    sleep "$delay"; delay=$((delay * 2))
  done
  return 1
}

has() { command -v "$1" >/dev/null 2>&1; }

state_done() { [ -f "$STATE_FILE" ] && grep -qx "$1" "$STATE_FILE"; }
state_mark() { [ "$DRY_RUN" = 1 ] && return 0; mkdir -p "$STATE_DIR"; state_done "$1" || echo "$1" >> "$STATE_FILE"; }

dk() { "${DOCKER[@]}" "$@"; }
compose() {
  local files=(-f docker-compose.global.yml) version="${VERSION_TAG#v}" cmd=("${DOCKER[@]}")
  if [ -n "$VERSION_TAG" ] && [ -f "$HESTIA_DIR/docker-compose.images.yml" ]; then files+=(-f docker-compose.images.yml); fi
  # sudo drops the environment: pass the version explicitly.
  [ "${cmd[0]}" = sudo ] && cmd=(sudo env "HESTIA_VERSION=$version" docker)
  (cd "$HESTIA_DIR" && HESTIA_VERSION="$version" "${cmd[@]}" compose -p "$PROJECT" "${files[@]}" "$@")
}

# ── 0. preflight ───────────────────────────────────────────────────────────────────────────────────────────────
detect_os() {
  case "$(uname -s)" in
    Linux)  OS=linux ;;
    Darwin) OS=mac ;;
    *) fail "questo installer è per Linux e macOS. Su Windows usa Installa-Hestia.cmd (o install.ps1)." ;;
  esac
  if [ "$(id -u)" != 0 ]; then
    has sudo || [ "$OS" = mac ] || fail "serve 'sudo' (o lancia come root)."
    SUDO="sudo"
  fi
  if [ "$OS" = linux ]; then
    if has apt-get; then PKG=apt; elif has dnf; then PKG=dnf; elif has yum; then PKG=yum
    elif has pacman; then PKG=pacman; elif has zypper; then PKG=zypper; elif has apk; then PKG=apk; fi
  else
    has brew && PKG=brew
  fi
  log "os os=$OS arch=$(uname -m) pkg=${PKG:-none}"
}

pkg_install() {  # pkg_install <package...>
  case "$PKG" in
    apt)    run $SUDO apt-get update -qq && run $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$@" ;;
    dnf)    run $SUDO dnf install -y -q "$@" ;;
    yum)    run $SUDO yum install -y -q "$@" ;;
    pacman) run $SUDO pacman -Sy --noconfirm --needed "$@" ;;
    zypper) run $SUDO zypper --non-interactive install "$@" ;;
    apk)    run $SUDO apk add --no-cache "$@" ;;
    brew)   run brew install "$@" ;;
    *) return 1 ;;
  esac
}

preflight() {
  say "Controllo il computer…"
  local parent
  if [ "$OS" = linux ]; then
    RAM_GB=$(( $(awk '/MemTotal/ {print $2}' /proc/meminfo) / 1024 / 1024 ))
  else
    RAM_GB=$(( $(sysctl -n hw.memsize) / 1024 / 1024 / 1024 ))
  fi
  parent="$HESTIA_DIR"; while [ ! -d "$parent" ]; do parent="$(dirname "$parent")"; done
  FREE_GB=$(( $(df -Pk "$parent" | awk 'NR==2 {print $4}') / 1024 / 1024 ))
  log "preflight ram_gb=$RAM_GB free_gb=$FREE_GB"
  [ "$RAM_GB" -lt 8 ] && note "Hai ${RAM_GB} GB di RAM: Hestia funziona, ma per i modelli locali ne servono almeno 16. Usa i modelli nel cloud."
  if [ "$FREE_GB" -lt 20 ]; then
    fail "servono almeno 20 GB liberi (meglio 30) su $parent, ce ne sono ${FREE_GB}. Libera spazio."
  fi
  [ "$FREE_GB" -lt 30 ] && note "Spazio libero: ${FREE_GB} GB. Basta per Hestia; per i modelli locali grandi potrebbe non bastare."
  has curl || pkg_install curl || fail "manca 'curl' e non riesco a installarlo."
  retry "Connessione a internet" curl -fsS --max-time 15 -o /dev/null "${HESTIA_REPO_URL%.git}.git/info/refs?service=git-upload-pack" \
    || fail "non riesco a raggiungere github.com: controlla la connessione a internet."
  if [ "$OS" = linux ] && [ "$(uname -m)" = x86_64 ] && ! grep -Eq 'vmx|svm|hypervisor' /proc/cpuinfo; then
    note "La virtualizzazione non risulta attiva nel BIOS: a Docker di solito non serve su Linux, ma se qualcosa non parte attivala."
  fi
}

ports_check() {
  # Only on a first install: a running Hestia of course holds its own ports.
  dk ps --format '{{.Names}}' 2>/dev/null | grep -q '^hestia_hub$' && return 0
  local busy="" port
  for port in 19001 19002 19015 5432; do
    if { has ss && ss -ltn 2>/dev/null | grep -q "[:.]$port "; } || \
       { has lsof && lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; }; then
      busy="$busy $port"
    fi
  done
  [ -n "$busy" ] && fail "queste porte sono già occupate da un altro programma:$busy. Chiudilo e rilancia."
  return 0
}

# ── 1. git ─────────────────────────────────────────────────────────────────────────────────────────────────────
ensure_git() {
  has git && return 0
  say "Installo git…"
  if [ "$OS" = mac ]; then
    [ -n "$PKG" ] && retry "Installazione di git" pkg_install git && return 0
    run xcode-select --install || true
    fail "su macOS serve git: conferma la finestra «Strumenti da riga di comando» che si è aperta (oppure installa Homebrew da https://brew.sh)."
  fi
  retry "Installazione di git" pkg_install git && return 0
  note "git non si è installato: scarico Hestia come archivio (gli aggiornamenti useranno git quando ci sarà)."
  return 0
}

# ── 2–3. Docker ────────────────────────────────────────────────────────────────────────────────────────────────
docker_ready() {
  if docker info >/dev/null 2>&1; then DOCKER=(docker); return 0; fi
  if [ -n "$SUDO" ] && sudo -n docker info >/dev/null 2>&1; then DOCKER=(sudo docker); return 0; fi
  if [ -n "$SUDO" ] && [ "$OS" = linux ] && sudo docker info >/dev/null 2>&1; then DOCKER=(sudo docker); return 0; fi
  return 1
}

install_docker_linux() {
  say "Installo Docker (ci vuole qualche minuto)…"
  if retry "Installazione di Docker" run_sh "curl -fsSL https://get.docker.com | $SUDO sh"; then return 0; fi
  log "[🔄] docker_fallback via=distro_package"
  case "$PKG" in
    apt) pkg_install docker.io docker-compose-v2 || pkg_install docker.io docker-compose-plugin ;;
    dnf|yum) pkg_install docker docker-compose-plugin || pkg_install moby-engine docker-compose ;;
    pacman) pkg_install docker docker-compose ;;
    zypper) pkg_install docker docker-compose ;;
    apk) pkg_install docker docker-cli-compose ;;
    *) false ;;
  esac || fail "non riesco a installare Docker. Installalo seguendo https://docs.docker.com/engine/install/ e rilancia."
}

ensure_compose() {
  dk compose version >/dev/null 2>&1 && return 0
  log "[🔄] compose_missing installing_plugin"
  case "$PKG" in
    apt) pkg_install docker-compose-plugin || pkg_install docker-compose-v2 ;;
    dnf|yum) pkg_install docker-compose-plugin ;;
    *) false ;;
  esac && dk compose version >/dev/null 2>&1 && return 0
  # Last fallback: the official compose plugin binary, user-wide.
  local arch; arch="$(uname -m)"; [ "$arch" = arm64 ] && arch=aarch64
  run mkdir -p "$HOME/.docker/cli-plugins"
  retry "Download di docker compose" run curl -fsSL -o "$HOME/.docker/cli-plugins/docker-compose" \
    "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-$arch" \
    && run chmod +x "$HOME/.docker/cli-plugins/docker-compose" && dk compose version >/dev/null 2>&1 \
    || fail "manca 'docker compose' e non riesco a installarlo."
}

wait_docker() {  # wait_docker <seconds> <message>
  local limit="$1" waited=0
  [ "$DRY_RUN" = 1 ] && return 0
  say "$2"
  until docker_ready; do
    [ "$waited" -ge "$limit" ] && return 1
    sleep 5; waited=$((waited + 5))
    [ $((waited % 30)) = 0 ] && say "…aspetto ancora Docker (${waited}s)"
  done
}

ensure_docker() {
  docker_ready && { ensure_compose; return 0; }
  if [ "$OS" = linux ]; then
    has docker || install_docker_linux
    run $SUDO systemctl enable --now docker || run $SUDO service docker start || true
    wait_docker 120 "Avvio Docker…" || fail "Docker è installato ma non parte. Prova: sudo systemctl start docker"
    if [ -n "$SUDO" ] && ! id -nG "$USER" | grep -qw docker; then
      run $SUDO usermod -aG docker "$USER" || true
      note "Ti ho aggiunto al gruppo 'docker': dal prossimo accesso i comandi docker non chiedono più sudo."
    fi
    ensure_compose
  else
    if [ ! -d /Applications/Docker.app ]; then
      [ "$PKG" = brew ] || fail "su macOS serve Homebrew (https://brew.sh) oppure Docker Desktop (https://docker.com/products/docker-desktop)."
      say "Installo Docker Desktop…"
      retry "Installazione di Docker Desktop" run brew install --cask docker \
        || fail "Docker Desktop non si installa: scaricalo da https://docker.com/products/docker-desktop e rilancia."
    fi
    run open -a Docker || true
    wait_docker 300 "Apro Docker Desktop: se è la prima volta, accetta la licenza nella sua finestra." \
      || fail "Docker Desktop non risponde: aprilo, accetta la licenza, aspetta che dica «running» e rilancia."
  fi
}

# ── 5. Ollama (native on the host: GPU on Linux, Metal on Mac) ──────────────────────────────────────────────────
ollama_up() { curl -fsS --max-time 3 http://127.0.0.1:11434/api/version >/dev/null 2>&1; }

ensure_ollama() {
  if ! has ollama && ! ollama_up; then
    say "Installo Ollama (i modelli sul tuo computer)…"
    if [ "$OS" = linux ]; then
      retry "Installazione di Ollama" run_sh "curl -fsSL https://ollama.com/install.sh | sh" || {
        note "Ollama non si è installato: Hestia userà i modelli nel cloud. Puoi installarlo dopo da https://ollama.com."
        return 0; }
    else
      { [ "$PKG" = brew ] && retry "Installazione di Ollama" run brew install ollama; } || {
        note "Ollama non si è installato: Hestia userà i modelli nel cloud. Puoi installarlo da https://ollama.com."
        return 0; }
    fi
  fi
  if ! ollama_up; then
    if [ "$OS" = linux ]; then run $SUDO systemctl enable --now ollama || run_sh "nohup ollama serve >/dev/null 2>&1 &" || true
    else run brew services start ollama || run open -a Ollama || true; fi
    [ "$DRY_RUN" = 1 ] || sleep 3
  fi
  [ "$OS" = linux ] && ollama_reachable_from_docker
  pull_default_models
  return 0
}

# Oracle's default chains (llm_chains.py): the embedding model is needed for memory, the chat one for local answers.
DEFAULT_MODELS="qwen3-embedding:0.6b gemma4:e4b"

pull_default_models() {
  has ollama || return 0
  local model
  for model in $DEFAULT_MODELS; do
    if [ "$DRY_RUN" = 0 ] && ollama list 2>/dev/null | awk '{print $1}' | grep -qx "$model"; then continue; fi
    say "Scarico il modello $model (una volta sola)…"
    retry "Download di $model" run ollama pull "$model" \
      || note "Il modello $model non si è scaricato: rilancia più tardi, nel frattempo Hestia usa il cloud se hai una chiave."
  done
}

ollama_reachable_from_docker() {
  # Containers reach Ollama at host.docker.internal = the Docker bridge; Ollama listens only on 127.0.0.1 by default.
  [ "$DRY_RUN" = 1 ] && return 0
  local probe=(run --rm --add-host host.docker.internal:host-gateway curlimages/curl:8.10.1 -fsS --max-time 5
               http://host.docker.internal:11434/api/version)
  dk "${probe[@]}" >/dev/null 2>&1 && return 0
  has systemctl && systemctl list-unit-files ollama.service >/dev/null 2>&1 || {
    note "Ollama non è raggiungibile dai container: avvialo con OLLAMA_HOST=0.0.0.0 ollama serve."
    return 0; }
  log "[🔄] ollama_bind_all reason=containers_cannot_reach"
  run $SUDO mkdir -p /etc/systemd/system/ollama.service.d
  run_sh "printf '[Service]\nEnvironment=OLLAMA_HOST=0.0.0.0:11434\n' | $SUDO tee /etc/systemd/system/ollama.service.d/hestia.conf"
  run $SUDO systemctl daemon-reload && run $SUDO systemctl restart ollama || true
  sleep 3
  if has ufw && $SUDO ufw status 2>/dev/null | grep -q "Status: active"; then
    run $SUDO ufw allow from 172.16.0.0/12 to any port 11434 proto tcp || true
  else
    note "Ollama ora ascolta anche sulla rete di casa (porta 11434), così i container lo vedono: non aprire quella porta sul router."
  fi
  dk "${probe[@]}" >/dev/null 2>&1 || note "Ollama non risponde ai container: Hestia userà i modelli nel cloud finché non lo sistemi."
}

# ── 6. Hestia code ─────────────────────────────────────────────────────────────────────────────────────────────
ensure_code() {
  if [ -d "$HESTIA_DIR/.git" ]; then
    git -C "$HESTIA_DIR" remote get-url origin 2>/dev/null | grep -qi 'hestia' \
      || fail "$HESTIA_DIR esiste ma non è Hestia. Scegli un'altra cartella con --dir."
    retry "Aggiornamento del codice" run git -C "$HESTIA_DIR" fetch --tags --prune origin \
      || note "Non ho potuto scaricare le novità del codice: uso la versione che c'è."
  elif [ -f "$HESTIA_DIR/docker-compose.global.yml" ]; then
    log "code_existing_without_git dir=$HESTIA_DIR"
  elif [ -d "$HESTIA_DIR" ] && [ -n "$(ls -A "$HESTIA_DIR" 2>/dev/null)" ]; then
    fail "$HESTIA_DIR esiste e non è vuota. Scegli un'altra cartella con --dir."
  else
    say "Scarico Hestia in ${HESTIA_DIR}…"
    if has git; then
      retry "Download di Hestia" run git clone --quiet "$HESTIA_REPO_URL" "$HESTIA_DIR" \
        || fail "non riesco a scaricare Hestia da GitHub. Controlla la connessione."
    else
      log "[🔄] code_tarball reason=no_git"
      run mkdir -p "$HESTIA_DIR"
      retry "Download di Hestia" run_sh "curl -fsSL '$HESTIA_TARBALL_URL' | tar -xz -C '$HESTIA_DIR' --strip-components=1" \
        || fail "non riesco a scaricare Hestia da GitHub. Controlla la connessione."
    fi
  fi
  pick_version
}

pick_version() {
  [ -d "$HESTIA_DIR/.git" ] || { VERSION_TAG=""; return 0; }
  if [ -n "$(git -C "$HESTIA_DIR" status --porcelain --untracked-files=no 2>/dev/null)" ]; then
    note "Nella cartella di Hestia ci sono modifiche locali: non ho cambiato versione del codice."
    VERSION_TAG="$(git -C "$HESTIA_DIR" describe --tags --exact-match 2>/dev/null || true)"
    return 0
  fi
  if [ "$CHANNEL" = stabile ]; then
    VERSION_TAG="$(git -C "$HESTIA_DIR" tag -l 'v*.*.*' --sort=-v:refname | head -n1)"
    if [ -n "$VERSION_TAG" ]; then
      run git -C "$HESTIA_DIR" -c advice.detachedHead=false checkout --quiet "$VERSION_TAG"
      ok "Versione $VERSION_TAG"
      return 0
    fi
    note "Non c'è ancora una versione pubblicata: installo l'ultima di sviluppo e la costruisco qui (più lento, una volta sola)."
  fi
  VERSION_TAG=""
  local branch; branch="$(git -C "$HESTIA_DIR" rev-parse --abbrev-ref HEAD)"
  if [ "$branch" = HEAD ]; then run git -C "$HESTIA_DIR" checkout --quiet main; branch=main; fi
  run git -C "$HESTIA_DIR" pull --quiet --ff-only origin "$branch" \
    || note "Il codice locale non segue più quello di GitHub: l'ho lasciato com'è."
}

# What the guided setup shows («Scheda video da 16 GB») and uses to suggest models: git-ignored, no personal data.
write_hardware() {
  [ "$DRY_RUN" = 1 ] && return 0
  local gpu="" vram=0 line mib
  if has nvidia-smi; then
    line="$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits 2>/dev/null | head -n1)"
    gpu="$(printf '%s' "${line%,*}" | tr -d '"\\')"
    mib="${line##*, }"
    case "$mib" in ''|*[!0-9]*) mib=0 ;; esac
    vram=$(( mib / 1024 ))
  elif [ "$OS" = mac ] && [ "$(uname -m)" = arm64 ]; then
    gpu="Apple"; vram=$(( RAM_GB * 2 / 3 ))   # unified memory: Ollama may use about two thirds
  fi
  mkdir -p "$HESTIA_DIR/.hestia-install"
  printf '{"os": "%s", "ram_gb": %s, "free_gb": %s, "gpu": "%s", "vram_gb": %s}\n' \
    "$OS" "$RAM_GB" "$FREE_GB" "$gpu" "${vram:-0}" > "$HESTIA_DIR/.hestia-install/hardware.json"
  log "hardware gpu=\"$gpu\" vram_gb=${vram:-0}"
}

# ── 7. .env files with generated secrets (python runs in a throwaway container, none needed on the host) ────────
ensure_env() {
  local args=(--generate-secrets)
  dk volume inspect "${PROJECT}_hestia_archive_pgdata" >/dev/null 2>&1 || args+=(--new-db)
  local user=()
  [ "$OS" = linux ] && user=(--user "$(id -u):$(id -g)")
  if retry "Preparazione della configurazione" run "${DOCKER[@]}" run --rm ${user[@]+"${user[@]}"} -v "$HESTIA_DIR:/w" -w /w \
       python:3.12-slim python tools/init_env.py "${args[@]}"; then
    return 0
  fi
  log "[🔄] env_host_python reason=container_failed"
  has python3 && run_sh "cd '$HESTIA_DIR' && python3 tools/init_env.py ${args[*]}" && return 0
  fail "non riesco a preparare i file di configurazione (.env)."
}

# ── 8–9. images, start, health ─────────────────────────────────────────────────────────────────────────────────
start_stack() {
  dk network inspect hestia_net >/dev/null 2>&1 || run "${DOCKER[@]}" network create hestia_net \
    || fail "non riesco a creare la rete Docker hestia_net."
  if [ -n "$VERSION_TAG" ]; then
    say "Scarico i moduli pronti della versione ${VERSION_TAG}…"
    retry "Download dei moduli" run_quiet_compose pull --ignore-pull-failures \
      || note "Alcuni moduli non si sono scaricati: li costruisco qui."
  else
    say "Costruisco i moduli (la prima volta ci vuole un po', poi è veloce)…"
    build_all
  fi
  say "Avvio Hestia…"
  local services=()
  if ! telegram_configured; then
    # No bot token yet: Telegram would only crash-loop. Its container is created, not started: the guided setup
    # writes the token and starts it.
    local svc
    while IFS= read -r svc; do services+=("$svc"); done < <(compose config --services 2>/dev/null | grep -vx telegram)
    note "Telegram si collega nel setup guidato che si apre nel browser."
  fi
  retry "Avvio dei moduli" run_quiet_compose up -d --remove-orphans ${services[@]+"${services[@]}"} \
    || fail "i moduli non partono. Guarda $LOG_FILE (ultime righe) o rilancia."
  if ! telegram_configured; then run_quiet_compose create telegram || true; fi
}

telegram_configured() {  # the value is never read into a variable or printed
  grep -Eq '^TELEGRAM_BOT_TOKEN=.+' "$HESTIA_DIR/Hestia-Telegram/app/.env" 2>/dev/null
}

run_quiet_compose() {
  if [ "$DRY_RUN" = 1 ]; then printf '  [dry-run] docker compose %s\n' "$*"; return 0; fi
  log "compose args=\"$*\""
  compose "$@" >> "$LOG_FILE" 2>&1
}

build_all() {
  retry "Costruzione dei moduli" run_quiet_compose build && return 0
  # Find the one that breaks, rebuild it from scratch, then the rest.
  local svc bad=""
  for svc in $(compose config --services 2>/dev/null); do
    run_quiet_compose build "$svc" && continue
    log "[🔄] build_no_cache service=$svc"
    run_quiet_compose build --no-cache "$svc" || bad="$bad $svc"
  done
  [ -z "$bad" ] || fail "non riesco a costruire:$bad. Guarda $LOG_FILE."
}

wait_healthy() {
  [ "$DRY_RUN" = 1 ] && return 0
  say "Aspetto che tutti i moduli rispondano…"
  local waited=0
  until curl -fsS --max-time 3 "$HUB_URL/health" >/dev/null 2>&1; do
    [ "$waited" -ge 300 ] && fail "il centro di Hestia (Hub) non risponde dopo 5 minuti."
    sleep 5; waited=$((waited + 5))
  done
  waited=0
  while :; do
    local down
    down="$(dk ps -a --filter "name=hestia_" --format '{{.Names}} {{.Status}}' | grep -Ev ' (Up|Created)' | awk '{print $1}' | tr '\n' ' ')"
    if [ -z "$down" ] && curl -fsS --max-time 3 "$WEBUI_URL" >/dev/null 2>&1; then
      ok "Tutti i moduli sono accesi."
      return 0
    fi
    if [ "$waited" -ge 600 ]; then
      local c
      for c in $down; do log "container_down name=$c"; dk logs --tail 20 "$c" >> "$LOG_FILE" 2>&1 || true; done
      note "Questi moduli non sono partiti: $down(ultime righe in $LOG_FILE). Hestia funziona lo stesso senza di loro."
      return 0
    fi
    sleep 10; waited=$((waited + 10))
  done
}

# ── 10. browser + shortcut ─────────────────────────────────────────────────────────────────────────────────────
finish() {
  if [ "$OS" = linux ] && [ "$DRY_RUN" = 0 ]; then
    local apps="$HOME/.local/share/applications"
    mkdir -p "$apps"
    printf '[Desktop Entry]\nType=Link\nName=Hestia\nURL=%s\nIcon=applications-internet\n' "$WEBUI_URL" > "$apps/hestia.desktop"
    [ -d "$HOME/Desktop" ] && cp "$apps/hestia.desktop" "$HOME/Desktop/hestia.desktop" 2>/dev/null || true
  fi
  if [ "$OPEN_BROWSER" = 1 ] && [ "$DRY_RUN" = 0 ]; then
    if [ "$OS" = mac ]; then open "$SETUP_URL" || true
    elif has xdg-open && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then xdg-open "$SETUP_URL" >/dev/null 2>&1 || true; fi
  fi
  echo
  ok "Hestia è pronta: $WEBUI_URL (il setup guidato è su $SETUP_URL)"
  local n
  for n in ${NOTES[@]+"${NOTES[@]}"}; do printf '         · %s\n' "$n"; done
  printf '         Per aggiornare o riparare: rilancia questo stesso comando.\n'
  log "install_done version=${VERSION_TAG:-dev} notes=${#NOTES[@]}"
}

# ── uninstall ──────────────────────────────────────────────────────────────────────────────────────────────────
uninstall() {
  [ -f "$HESTIA_DIR/docker-compose.global.yml" ] || fail "non trovo Hestia in $HESTIA_DIR (usa --dir)."
  docker_ready || fail "Docker non risponde: avvialo e rilancia."
  if [ "$PURGE" = 1 ]; then
    say "ATTENZIONE: cancello Hestia E TUTTI I SUOI DATI (memorie, chat, impostazioni). Non si torna indietro."
    local typed=""
    [ -r /dev/tty ] && read -r -p "[Hestia] Scrivi CANCELLA per confermare: " typed < /dev/tty || true
    [ "$typed" = CANCELLA ] || fail "non ho cancellato niente (conferma non data)."
    run_quiet_compose down -v --remove-orphans || true
    run rm -rf "$HESTIA_DIR"
    run rm -rf "$STATE_DIR"
    ok "Hestia e i suoi dati sono stati cancellati."
  else
    run_quiet_compose down --remove-orphans || true
    ok "Hestia è spenta e i container rimossi. I dati restano (cartella $HESTIA_DIR e volumi Docker); --purge per cancellarli."
  fi
}

# ── main ───────────────────────────────────────────────────────────────────────────────────────────────────────
parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --dir) HESTIA_DIR="$2"; shift ;;
      --dir=*) HESTIA_DIR="${1#*=}" ;;
      --channel) CHANNEL="$2"; shift ;;
      --channel=*) CHANNEL="${1#*=}" ;;
      --update|--repair) ACTION=install ;;
      --uninstall) ACTION=uninstall ;;
      --purge) PURGE=1 ;;
      --dry-run) DRY_RUN=1 ;;
      --no-browser) OPEN_BROWSER=0 ;;
      -h|--help) usage ;;
      *) fail "opzione sconosciuta: $1 (vedi --help)" ;;
    esac
    shift
  done
  case "$CHANNEL" in stabile|novita|novità) ;; *) fail "canale sconosciuto: $CHANNEL (stabile o novita)" ;; esac
  [ "$CHANNEL" = novità ] && CHANNEL=novita
  return 0
}

main() {
  parse_args "$@"
  mkdir -p "$STATE_DIR"
  log "install_start action=$ACTION channel=$CHANNEL dry_run=$DRY_RUN"
  detect_os
  if [ "$ACTION" = uninstall ]; then uninstall; return 0; fi
  say "Installo Hestia in $HESTIA_DIR (canale $CHANNEL). Ti chiederò la password del computer al massimo una volta."
  preflight
  ensure_git;    state_mark git
  ensure_docker; state_mark docker
  ports_check
  ensure_ollama; state_mark ollama
  ensure_code;   state_mark code
  write_hardware
  ensure_env;    state_mark env
  start_stack;   state_mark started
  wait_healthy;  state_mark healthy
  finish
}

# Everything runs from here: a download cut halfway through (curl | bash) never executes half a script.
main "$@"
