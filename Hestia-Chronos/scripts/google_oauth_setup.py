"""One-time helper: run this on the HOST (not inside Docker) to obtain a
Google OAuth2 user token.  The resulting token.json content should be
placed in the GOOGLE_TOKEN_JSON environment variable.

Requirements (host only):
    pip install google-auth-oauthlib google-api-python-client

Usage:
    1. Create a "Desktop app" OAuth 2.0 Client ID in the Google Cloud Console.
    2. Download the credentials JSON and save it as credentials.json.
    3. Run: python scripts/google_oauth_setup.py
    4. Copy the token.json content into GOOGLE_TOKEN_JSON in your .env file.
"""
import json
import os

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

SCOPES = ["https://www.googleapis.com/auth/calendar"]
CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.json"


def main():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    print("\nToken saved to token.json. Its content:")
    print("-" * 60)
    with open(TOKEN_FILE) as f:
        print(f.read())
    print("-" * 60)
    print("\nPaste the above JSON (as a single-line string) into GOOGLE_TOKEN_JSON in your .env file.")


if __name__ == "__main__":
    main()
