@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

set MODE=%1
set TARGET=%2
if "%MODE%"=="" set MODE=all

echo.
echo ============================================================
echo   Hestia Test Suite  -  %MODE%
echo ============================================================

REM -- Single service -------------------------------------------------
if /I "%MODE%"=="service" (
    if "%TARGET%"=="" (
        echo Usage: run-tests.bat service ^<name^>
        for /d %%d in (Hestia-*) do echo   - %%~nxd
        exit /b 1
    )
    set "DIR=Hestia-%TARGET%"
    if not exist "!DIR!\tests" (
        echo Not found: !DIR!\tests
        exit /b 1
    )
    python -m pytest "!DIR!\tests" --ignore="!DIR!\tests\test_live_formatting.py" --ignore="!DIR!\tests\test_live_tool_calling.py" --ignore="!DIR!\tests\test_live_tool_calling_comprehensive.py" --ignore="!DIR!\tests\test_live_all_tools.py" -v --tb=short
    goto :end
)

REM -- All / Unit -----------------------------------------------------
set FAILED=
set PASSED=0
set COUNT=0
for /d %%d in (Hestia-*) do (
    if exist "%%d\tests" (
        set /a COUNT+=1
        set NAME=%%~nxd
        echo.
        echo ============================================================
        echo   !NAME!
        echo ============================================================
        if /I "%MODE%"=="unit" (
            python -m pytest "%%d\tests" --ignore="%%d\tests\test_live_formatting.py" --ignore="%%d\tests\test_live_tool_calling.py" --ignore="%%d\tests\test_live_tool_calling_comprehensive.py" --ignore="%%d\tests\test_live_all_tools.py" -m unit -v --tb=short 2>&1
        ) else (
            python -m pytest "%%d\tests" --ignore="%%d\tests\test_live_formatting.py" --ignore="%%d\tests\test_live_tool_calling.py" --ignore="%%d\tests\test_live_tool_calling_comprehensive.py" --ignore="%%d\tests\test_live_all_tools.py" -v --tb=short 2>&1
        )
        if !ERRORLEVEL! NEQ 0 (
            set "FAILED=!FAILED!  !NAME!"
        ) else (
            set /a PASSED+=1
        )
    )
)

REM -- Summary ---------------------------------------------------------
set /a FAILCOUNT=%COUNT% - %PASSED%
echo.
echo ============================================================
echo   SUMMARY
echo ============================================================
echo   Services tested: %COUNT%
echo   Passed: %PASSED%
echo   Failed: %FAILCOUNT%
if defined FAILED (
    echo   Failed services:
    echo !FAILED!
    echo ============================================================
    echo   RESULT: SOME TESTS FAILED
    exit /b 1
) else (
    echo ============================================================
    echo   RESULT: ALL TESTS PASSED
)

:end
echo.
