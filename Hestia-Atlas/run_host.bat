@echo off
setlocal

set "ROOT_DIR=%~dp0"
set "EDGE_DATA_DIR=%ROOT_DIR%data\edge_profile"
if not exist "%EDGE_DATA_DIR%" mkdir "%EDGE_DATA_DIR%"

if not exist .venv (
  python -m venv .venv
)
call .venv\Scripts\activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 19014
