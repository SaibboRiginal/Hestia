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
echo [Hestia] Clearing Python cache...
for /d /r %%d in (__pycache__) do @if exist "%%d" rmdir /s /q "%%d"
echo [Hestia] Stopping existing containers first...
docker compose -f docker-compose.global.yml down
echo [Hestia] Starting with fresh build...
docker compose -f docker-compose.global.yml up -d --build %2 %3 %4 %5
goto :end

:start
echo [Hestia] Bringing up any stopped containers...
docker compose -f docker-compose.global.yml up -d
echo [Hestia] Restarting ALL services to pick up code changes...
docker compose -f docker-compose.global.yml restart
goto :end

:restart
echo [Hestia] Restarting: %*
docker compose -f docker-compose.global.yml restart %*
goto :end

:end
endlocal
