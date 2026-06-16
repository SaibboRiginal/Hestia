@echo off
setlocal

docker network inspect hestia_net >nul 2>&1
if errorlevel 1 (
    echo [Hestia] Creating shared Docker network: hestia_net
    docker network create hestia_net >/dev/null
)

if "%~1"=="--build" goto :build
if "%~1"=="" goto :start
goto :restart

:build
echo [Hestia] FULL REBUILD (dependencies changed) ...
docker compose -f docker-compose.global.yml up -d --build %2 %3 %4 %5
goto :end

:start
echo [Hestia] Starting stack (code mounts are live - restart is instant) ...
echo [Hestia] Use up-all --build only when requirements.txt or Dockerfile changed
docker compose -f docker-compose.global.yml up -d
goto :end

:restart
echo [Hestia] Restarting: %*
docker compose -f docker-compose.global.yml restart %*
goto :end

:end
endlocal
