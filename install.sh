#!/usr/bin/env bash
# Hestia installer for Linux (main target) and macOS (only the simple path: Homebrew + Docker Desktop).
# Written for bash 3.2 too (macOS): no mapfile, no ${var,,}, empty arrays expanded with ${a[@]+"${a[@]}"}, and
# ${VAR} in braces before a non-ASCII character (3.2 glues the first UTF-8 byte to the name).
#
#   curl -fsSL https://raw.githubusercontent.com/SaibboRiginal/Hestia/main/install.sh | bash
#   bash install.sh [--dir PATH] [--channel stable|latest] [--update] [--uninstall [--purge]] [--dry-run] [--yes]
#   bash install.sh --join CODE --central IP        this machine becomes a satellite of the central one
#   bash install.sh --role all|central|satellite
#
# Every step checks before acting, retries (2/4/8 s), has a fallback, and records where it got to: running the same
# command again resumes or repairs. When it truly cannot go on it stops with one sentence saying what to do.
# It never prints or logs secrets, never overwrites an existing .env value (only the machine link keys HUB_UPSTREAM_URL,
# HUB_NODE_TOKEN, HUB_NODE_ADDRESS, on --join or a role change), never deletes data without --purge.
# SPEC: docs/work/2026-10-30-one-click-setup
set -Eeuo pipefail

HESTIA_REPO_URL="${HESTIA_REPO_URL:-https://github.com/SaibboRiginal/Hestia.git}"
HESTIA_RAW_URL="${HESTIA_RAW_URL:-https://raw.githubusercontent.com/SaibboRiginal/Hestia/main}"   # language catalogs
HESTIA_TARBALL_URL="${HESTIA_TARBALL_URL:-https://codeload.github.com/SaibboRiginal/Hestia/tar.gz/refs/heads/main}"
# Folder: where it is launched. A Hestia folder (it has docker-compose.global.yml) is used as it is, otherwise Hestia
# goes in a «Hestia» folder inside it; from / or a system folder, ~/Hestia instead. --dir / HESTIA_DIR win.
default_dir() {
  local here; here="$(pwd -P 2>/dev/null || pwd)"
  if [ -f "$here/docker-compose.global.yml" ]; then printf '%s' "$here"; return; fi
  case "$here" in /|/bin*|/sbin*|/usr*|/etc*|/var*|/opt*|/System*|/Library*|/private*|/tmp|/root) [ "$here" = "$HOME" ] || { printf '%s' "$HOME/Hestia"; return; } ;; esac
  printf '%s' "$here/Hestia"
}
HESTIA_DIR="${HESTIA_DIR:-$(default_dir)}"
CHANNEL="${HESTIA_CHANNEL:-stable}"
ACTION="install"
RAM_GB=0
FREE_GB=0
PURGE=0
DRY_RUN=0
OPEN_BROWSER=1
WEBUI_URL="http://localhost:19015"
SETUP_URL="$WEBUI_URL/setup"
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
ROLE=""            # all (one machine) · central (always on, no heavy modules) · satellite (voice + training near a GPU)
JOIN_CODE=""
CENTRAL_URL=""
LAN_IP=""
SATELLITE_SERVICES="hub echo metis"
HEAVY_SERVICES="echo metis"

# ── language ───────────────────────────────────────────────────────────────────────────────────────────────────
# Messages are English, in the language of the computer (or --lang / HESTIA_LANG) when Hestia has a catalog for it:
# Hestia-Shared/hestia_common/locales/<code>/installer.tsv, one line «English<TAB>translation», values as {0} {1}.
# It is read next to this script, else downloaded from the same repository; no catalog → English. A new language =
# one new file, no change here. Every message is written "$(t "english {0}" "$value")".
detect_lang() {
  local l="${HESTIA_LANG:-${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}}"
  if [ -z "$l" ] || [ "$l" = C ] || [ "$l" = POSIX ] || [ "${l#C.}" != "$l" ]; then
    l="$(defaults read -g AppleLocale 2>/dev/null || true)"
  fi
  lang_code "$l"
}
lang_code() {
  local c
  c="$(printf '%s' "$1" | cut -c1-2 | tr '[:upper:]' '[:lower:]')"
  case "$c" in [a-z][a-z]) printf '%s' "$c" ;; *) printf en ;; esac
}
UI_LANG="$(detect_lang)"
TR_FILE=""
load_texts() {
  TR_FILE=""
  [ "$UI_LANG" = en ] && return 0
  local rel="Hestia-Shared/hestia_common/locales/$UI_LANG/installer.tsv" here
  here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
  if [ -n "$here" ] && [ -f "$here/$rel" ]; then TR_FILE="$here/$rel"; return 0; fi
  if [ -f "$PWD/$rel" ]; then TR_FILE="$PWD/$rel"; return 0; fi   # piped from a copy of the repository
  TR_FILE="${TMPDIR:-/tmp}/hestia-installer-$UI_LANG-$$.tsv"
  if ! curl -fsSL --max-time 10 -o "$TR_FILE" "$HESTIA_RAW_URL/$rel" 2>/dev/null; then
    rm -f "$TR_FILE"; TR_FILE=""   # [🔄] no catalog for this language or no network yet: English
  fi
}
t() {
  local text="$1" found="" i=0 v
  shift
  if [ -n "$TR_FILE" ]; then
    found="$(awk -F '\t' -v k="$text" '$1 == k { print $2; exit }' "$TR_FILE" 2>/dev/null || true)"
    [ -n "$found" ] && text="$found"
  fi
  for v in "$@"; do text="${text//\{$i\}/$v}"; i=$((i + 1)); done
  printf '%s' "$text"
}

# ── output ─────────────────────────────────────────────────────────────────────────────────────────────────────
say()  { printf '\033[1;33m[Hestia]\033[0m %s\n' "$*"; log "say msg=\"$*\""; }
ok()   { printf '\033[1;32m[Hestia]\033[0m %s\n' "$*"; log "ok msg=\"$*\""; }
note() { NOTES+=("$*"); }
log()  { mkdir -p "$STATE_DIR" 2>/dev/null && printf '%s event=%s\n' "$(date -u +%FT%TZ)" "$*" >> "$LOG_FILE" || true; }

fail() {
  printf '\n\033[1;31m[Hestia] %s\033[0m %s\n' "$(t "I stopped:")" "$1"
  printf '         %s\n' "$(t "Run the same command again when done: I pick up from here.")"
  printf '         %s %s\n' "$(t "Details:")" "$LOG_FILE"
  log "install_failed reason=\"$1\""
  exit 1
}

trap 'log "[🔄] unexpected_error line=$LINENO cmd=\"$BASH_COMMAND\""' ERR

usage() {
  cat <<'TXT'
Hestia installer (Linux, macOS)
  --dir PATH            install folder (default: where you launch it; a Hestia folder is used as it is)
  --channel stable      latest release, ready-made images (default)
  --channel latest      latest code on main, built here
  --lang CODE           language of the messages, e.g. en, it (default: the computer's)
  --update / --repair   same as no option: resume, repair, update
  --uninstall [--purge] stop Hestia (data kept); --purge also deletes data after typing DELETE (the word in your language)
  --dry-run             only print what it would do
  --no-browser          do not open the browser at the end
  --role all            everything on this machine (default)
  --role central        always-on home, e.g. Raspberry Pi: everything but voice and training
  --role satellite      voice and training here, near the graphics card; the rest stays on the central one
  --join CODE --central IP   link this machine as a satellite (code from System -> Machines on the central one)
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
    say "$(t "{0}: did not work, retrying in {1}s…" "$what" "${delay}")"
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
    *) fail "$(t "this installer is for Linux and macOS. On Windows use Install-Hestia.cmd (or install.ps1).")" ;;
  esac
  if [ "$(id -u)" != 0 ]; then
    has sudo || [ "$OS" = mac ] || fail "$(t "'sudo' is needed (or run as root).")"
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
  say "$(t "Checking the computer…")"
  local parent
  if [ "$OS" = linux ]; then
    RAM_GB=$(( $(awk '/MemTotal/ {print $2}' /proc/meminfo) / 1024 / 1024 ))
  else
    RAM_GB=$(( $(sysctl -n hw.memsize) / 1024 / 1024 / 1024 ))
  fi
  parent="$HESTIA_DIR"; while [ ! -d "$parent" ]; do parent="$(dirname "$parent")"; done
  FREE_GB=$(( $(df -Pk "$parent" | awk 'NR==2 {print $4}') / 1024 / 1024 ))
  log "preflight ram_gb=$RAM_GB free_gb=$FREE_GB"
  [ "$RAM_GB" -lt 8 ] && note "$(t "You have {0} GB of RAM: Hestia works, but local models need at least 16. Use cloud models." "${RAM_GB}")"
  if [ "$FREE_GB" -lt 20 ]; then
    fail "$(t "at least 20 GB free (better 30) are needed on {0}, there are {1}. Free some space." "$parent" "${FREE_GB}")"
  fi
  [ "$FREE_GB" -lt 30 ] && note "$(t "Free space: {0} GB. Enough for Hestia; it may not be enough for large local models." "${FREE_GB}")"
  has curl || pkg_install curl || fail "$(t "'curl' is missing and I cannot install it.")"
  retry "$(t "Internet connection")" curl -fsS --max-time 15 -o /dev/null "${HESTIA_REPO_URL%.git}.git/info/refs?service=git-upload-pack" \
    || fail "$(t "I cannot reach github.com: check the internet connection.")"
  if [ "$OS" = linux ] && [ "$(uname -m)" = x86_64 ] && ! grep -Eq 'vmx|svm|hypervisor' /proc/cpuinfo; then
    note "$(t "Virtualization does not look on in the BIOS: Docker usually does not need it on Linux, but if something does not start, turn it on.")"
  fi
}

# A busy port is named with what holds it. Another Hestia (its containers, from another folder or an older install)
# is offered to be stopped, so the user never hunts for it; any other program is named so they know what to close.
port_holder() {   # prints «container:<name>» or «program:<name>» or nothing
  local row prog=""
  if dk info >/dev/null 2>&1; then
    while IFS= read -r row; do
      case "${row#*|}" in *":$1->"*) printf 'container:%s' "${row%%|*}"; return 0 ;; esac
    done < <(dk ps --format '{{.Names}}|{{.Ports}}' 2>/dev/null)
  fi
  has lsof && prog="$(lsof -nP -iTCP:"$1" -sTCP:LISTEN 2>/dev/null | awk 'NR==2 {print $1}')"
  [ -z "$prog" ] && has ss && prog="$(ss -ltnp 2>/dev/null | grep "[:.]$1 " | sed -n 's/.*users:(("\([^"]*\)".*/\1/p' | head -n1)"
  [ -n "$prog" ] && printf 'program:%s' "$prog"
  return 0
}

ports_check() {
  # Only on a first install: a running Hestia of course holds its own ports.
  dk ps --format '{{.Names}}' 2>/dev/null | grep -q '^hestia_hub$' && return 0
  local busy="" others="" hestia="" port holder
  local ports="19001 19002 19015 5432"
  [ "$ROLE" = satellite ] && ports="19001 19021 19014"
  for port in $ports; do
    if { has ss && ss -ltn 2>/dev/null | grep -q "[:.]$port "; } || \
       { has lsof && lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; }; then
      busy="$busy $port"
      holder="$(port_holder "$port")"
      case "$holder" in
        container:hestia_*) hestia="$hestia ${holder#container:}" ;;
        ?*) others="$others $port (${holder#*:})" ;;
        *) others="$others $port" ;;
      esac
    fi
  done
  log "ports_busy ports=\"${busy# }\" hestia=\"${hestia# }\" others=\"${others# }\""
  [ -n "$others" ] && fail "$(t "these ports are already used by another program:{0}. Close it and run again." "$others")"
  [ -z "$hestia" ] && return 0
  # Another Hestia is on: stop all of its containers (they start again with docker start; data stays in its volumes).
  local first where place answer="n" running
  first="$(echo $hestia | awk '{print $1}')"
  where="$(dk inspect -f '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' "$first" 2>/dev/null)"
  place="${where:-$(t "another folder")}"
  running="$(dk ps --format '{{.Names}}' 2>/dev/null | grep '^hestia_' | tr '\n' ' ')"
  say "$(t "Another Hestia is already on ({0}) and holds the ports Hestia needs." "$place")"
  [ -r /dev/tty ] && read -r -p "[Hestia] $(t "Stop it and go on? [Y/n]") " answer < /dev/tty || true
  [ -r /dev/tty ] || answer="n"
  case "$answer" in [nN]*) fail "$(t "stop the other Hestia first (docker stop on its containers), then run again.")" ;; esac
  # shellcheck disable=SC2086
  [ "$DRY_RUN" = 1 ] || dk stop $running >/dev/null 2>&1 || true
  log "other_hestia_stopped where=\"$place\""
  say "$(t "Other Hestia stopped: its data stays where it was.")"
  return 0
}

# ── 1. git ─────────────────────────────────────────────────────────────────────────────────────────────────────
ensure_git() {
  has git && return 0
  say "$(t "Installing git…")"
  if [ "$OS" = mac ]; then
    [ -n "$PKG" ] && retry "$(t "Installing git")" pkg_install git && return 0
    run xcode-select --install || true
    fail "$(t "macOS needs git: confirm the «Command Line Tools» window that opened (or install Homebrew from https://brew.sh).")"
  fi
  retry "$(t "Installing git")" pkg_install git && return 0
  note "$(t "git did not install: I download Hestia as an archive (updates will use git once it is there).")"
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
  say "$(t "Installing Docker (it takes a few minutes)…")"
  if retry "$(t "Installing Docker")" run_sh "curl -fsSL https://get.docker.com | $SUDO sh"; then return 0; fi
  log "[🔄] docker_fallback via=distro_package"
  case "$PKG" in
    apt) pkg_install docker.io docker-compose-v2 || pkg_install docker.io docker-compose-plugin ;;
    dnf|yum) pkg_install docker docker-compose-plugin || pkg_install moby-engine docker-compose ;;
    pacman) pkg_install docker docker-compose ;;
    zypper) pkg_install docker docker-compose ;;
    apk) pkg_install docker docker-cli-compose ;;
    *) false ;;
  esac || fail "$(t "I cannot install Docker. Install it following https://docs.docker.com/engine/install/ and run again.")"
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
  retry "$(t "Downloading docker compose")" run curl -fsSL -o "$HOME/.docker/cli-plugins/docker-compose" \
    "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-$arch" \
    && run chmod +x "$HOME/.docker/cli-plugins/docker-compose" && dk compose version >/dev/null 2>&1 \
    || fail "$(t "'docker compose' is missing and I cannot install it.")"
}

wait_docker() {  # wait_docker <seconds> <message>
  local limit="$1" waited=0
  [ "$DRY_RUN" = 1 ] && return 0
  say "$2"
  until docker_ready; do
    [ "$waited" -ge "$limit" ] && return 1
    sleep 5; waited=$((waited + 5))
    [ $((waited % 30)) = 0 ] && say "$(t "…still waiting for Docker ({0}s)" "${waited}")"
  done
}

ensure_docker() {
  docker_ready && { ensure_compose; return 0; }
  if [ "$OS" = linux ]; then
    has docker || install_docker_linux
    run $SUDO systemctl enable --now docker || run $SUDO service docker start || true
    wait_docker 120 "$(t "Starting Docker…")" || fail "$(t "Docker is installed but does not start. Try: sudo systemctl start docker")"
    if [ -n "$SUDO" ] && ! id -nG "$USER" | grep -qw docker; then
      run $SUDO usermod -aG docker "$USER" || true
      note "$(t "I added you to the 'docker' group: from your next login docker commands no longer ask for sudo.")"
    fi
    ensure_compose
  else
    if [ ! -d /Applications/Docker.app ]; then
      [ "$PKG" = brew ] || fail "$(t "macOS needs Homebrew (https://brew.sh) or Docker Desktop (https://docker.com/products/docker-desktop).")"
      say "$(t "Installing Docker Desktop…")"
      retry "$(t "Installing Docker Desktop")" run brew install --cask docker \
        || fail "$(t "Docker Desktop does not install: download it from https://docker.com/products/docker-desktop and run again.")"
    fi
    run open -a Docker || true
    wait_docker 300 "$(t "Opening Docker Desktop: if it is the first time, accept the license in its window.")" \
      || fail "$(t "Docker Desktop does not answer: open it, accept the license, wait for «running» and run again.")"
  fi
}

# ── 5. Ollama (native on the host: GPU on Linux, Metal on Mac) ──────────────────────────────────────────────────
ollama_up() { curl -fsS --max-time 3 http://127.0.0.1:11434/api/version >/dev/null 2>&1; }

ensure_ollama() {
  if ! has ollama && ! ollama_up; then
    say "$(t "Installing Ollama (the models on your computer)…")"
    if [ "$OS" = linux ]; then
      retry "$(t "Installing Ollama")" run_sh "curl -fsSL https://ollama.com/install.sh | sh" || {
        note "$(t "Ollama did not install: Hestia will use cloud models. You can install it later from https://ollama.com.")"
        return 0; }
    else
      { [ "$PKG" = brew ] && retry "$(t "Installing Ollama")" run brew install ollama; } || {
        note "$(t "Ollama did not install: Hestia will use cloud models. You can install it from https://ollama.com.")"
        return 0; }
    fi
  fi
  if ! ollama_up; then
    if [ "$OS" = linux ]; then run $SUDO systemctl enable --now ollama || run_sh "nohup ollama serve >/dev/null 2>&1 &" || true
    else run brew services start ollama || run open -a Ollama || true; fi
    [ "$DRY_RUN" = 1 ] || sleep 3
  fi
  [ "$OS" = linux ] && ollama_reachable_from_docker
  [ "$ROLE" = satellite ] && ollama_bind_all   # the central one's brain uses this graphics card
  return 0
}

# No model is downloaded here: the guided setup shows what is already on the computer and downloads only what the
# owner picks, with its progress (Oracle /api/llm/setup/pull).

ollama_reachable_from_docker() {
  # Containers reach Ollama at host.docker.internal = the Docker bridge; Ollama listens only on 127.0.0.1 by default.
  [ "$DRY_RUN" = 1 ] && return 0
  local probe=(run --rm --add-host host.docker.internal:host-gateway curlimages/curl:8.10.1 -fsS --max-time 5
               http://host.docker.internal:11434/api/version)
  dk "${probe[@]}" >/dev/null 2>&1 && return 0
  has systemctl && systemctl list-unit-files ollama.service >/dev/null 2>&1 || {
    note "$(t "The containers cannot reach Ollama: start it with OLLAMA_HOST=0.0.0.0 ollama serve.")"
    return 0; }
  log "[🔄] ollama_bind_all reason=containers_cannot_reach"
  ollama_bind_all
  dk "${probe[@]}" >/dev/null 2>&1 || note "$(t "Ollama does not answer the containers: Hestia will use cloud models until you fix it.")"
}

# Ollama listening on every address: the containers (Docker bridge) and, on a satellite, the central one over the LAN.
ollama_bind_all() {
  if [ "$OS" = mac ]; then
    run launchctl setenv OLLAMA_HOST 0.0.0.0:11434 || true
    run brew services restart ollama || true
    note "$(t "Ollama now listens on the home network (port 11434): do not open that port on the router.")"
    return 0
  fi
  if has systemctl && systemctl list-unit-files ollama.service >/dev/null 2>&1; then
    if ! grep -qs 'OLLAMA_HOST=0.0.0.0' /etc/systemd/system/ollama.service.d/hestia.conf; then
      run $SUDO mkdir -p /etc/systemd/system/ollama.service.d
      run_sh "printf '[Service]\nEnvironment=OLLAMA_HOST=0.0.0.0:11434\n' | $SUDO tee /etc/systemd/system/ollama.service.d/hestia.conf"
      run $SUDO systemctl daemon-reload && run $SUDO systemctl restart ollama || true
      [ "$DRY_RUN" = 1 ] || sleep 3
    fi
  else
    note "$(t "To let the other machines see it, start Ollama with: OLLAMA_HOST=0.0.0.0 ollama serve")"
    return 0
  fi
  if has ufw && $SUDO ufw status 2>/dev/null | grep -q "Status: active"; then
    run $SUDO ufw allow from 172.16.0.0/12 to any port 11434 proto tcp || true
    if [ "$ROLE" = satellite ]; then   # the central one reaches this machine's modules and Ollama over the LAN
      local p
      for p in 11434 19021 19014; do run $SUDO ufw allow from 192.168.0.0/16 to any port "$p" proto tcp || true; done
      for p in 11434 19021 19014; do run $SUDO ufw allow from 10.0.0.0/8 to any port "$p" proto tcp || true; done
    fi
  else
    note "$(t "Ollama now also listens on the home network (port 11434): do not open that port on the router.")"
  fi
}

# ── 6. Hestia code ─────────────────────────────────────────────────────────────────────────────────────────────
ensure_code() {
  if [ -d "$HESTIA_DIR/.git" ]; then
    git -C "$HESTIA_DIR" remote get-url origin 2>/dev/null | grep -qi 'hestia' \
      || fail "$(t "{0} exists but is not Hestia. Choose another folder with --dir." "$HESTIA_DIR")"
    retry "$(t "Updating the code")" run git -C "$HESTIA_DIR" fetch --tags --prune origin \
      || note "$(t "I could not download the code changes: I use the version already here.")"
  elif [ -f "$HESTIA_DIR/docker-compose.global.yml" ]; then
    log "code_existing_without_git dir=$HESTIA_DIR"
  elif [ -d "$HESTIA_DIR" ] && [ -n "$(ls -A "$HESTIA_DIR" 2>/dev/null)" ]; then
    fail "$(t "{0} exists and is not empty. Choose another folder with --dir." "$HESTIA_DIR")"
  else
    say "$(t "Downloading Hestia into {0}…" "${HESTIA_DIR}")"
    if has git; then
      retry "$(t "Downloading Hestia")" run git clone --quiet "$HESTIA_REPO_URL" "$HESTIA_DIR" \
        || fail "$(t "I cannot download Hestia from GitHub. Check the connection.")"
    else
      log "[🔄] code_tarball reason=no_git"
      run mkdir -p "$HESTIA_DIR"
      retry "$(t "Downloading Hestia")" run_sh "curl -fsSL '$HESTIA_TARBALL_URL' | tar -xz -C '$HESTIA_DIR' --strip-components=1" \
        || fail "$(t "I cannot download Hestia from GitHub. Check the connection.")"
    fi
  fi
  pick_version
}

pick_version() {
  [ -d "$HESTIA_DIR/.git" ] || { VERSION_TAG=""; return 0; }
  if [ -n "$(git -C "$HESTIA_DIR" status --porcelain --untracked-files=no 2>/dev/null)" ]; then
    note "$(t "The Hestia folder has local changes: I did not change the code version.")"
    VERSION_TAG="$(git -C "$HESTIA_DIR" describe --tags --exact-match 2>/dev/null || true)"
    return 0
  fi
  if [ "$CHANNEL" = stable ]; then
    VERSION_TAG="$(git -C "$HESTIA_DIR" tag -l 'v*.*.*' --sort=-v:refname | head -n1)"
    if [ -n "$VERSION_TAG" ]; then
      run git -C "$HESTIA_DIR" -c advice.detachedHead=false checkout --quiet "$VERSION_TAG"
      ok "$(t "Version {0}" "$VERSION_TAG")"
      return 0
    fi
    note "$(t "There is no published version yet: I install the latest development one and build it here (slower, only once).")"
  fi
  VERSION_TAG=""
  local branch; branch="$(git -C "$HESTIA_DIR" rev-parse --abbrev-ref HEAD)"
  if [ "$branch" = HEAD ]; then run git -C "$HESTIA_DIR" checkout --quiet main; branch=main; fi
  run git -C "$HESTIA_DIR" pull --quiet --ff-only origin "$branch" \
    || note "$(t "The local code no longer follows GitHub: I left it as it is.")"
}

# What the guided setup shows («16 GB graphics card») and uses to suggest models: git-ignored, no personal data.
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
  printf '{"os": "%s", "ram_gb": %s, "free_gb": %s, "gpu": "%s", "vram_gb": %s, "role": "%s", "lan_ip": "%s"}\n' \
    "$OS" "$RAM_GB" "$FREE_GB" "$gpu" "${vram:-0}" "$ROLE" "$LAN_IP" > "$HESTIA_DIR/.hestia-install/hardware.json"
  log "hardware gpu=\"$gpu\" vram_gb=${vram:-0} role=$ROLE lan_ip=$LAN_IP"
}

# ── machines: role, LAN address, link to the central one (docs/work/2026-10-30-one-click-setup §4.0) ─────────────
resolve_role() {
  if [ -z "$ROLE" ]; then   # a re-run keeps the role chosen before
    ROLE="$(sed -n 's/.*"role": *"\([a-z]*\)".*/\1/p' "$HESTIA_DIR/.hestia-install/hardware.json" 2>/dev/null || true)"
    [ -n "$ROLE" ] || ROLE=all
  fi
  if [ "$ROLE" = satellite ] && [ -z "$JOIN_CODE" ] && ! grep -Eq '^HUB_NODE_TOKEN=.+' "$HESTIA_DIR/.env" 2>/dev/null; then
    fail "$(t "to link this machine you need the code: on the central home open System → Machines → Link a machine, then run again with --join CODE --central ADDRESS.")"
  fi
  LAN_IP="$(detect_lan_ip)"
  log "role role=$ROLE lan_ip=$LAN_IP"
}

detect_lan_ip() {
  local ip=""
  if [ "$OS" = mac ]; then
    ip="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)"
  else
    has ip && ip="$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -n1)"
    [ -n "$ip" ] || ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  fi
  printf '%s' "$ip"
}

set_root_env() {  # set_root_env KEY VALUE: replaces or appends in the root .env; the value is never printed or logged
  local file="$HESTIA_DIR/.env" tmp
  if [ "$DRY_RUN" = 1 ]; then printf '  [dry-run] .env %s=…\n' "$1"; return 0; fi
  touch "$file"; tmp="$file.hestia-tmp"
  grep -v "^$1=" "$file" > "$tmp" || true
  printf '%s=%s\n' "$1" "$2" >> "$tmp"
  cat "$tmp" > "$file"; rm -f "$tmp"
  log "env_set key=$1"
}

link_machine() {
  if [ "$ROLE" != satellite ]; then
    # Not (or no longer) a satellite: its Hub is the central one again.
    grep -Eq '^HUB_UPSTREAM_URL=.+' "$HESTIA_DIR/.env" 2>/dev/null || return 0
    log "[🔄] machine_unlink reason=role_$ROLE"
    set_root_env HUB_UPSTREAM_URL ""; set_root_env HUB_NODE_TOKEN ""; set_root_env HUB_NODE_ADDRESS ""
    return 0
  fi
  [ -n "$JOIN_CODE" ] || return 0   # already linked (re-run): keep the token
  [ -n "$LAN_IP" ] || fail "$(t "I cannot find this machine's address on the home network: connect it to Wi-Fi or cable and run again.")"
  say "$(t "Linking this machine to the central home ({0})…" "$CENTRAL_URL")"
  if [ "$DRY_RUN" = 1 ]; then printf '  [dry-run] POST %s/api/nodes/join\n' "$CENTRAL_URL"; return 0; fi
  local name out code token
  name="$(hostname 2>/dev/null | tr -cd 'A-Za-z0-9 ._-' | cut -c1-40)"
  out="$STATE_DIR/join.json"
  ( umask 077; : > "$out" )
  code="$(curl -sS --max-time 15 -o "$out" -w '%{http_code}' -H 'Content-Type: application/json' \
          -d "{\"code\": \"$JOIN_CODE\", \"name\": \"${name:-satellite}\", \"address\": \"$LAN_IP\"}" \
          "$CENTRAL_URL/api/nodes/join" 2>>"$LOG_FILE" || true)"
  token="$(sed -n 's/.*"token": *"\([A-Za-z0-9_-]*\)".*/\1/p' "$out")"
  rm -f "$out"
  log "machine_join status=$code"
  case "$code" in
    200) ;;
    000) fail "$(t "I cannot reach the central home at {0}: check that it is on and on the same network." "$CENTRAL_URL")" ;;
    403) fail "$(t "the code is wrong or expired: ask the central home for a new one (System → Machines).")" ;;
    *) fail "$(t "the central home refused the link (error {0})." "$code")" ;;
  esac
  [ -n "$token" ] || fail "$(t "the central home gave no link key: ask for a new code and run again.")"
  set_root_env HUB_UPSTREAM_URL "$CENTRAL_URL/api"
  set_root_env HUB_NODE_TOKEN "$token"
  set_root_env HUB_NODE_ADDRESS "$LAN_IP"
  token=""
  ok "$(t "Linked to the central home.")"
}

# Drops the containers this machine's role keeps stopped on purpose (reads names from stdin).
not_my_role() {
  local c
  while IFS= read -r c; do
    case "$ROLE" in
      satellite) case " $SATELLITE_SERVICES " in *" ${c#hestia_} "*) printf '%s\n' "$c" ;; esac ;;
      central) case " $HEAVY_SERVICES " in *" ${c#hestia_} "*) ;; *) printf '%s\n' "$c" ;; esac ;;
      *) printf '%s\n' "$c" ;;
    esac
  done
}

# The services of this machine's role (empty = all of them).
role_services() {
  case "$ROLE" in
    satellite) printf '%s\n' $SATELLITE_SERVICES ;;
    central) compose config --services 2>/dev/null | grep -vxE "$(printf '%s' "$HEAVY_SERVICES" | tr ' ' '|')" || true ;;
    *) ;;
  esac
}

# ── 7. .env files with generated secrets (python runs in a throwaway container, none needed on the host) ────────
ensure_env() {
  local args=(--generate-secrets)
  dk volume inspect "${PROJECT}_hestia_archive_pgdata" >/dev/null 2>&1 || args+=(--new-db)
  local user=()
  [ "$OS" = linux ] && user=(--user "$(id -u):$(id -g)")
  if retry "$(t "Preparing the configuration")" run "${DOCKER[@]}" run --rm ${user[@]+"${user[@]}"} -v "$HESTIA_DIR:/w" -w /w \
       python:3.12-slim python tools/init_env.py "${args[@]}"; then
    return 0
  fi
  log "[🔄] env_host_python reason=container_failed"
  has python3 && run_sh "cd '$HESTIA_DIR' && python3 tools/init_env.py ${args[*]}" && return 0
  fail "$(t "I cannot prepare the configuration files (.env).")"
}

# ── 8–9. images, start, health ─────────────────────────────────────────────────────────────────────────────────
start_stack() {
  dk network inspect hestia_net >/dev/null 2>&1 || run "${DOCKER[@]}" network create hestia_net \
    || fail "$(t "I cannot create the Docker network hestia_net.")"
  local services=() svc
  while IFS= read -r svc; do [ -n "$svc" ] && services+=("$svc"); done < <(role_services)
  if [ -n "$VERSION_TAG" ]; then
    say "$(t "Downloading the ready-made modules of version {0}…" "${VERSION_TAG}")"
    retry "$(t "Downloading the modules")" pull_with_progress --ignore-pull-failures ${services[@]+"${services[@]}"} \
      || note "$(t "Some modules did not download: I build them here.")"
  else
    say "$(t "Building the modules (the first time takes a while, then it is quick)…")"
    build_all ${services[@]+"${services[@]}"}
  fi
  say "$(t "Starting Hestia…")"
  if [ "$ROLE" = satellite ]; then
    # Only the satellite's own modules: everything else (memory, settings, the WebUI) lives on the central one.
    local others
    others="$(compose config --services 2>/dev/null | { grep -vxE "$(printf '%s' "$SATELLITE_SERVICES" | tr ' ' '|')" || true; } | tr '\n' ' ' || true)"
    [ -z "$others" ] || run_quiet_compose stop $others || true
    retry "$(t "Starting the modules")" run_quiet_compose up -d --no-deps --remove-orphans "${services[@]}" \
      || fail "$(t "the modules do not start. See {0} (last lines) or run again." "$LOG_FILE")"
    return 0
  fi
  [ "$ROLE" = central ] && { run_quiet_compose stop $HEAVY_SERVICES || true; }
  if ! telegram_configured; then
    # No bot token yet: Telegram would only crash-loop. Its container is created, not started: the guided setup
    # writes the token and starts it.
    [ ${#services[@]} -gt 0 ] || while IFS= read -r svc; do services+=("$svc"); done < <(compose config --services 2>/dev/null)
    local kept=()
    for svc in ${services[@]+"${services[@]}"}; do [ "$svc" = telegram ] || kept+=("$svc"); done
    services=(${kept[@]+"${kept[@]}"})
    note "$(t "Telegram is linked in the guided setup that opens in the browser.")"
  fi
  retry "$(t "Starting the modules")" run_quiet_compose up -d --remove-orphans ${services[@]+"${services[@]}"} \
    || fail "$(t "the modules do not start. See {0} (last lines) or run again." "$LOG_FILE")"
  if ! telegram_configured; then run_quiet_compose create telegram || true; fi
}

telegram_configured() {  # the value is never read into a variable or printed
  grep -Eq '^TELEGRAM_BOT_TOKEN=.+' "$HESTIA_DIR/Hestia-Telegram/app/.env" 2>/dev/null
}

# The download of the ready-made modules takes minutes: every module that arrives is shown (name, done/total), so a
# slow line never looks frozen. The full compose output still goes to the log.
pull_with_progress() {
  if [ "$DRY_RUN" = 1 ]; then printf '  [dry-run] docker compose pull %s\n' "$*"; return 0; fi
  log "compose args=\"pull $*\""
  local seen=" " got=" " nseen=0 ndone=0 line raw what name mark rc_file
  rc_file="$(mktemp)"
  { compose pull "$@" 2>&1; echo $? > "$rc_file"; } | while IFS= read -r line; do
    # Layer progress (Downloading/Extracting ... many lines a second) stays out of the log.
    case "$line" in *[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]" Downloading"*|\
                    *" Extracting"*|*" Waiting"*|*" Verifying"*) continue ;; esac
    printf '%s\n' "$line" >> "$LOG_FILE"
    raw="$(printf '%s' "$line" | sed -nE 's/.*[[:space:]]([^[:space:]]+)[[:space:]]+(Pulling|Pulled|Error)([[:space:]].*)?$/\1 \2/p')"
    [ -n "$raw" ] || continue
    what="${raw##* }"; raw="${raw% *}"
    case "$raw" in [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) continue ;; esac
    name="$(printf '%s' "$raw" | sed -nE 's/.*:([a-z0-9]+)-[0-9]+\.[0-9]+\.[0-9]+.*/\1/p')"
    [ -n "$name" ] || { name="${raw%%:*}"; name="${name##*/}"; }
    case "$seen" in *" $name "*) ;; *) seen="$seen$name "; nseen=$((nseen + 1)) ;; esac
    [ "$what" = Pulling ] && continue
    case "$got" in *" $name "*) continue ;; esac
    got="$got$name "; ndone=$((ndone + 1))
    if [ "$what" = Pulled ]; then mark="$(t "ready")"; else mark="$(t "not downloaded")"; fi
    printf '         %s %s (%s/%s)\n' "$name" "$mark" "$ndone" "$nseen"
  done
  local rc; rc="$(cat "$rc_file" 2>/dev/null)"; rm -f "$rc_file"
  [ "${rc:-1}" = 0 ]
}

run_quiet_compose() {
  if [ "$DRY_RUN" = 1 ]; then printf '  [dry-run] docker compose %s\n' "$*"; return 0; fi
  log "compose args=\"$*\""
  compose "$@" >> "$LOG_FILE" 2>&1
}

build_all() {  # build_all [service...]: none = all
  retry "$(t "Building the modules")" run_quiet_compose build "$@" && return 0
  # Find the one that breaks, rebuild it from scratch, then the rest.
  local svc bad="" list="$*"
  [ -n "$list" ] || list="$(compose config --services 2>/dev/null)"
  for svc in $list; do
    run_quiet_compose build "$svc" && continue
    log "[🔄] build_no_cache service=$svc"
    run_quiet_compose build --no-cache "$svc" || bad="$bad $svc"
  done
  [ -z "$bad" ] || fail "$(t "I cannot build:{0}. See {1}." "$bad" "$LOG_FILE")"
}

wait_healthy() {
  [ "$DRY_RUN" = 1 ] && return 0
  say "$(t "Waiting for every module to answer…")"
  local waited=0
  until curl -fsS --max-time 3 "$HUB_URL/health" >/dev/null 2>&1; do
    [ "$waited" -ge 300 ] && fail "$(t "the heart of Hestia (Hub) does not answer after 5 minutes.")"
    sleep 5; waited=$((waited + 5))
  done
  waited=0
  while :; do
    local down
    down="$(dk ps -a --filter "name=hestia_" --format '{{.Names}} {{.Status}}' | { grep -Ev ' (Up|Created)' || true; } | awk '{print $1}' | not_my_role | tr '\n' ' ')"
    if [ -z "$down" ] && { [ "$ROLE" = satellite ] || curl -fsS --max-time 3 "$WEBUI_URL" >/dev/null 2>&1; }; then
      ok "$(t "Every module is on.")"
      return 0
    fi
    if [ "$waited" -ge 600 ]; then
      local c
      for c in $down; do log "container_down name=$c"; dk logs --tail 20 "$c" >> "$LOG_FILE" 2>&1 || true; done
      note "$(t "These modules did not start: {0}(last lines in {1}). Hestia works without them anyway." "$down" "$LOG_FILE")"
      return 0
    fi
    sleep 10; waited=$((waited + 10))
  done
}

# ── 10. browser + shortcut ─────────────────────────────────────────────────────────────────────────────────────
finish() {
  if [ "$ROLE" = satellite ]; then
    echo
    ok "$(t "This machine is a satellite of {0}: voice and training run here." "${CENTRAL_URL:-$(t "the central home")}")"
    printf '         %s\n' "$(t "You manage it from the central home: System → Machines (also «Use its graphics card»).")"
    local n
    for n in ${NOTES[@]+"${NOTES[@]}"}; do printf '         · %s\n' "$n"; done
    log "install_done role=satellite version=${VERSION_TAG:-dev} notes=${#NOTES[@]}"
    return 0
  fi
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
  ok "$(t "Hestia is ready: {0} (the guided setup is at {1})" "$WEBUI_URL" "$SETUP_URL")"
  local n
  for n in ${NOTES[@]+"${NOTES[@]}"}; do printf '         · %s\n' "$n"; done
  printf '         %s\n' "$(t "To update or repair: run this same command again.")"
  log "install_done version=${VERSION_TAG:-dev} notes=${#NOTES[@]}"
}

# ── uninstall ──────────────────────────────────────────────────────────────────────────────────────────────────
uninstall() {
  [ -f "$HESTIA_DIR/docker-compose.global.yml" ] || fail "$(t "I cannot find Hestia in {0} (use --dir)." "$HESTIA_DIR")"
  docker_ready || fail "$(t "Docker does not answer: start it and run again.")"
  if [ "$PURGE" = 1 ]; then
    say "$(t "WARNING: I delete Hestia AND ALL ITS DATA (memories, chats, settings). There is no way back.")"
    local typed=""
    word="$(t "DELETE")"
    [ -r /dev/tty ] && read -r -p "[Hestia] $(t "Type {0} to confirm" "$word"): " typed < /dev/tty || true
    [ "$typed" = "$word" ] || fail "$(t "I deleted nothing (no confirmation).")"
    run_quiet_compose down -v --remove-orphans || true
    run rm -rf "$HESTIA_DIR"
    run rm -rf "$STATE_DIR"
    ok "$(t "Hestia and its data have been deleted.")"
  else
    run_quiet_compose down --remove-orphans || true
    ok "$(t "Hestia is off and the containers removed. The data stay (folder {0} and Docker volumes); --purge to delete them." "$HESTIA_DIR")"
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
      --lang) UI_LANG="$(lang_code "$2")"; shift ;;
      --lang=*) UI_LANG="$(lang_code "${1#*=}")" ;;
      --role) ROLE="$2"; shift ;;
      --role=*) ROLE="${1#*=}" ;;
      --join) JOIN_CODE="$2"; shift ;;
      --join=*) JOIN_CODE="${1#*=}" ;;
      --central) CENTRAL_URL="$2"; shift ;;
      --central=*) CENTRAL_URL="${1#*=}" ;;
      -h|--help) usage ;;
      *) fail "$(t "unknown option: {0} (see --help)" "$1")" ;;
    esac
    shift
  done
  load_texts
  case "$CHANNEL" in latest) CHANNEL=news ;; esac
  case "$CHANNEL" in stable|news) ;; *) fail "$(t "unknown channel: {0} (stable or latest)" "$CHANNEL")" ;; esac
  case "$ROLE" in ''|all|central|satellite) ;; *) fail "$(t "unknown role: {0} (all, central or satellite)" "$ROLE")" ;; esac
  if [ -n "$JOIN_CODE" ]; then
    [ -z "$ROLE" ] || [ "$ROLE" = satellite ] || fail "$(t "--join is only for a satellite.")"
    ROLE=satellite
    [ -n "$CENTRAL_URL" ] || fail "$(t "--join also needs --central (the address of the central home, e.g. 192.168.1.10).")"
    JOIN_CODE="$(printf '%s' "$JOIN_CODE" | tr -cd '0-9')"
  fi
  if [ -n "$CENTRAL_URL" ]; then   # 192.168.1.10 → http://192.168.1.10:19001
    CENTRAL_URL="${CENTRAL_URL%/}"; CENTRAL_URL="${CENTRAL_URL%/api}"
    case "$CENTRAL_URL" in http://*|https://*) ;; *) CENTRAL_URL="http://$CENTRAL_URL" ;; esac
    case "${CENTRAL_URL#*://}" in *:*) ;; *) CENTRAL_URL="$CENTRAL_URL:19001" ;; esac
  fi
  return 0
}

main() {
  parse_args "$@"
  mkdir -p "$STATE_DIR"
  log "install_start action=$ACTION channel=$CHANNEL dry_run=$DRY_RUN"
  detect_os
  if [ "$ACTION" = uninstall ]; then uninstall; return 0; fi
  say "$(t "Installing Hestia in {0} (channel {1}). I will ask for the computer password at most once." "$HESTIA_DIR" "$CHANNEL")"
  preflight
  resolve_role
  ensure_git;    state_mark git
  ensure_docker; state_mark docker
  ports_check
  ensure_ollama; state_mark ollama
  ensure_code;   state_mark code
  write_hardware
  ensure_env;    state_mark env
  link_machine
  start_stack;   state_mark started
  wait_healthy;  state_mark healthy
  finish
}

# Everything runs from here: a download cut halfway through (curl | bash) never executes half a script.
main "$@"
