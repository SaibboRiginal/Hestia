@echo off
rem Hestia: install, repair or update with a double-click (Windows). Runs install.ps1 next to this file if present,
rem otherwise the latest one from GitHub. Extra arguments go to install.ps1 (e.g. -Dir D:\Hestia, -Uninstall).
setlocal
set "HERE=%~dp0"
if exist "%HERE%install.ps1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%HERE%install.ps1" %*
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "& ([scriptblock]::Create(((Invoke-RestMethod -UseBasicParsing 'https://raw.githubusercontent.com/SaibboRiginal/Hestia/main/install.ps1') -replace '^\uFEFF',''))) %*"
)
echo.
pause
endlocal
