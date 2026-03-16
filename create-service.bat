@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "RAW_NAME=%~1"
set "SERVICE_TYPE=%~2"
set "SERVICE_PORT=%~3"

if "%RAW_NAME%"=="" goto :usage
if "%SERVICE_TYPE%"=="" set "SERVICE_TYPE=integration"
if "%SERVICE_PORT%"=="" set "SERVICE_PORT=8099"

if /I not "%SERVICE_TYPE%"=="core" if /I not "%SERVICE_TYPE%"=="module" if /I not "%SERVICE_TYPE%"=="integration" (
  echo [!] Invalid service type: %SERVICE_TYPE%
  echo     Allowed: core ^| module ^| integration
  exit /b 1
)

set "ROOT_DIR=%~dp0"
set "TEMPLATE_DIR=%ROOT_DIR%templates\python-service-template"

if not exist "%TEMPLATE_DIR%\app\main.py" (
  echo [!] Template not found at %TEMPLATE_DIR%
  exit /b 1
)

for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "$s='%RAW_NAME%'.ToLower(); $s=$s -replace '^hestia-',''; $s=$s -replace '[^a-z0-9]+','_'; $s=$s.Trim('_'); if([string]::IsNullOrWhiteSpace($s)){exit 2}; Write-Output $s"`) do set "SERVICE_KEY=%%i"
if not defined SERVICE_KEY (
  echo [!] Failed to derive a valid service key from: %RAW_NAME%
  exit /b 1
)

for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "$parts='%SERVICE_KEY%'.Split('_'); $title=($parts | ForEach-Object { if($_.Length -gt 0){ $_.Substring(0,1).ToUpper()+$_.Substring(1)} }) -join '-'; Write-Output $title"`) do set "SERVICE_TITLE=%%i"
if not defined SERVICE_TITLE (
  echo [!] Failed to derive service folder title from key: %SERVICE_KEY%
  exit /b 1
)

set "TARGET_DIR=%ROOT_DIR%Hestia-%SERVICE_TITLE%"
if exist "%TARGET_DIR%" (
  echo [!] Target already exists: %TARGET_DIR%
  exit /b 1
)

echo [*] Creating service scaffold: Hestia-%SERVICE_TITLE%
mkdir "%TARGET_DIR%"
xcopy "%TEMPLATE_DIR%\*" "%TARGET_DIR%\" /E /I /Y >nul
if errorlevel 1 (
  echo [!] Failed to copy template files.
  exit /b 1
)

(
  echo SERVICE_NAME=%SERVICE_KEY%
  echo SERVICE_BASE_URL=http://hestia_%SERVICE_KEY%:%SERVICE_PORT%
  echo SERVICE_VERSION=1.0.0
  echo SERVICE_TYPE=%SERVICE_TYPE%
  echo SERVICE_TAGS=%SERVICE_TYPE%
  echo HUB_API_URL=http://hestia_hub:8005/api
) > "%TARGET_DIR%\app\.env"

powershell -NoProfile -Command "$files=@('%TARGET_DIR%\Dockerfile','%TARGET_DIR%\docker-compose.yml','%TARGET_DIR%\app\.env.example'); foreach($f in $files){ $c=Get-Content -Raw $f; $c=$c.Replace('__SERVICE_KEY__','%SERVICE_KEY%').Replace('__SERVICE_PORT__','%SERVICE_PORT%'); Set-Content -NoNewline -Path $f -Value $c }"
if errorlevel 1 (
  echo [!] Failed while replacing template placeholders.
  exit /b 1
)

echo [✓] Service created at: %TARGET_DIR%
echo [i] Next steps:
echo     1. cd Hestia-%SERVICE_TITLE%
echo     2. Edit app\main.py and implement your endpoints/capabilities
echo     3. docker compose up --build -d
echo     4. Optional: add service into root docker-compose.global.yml
exit /b 0

:usage
echo Usage:
echo   create-service.bat ^<name^> [core^|module^|integration] [port]
echo Examples:
echo   create-service.bat Markets module 8012
echo   create-service.bat hestia-news core 8013
exit /b 1
