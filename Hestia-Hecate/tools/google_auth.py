"""Google OAuth helper — runs on the HOST (Windows) to obtain a refresh token.

Opens your browser automatically, handles the redirect locally, and persists the
result to ``data/google_token.json`` (volume-mounted, survives Docker restarts).

Requirements (host only, one-time):
    pip install google-auth-oauthlib google-api-python-client

Usage:
    python scripts/google_auth.py
    :: or just double-click: google-oauth.bat
"""
import json
import os
import sys
from pathlib import Path

# -- project root detection ------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]  # Hestia-Hecate/
DATA_DIR = ROOT / "data"
ENV_FILE = ROOT / "app" / ".env"
TOKEN_FILE = DATA_DIR / "google_token.json"

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _load_env_vars(env_path: Path) -> dict:
    """Read KEY=VALUE pairs from a .env file (simple parser, no dotenv dep)."""
    env = {}
    if not env_path.exists():
        return env
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value:
            env[key] = value
    return env


def main():
    # 1) Load client_id / client_secret from .env
    env = _load_env_vars(ENV_FILE)
    client_id = env.get("GOOGLE_CLIENT_ID", "").strip()
    client_secret = env.get("GOOGLE_CLIENT_SECRET", "").strip()

    if not client_id or not client_secret:
        print("ERROR: GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set in:")
        print(f"       {ENV_FILE}")
        sys.exit(1)

    # 2) Check for an existing valid token (skip flow if still good)
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    creds = None
    if TOKEN_FILE.exists():
        try:
            creds = Credentials.from_authorized_user_file(
                str(TOKEN_FILE), SCOPES)
        except Exception:
            pass

    if creds and creds.valid:
        print("Existing token is still valid — no re-auth needed.")
        _print_summary(creds)
        return

    if creds and creds.expired and creds.refresh_token:
        print("Existing token expired — refreshing...")
        try:
            creds.refresh(Request())
            _persist(creds)
            print("Token refreshed successfully.")
            _print_summary(creds)
            return
        except Exception as exc:
            print(f"Refresh failed ({exc}) — starting full OAuth flow...\n")

    # 3) Full OAuth flow (opens browser automatically)
    from google_auth_oauthlib.flow import InstalledAppFlow

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob",
                               "http://localhost"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }

    flow = InstalledAppFlow.from_client_config(
        client_config, SCOPES)

    print("Opening browser for Google authorization...")
    print("If the browser doesn't open, check the console for a URL.\n")

    creds = flow.run_local_server(
        port=0,
        authorization_prompt_message="",
        success_message="Authorization complete! You may close this tab.",
        open_browser=True,
    )

    _persist(creds)
    print("Token saved.")
    _print_summary(creds)


def _persist(creds):
    """Write token to the volume-mounted data/ directory."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": getattr(creds, "token_uri",
                              "https://oauth2.googleapis.com/token"),
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or SCOPES),
    }
    TOKEN_FILE.write_text(json.dumps(token_data, indent=2), encoding="utf-8")
    print(f"\nToken persisted to: {TOKEN_FILE}")


def _print_summary(creds):
    print(f"\n  refresh_token: {creds.refresh_token}")
    print(f"  access_token:  {creds.token[:30]}...")
    print(f"  expiry:        {getattr(creds, 'expiry', '?')}")
    print(f"\n  Copy this line into {ENV_FILE} if you want a bootstrap fallback:")
    print(f"  GOOGLE_REFRESH_TOKEN={creds.refresh_token}")


if __name__ == "__main__":
    main()
