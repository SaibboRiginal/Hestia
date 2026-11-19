@echo off
setlocal
rem Messages in the language of Windows when Hestia has a catalog for it (same file as install.ps1), else English.

docker info >nul 2>&1
if errorlevel 1 (
    call :say "Docker is not answering: start Docker Desktop, wait until it is running and launch again."
    exit /b 1
)

docker network inspect hestia_net >nul 2>&1
if errorlevel 1 (
    call :say "Creating the shared Docker network: hestia_net"
    docker network create hestia_net >nul
)

if "%~1"=="--build" goto :build
if "%~1"=="" goto :start
goto :restart

:build
call :say "FULL REBUILD (dependencies changed)..."
call :say "Clearing the Python cache..."
for /d /r %%d in (__pycache__) do @if exist "%%d" rmdir /s /q "%%d"
call :say "Stopping the running containers first..."
docker compose -f docker-compose.global.yml down
call :say "Starting with a fresh build..."
docker compose -f docker-compose.global.yml up -d --build %2 %3 %4 %5
goto :end
endlocal
exit /b 0

:say
set "HX_MSG=%~1"
set "HX_TAIL=%~2"
powershell -NoProfile -Command "$k=$env:HX_MSG; $t=$k; $f='Hestia-Shared\hestia_common\locales\'+(Get-UICulture).TwoLetterISOLanguageName+'\installer.tsv'; if (Test-Path $f) { foreach ($x in [IO.File]::ReadAllLines($f, [Text.Encoding]::UTF8)) { $p=$x.Split([char]9); if ($p[0] -ceq $k) { $t=$p[1] } } }; Write-Host ('[Hestia] ' + $t + $env:HX_TAIL)"
exit /b 0
