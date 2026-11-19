#!/usr/bin/env bash
# Linux/macOS twin of up-all.bat: start or restart the whole stack from the repo folder.
#   ./up-all.sh            bring up stopped containers, then restart all (picks up code changes)
#   ./up-all.sh --build    full rebuild (dependencies changed)
#   ./up-all.sh oracle …   restart only these services
# First install, repair or update: install.sh (it also creates the .env files and checks health).
set -euo pipefail
cd "$(dirname "$0")"
COMPOSE=(docker compose -f docker-compose.global.yml)
# Messages in the computer's language when Hestia has a catalog for it (same file as install.sh), else English.
LANG_CODE="$(printf '%s' "${HESTIA_LANG:-${LC_ALL:-${LC_MESSAGES:-${LANG:-en}}}}" | cut -c1-2 | tr '[:upper:]' '[:lower:]')"
TEXTS="Hestia-Shared/hestia_common/locales/$LANG_CODE/installer.tsv"
say() {
  local text="$1" found=""
  [ -f "$TEXTS" ] && found="$(awk -F '\t' -v k="$1" '$1 == k { print $2; exit }' "$TEXTS" 2>/dev/null || true)"
  [ -n "$found" ] && text="$found"
  printf '[Hestia] %s%s\n' "$text" "${2:-}"
}

if ! docker info >/dev/null 2>&1; then
  say "Docker is not answering: start it (sudo systemctl start docker, or Docker Desktop) and run again."
  exit 1
fi
if ! docker network inspect hestia_net >/dev/null 2>&1; then
  say "Creating the shared Docker network: hestia_net"
  docker network create hestia_net >/dev/null
fi

case "${1:-}" in
  --build)
    shift
    say "FULL REBUILD (dependencies changed)..."
    find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
    "${COMPOSE[@]}" down
    "${COMPOSE[@]}" up -d --build "$@"
    ;;
  "")
    say "Bringing up the stopped containers..."
    "${COMPOSE[@]}" up -d
    say "Restarting ALL services to pick up the code changes..."
    "${COMPOSE[@]}" restart
    ;;
  *)
    say "Restarting: " "$*"
    "${COMPOSE[@]}" restart "$@"
    ;;
esac
