@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
cd /d "%~dp0"

set MODE=%1
set TARGET=%2
set EXTRA=%3

if "%MODE%"=="" set MODE=all
if "%EXTRA%"=="" set EXTRA=-v

echo.
echo ============================================================
echo   Hestia Test Suite
echo ============================================================
echo   Mode: %MODE%
echo   Target: %TARGET%
echo ============================================================
echo.

if /I "%MODE%"=="all" (
    echo === Running ALL tests (per-service to avoid import collisions) ===
    set "FAILED_SERVICES="
    set "TOTAL_PASSED=0"
    set "TOTAL_FAILED=0"
    for /d %%d in (Hestia-*) do (
        if exist "%%d\tests" (
            echo.
            echo --- %%~nxd ---
            python -m pytest %%d\tests %EXTRA% --tb=short
            if !ERRORLEVEL! NEQ 0 (
                set "FAILED_SERVICES=!FAILED_SERVICES! %%~nxd"
                set /a TOTAL_FAILED+=1
            ) else (
                set /a TOTAL_PASSED+=1
            )
        )
    )
    echo.
    if "!FAILED_SERVICES!"=="" (
        echo All services passed.
    ) else (
        echo Failed services:!FAILED_SERVICES!
    )
    goto :end
)

if /I "%MODE%"=="unit" (
    echo === Running unit tests (per-service) ===
    for /d %%d in (Hestia-*) do (
        if exist "%%d\tests" (
            echo --- %%~nxd ---
            python -m pytest %%d\tests -m unit %EXTRA% --tb=short 2>nul
        )
    )
    goto :end
)

if /I "%MODE%"=="api" (
    echo === Running API + format tests (per-service) ===
    for /d %%d in (Hestia-*) do (
        if exist "%%d\tests" (
            echo --- %%~nxd ---
            python -m pytest %%d\tests -m "api or format" %EXTRA% --tb=short 2>nul
        )
    )
    goto :end
)

if /I "%MODE%"=="live" (
    echo === Running live LLM tests ===
    echo Checking Ollama...
    python -c "import urllib.request; urllib.request.urlopen('http://localhost:11434/api/tags', timeout=3); print('Ollama: REACHABLE')" 2>nul
    if %ERRORLEVEL% NEQ 0 (
        echo [FAIL] Ollama is not reachable at http://localhost:11434
        echo        Start Ollama and try again.
        exit /b 1
    )
    for /d %%d in (Hestia-*) do (
        if exist "%%d\tests" (
            echo --- %%~nxd ---
            python -m pytest %%d\tests -m llm_live --run-live %EXTRA% --tb=long 2>nul
        )
    )
    goto :end
)

if /I "%MODE%"=="service" (
    if "%TARGET%"=="" (
        echo Usage: run-tests.bat service ^<name^>
        echo Example: run-tests.bat service oracle
        echo.
        echo Available services:
        for /d %%d in (Hestia-*) do echo   - %%~nxd
        exit /b 1
    )
    set "SVC_DIR=Hestia-%TARGET%"
    if not exist "!SVC_DIR!\tests" (
        echo [FAIL] !SVC_DIR!\tests not found
        exit /b 1
    )
    echo === Running tests for !SVC_DIR! ===
    python -m pytest !SVC_DIR!\tests %EXTRA% --tb=short
    goto :end
)

echo.
echo Usage:
echo   run-tests.bat                  Run all tests
echo   run-tests.bat all              Run all tests
echo   run-tests.bat unit             Run unit tests only (fast, mocked)
echo   run-tests.bat api              Run API + format tests
echo   run-tests.bat live             Run live LLM tests (requires Ollama)
echo   run-tests.bat service ^<name^>  Run tests for one service
echo.
echo Examples:
echo   run-tests.bat service oracle
echo   run-tests.bat service telegram
echo   run-tests.bat service scout
echo.

:end
echo.
echo ============================================================
echo   Done.
echo ============================================================
