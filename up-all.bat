@echo off
setlocal

docker network inspect hestia_net >nul 2>&1
if errorlevel 1 (
	echo [Hestia] Creating shared Docker network: hestia_net
	docker network create hestia_net >nul
)

if "%~1"=="" (
	echo [Hestia] Building and starting full stack...
	docker compose -f docker-compose.global.yml up -d --build
) else (
	echo [Hestia] Rebuilding: %*
	docker compose -f docker-compose.global.yml up -d --build %*
)

endlocal
