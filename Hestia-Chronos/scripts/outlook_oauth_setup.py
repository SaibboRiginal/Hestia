"""One-time helper: run this on the HOST (not inside Docker) to obtain a
Microsoft OAuth2 refresh token for personal Outlook/Microsoft accounts.

Requirements (host only):
    pip install msal

Usage:
    1. Register an app in Azure Portal → App Registrations.
    2. Set "Accounts in any organizational directory and personal Microsoft accounts"
       as the supported account type.
    3. Add Delegated permission: Calendars.ReadWrite (Microsoft Graph).
    4. Note the Application (client) ID.
    5. Run: python scripts/outlook_oauth_setup.py --client-id YOUR_CLIENT_ID
    6. Follow the device code prompt in your browser.
    7. Copy the refresh_token into OUTLOOK_REFRESH_TOKEN in your .env file.
"""
import argparse
import json

import msal

SCOPES = ["https://graph.microsoft.com/Calendars.ReadWrite", "offline_access"]
TENANT = "consumers"  # personal Microsoft accounts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--client-id", required=True,
                        help="Azure app client ID")
    args = parser.parse_args()

    authority = f"https://login.microsoftonline.com/{TENANT}"
    app = msal.PublicClientApplication(args.client_id, authority=authority)

    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        print("Failed to create device flow:", json.dumps(flow, indent=2))
        return

    print(flow["message"])
    result = app.acquire_token_by_device_flow(flow)

    if "refresh_token" in result:
        print("\nAuthentication successful!")
        print("\nRefresh token (copy into OUTLOOK_REFRESH_TOKEN):")
        print("-" * 60)
        print(result["refresh_token"])
        print("-" * 60)
    else:
        print("Authentication failed:", result.get("error_description"))


if __name__ == "__main__":
    main()
