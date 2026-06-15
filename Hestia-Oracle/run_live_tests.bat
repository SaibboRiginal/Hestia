@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
cd /d "%~dp0"

set EXTRA=%1
if "%EXTRA%"=="" set EXTRA=-v

echo.
echo ============================================================
echo   Hestia-Oracle -- Live LLM Tool-Calling Tests
echo ============================================================
echo.

python -c "import urllib.request; urllib.request.urlopen('http://localhost:11434/api/tags', timeout=3); print('Ollama: REACHABLE')" 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [FAIL] Ollama is not reachable at http://localhost:11434
    echo        Start Ollama and try again.
    exit /b 1
)

echo.
echo === Available Ollama models ===
python -c "import requests,json; d=requests.get('http://localhost:11434/api/tags',timeout=5).json(); [print(f'  - {m[\"name\"]}') for m in d.get('models',[])]"
echo.

echo === 1/2  All Tools by Domain ===
echo.
python -m pytest tests/test_live_all_tools.py -m llm_live --run-live %EXTRA% --tb=long

echo.
echo === 2/2  Tool-Calling Comprehensive ===
echo.
python -m pytest tests/test_live_tool_calling_comprehensive.py -m llm_live --run-live %EXTRA% --tb=long

echo.
echo ============================================================
echo   Run complete.
echo ============================================================
