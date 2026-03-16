@echo off
setlocal

if "%ARCHIVE_DATABASE_URL%"=="" (
  echo [Hestia] ERROR: ARCHIVE_DATABASE_URL is not set.
  echo Example:
  echo   set ARCHIVE_DATABASE_URL=postgresql://user:pass@host:5432/dbname
  exit /b 1
)

docker network inspect hestia_net >nul 2>&1
if errorlevel 1 (
  echo [Hestia] Creating shared Docker network: hestia_net
  docker network create hestia_net >nul
)

echo [Hestia] Building and starting Raspberry core stack...
docker compose -f docker-compose.rpi.yml up -d --build

endlocal
