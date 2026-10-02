#!/usr/bin/env sh
# Hestia-Hecate — Google OAuth setup (Linux / macOS / Raspberry Pi host).
# Needs a browser on this machine. Headless? Use Telegram: "collega Google Calendar".
cd "$(dirname "$0")" || exit 1
python3 -c "import google_auth_oauthlib" 2>/dev/null || pip3 install --user google-auth-oauthlib google-api-python-client
python3 tools/google_auth.py "$@"
