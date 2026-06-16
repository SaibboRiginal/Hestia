@echo off
cd /d "%~dp0"
echo.
echo ============================================
echo   Hestia-Hecate — Google OAuth Setup
echo ============================================
echo.
echo This opens your browser so you can grant
echo calendar access to Hestia. The token is
echo saved to data\google_token.json and survives
echo Docker restarts automatically.
echo.
echo You only need to run this ONCE.
echo ============================================
echo.

python tools/google_auth.py

echo.
echo Done! Hecate will pick up the token on the next startup.
echo.
pause
