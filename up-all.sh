#!/usr/bin/env bash
# Linux/macOS twin of up-all.bat: start or restart the whole stack from the repo folder.
#   ./up-all.sh            bring up stopped containers, then restart all (picks up code changes)
#   ./up-all.sh --build    full rebuild (dependencies changed)
#   ./up-all.sh oracle …   restart only these services
# First install, repair or update: install.sh (it also creates the .env files and checks health).
set -euo pipefail
cd "$(dirname "$0")"
COMPOSE=(docker compose -f docker-compose.global.yml)

if ! docker info >/dev/null 2>&1; then
  echo "[Hestia] Docker non risponde: avvialo (sudo systemctl start docker, o Docker Desktop) e rilancia."
  exit 1
fi
if ! docker network inspect hestia_net >/dev/null 2>&1; then
  echo "[Hestia] Creating shared Docker network: hestia_net"
  docker network create hestia_net >/dev/null
fi

case "${1:-}" in
  --build)
    shift
    echo "[Hestia] FULL REBUILD (dependencies changed) ..."
    find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
    "${COMPOSE[@]}" down
    "${COMPOSE[@]}" up -d --build "$@"
    ;;
  "")
    echo "[Hestia] Bringing up any stopped containers..."
    "${COMPOSE[@]}" up -d
    echo "[Hestia] Restarting ALL services to pick up code changes..."
    "${COMPOSE[@]}" restart
    ;;
  *)
    echo "[Hestia] Restarting: $*"
    "${COMPOSE[@]}" restart "$@"
    ;;
esac
