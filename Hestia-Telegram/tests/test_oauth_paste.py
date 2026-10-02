"""Pasted OAuth callback URLs go straight to Hecate (no LLM in the loop)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from telegram_bot.services import oauth_paste


@pytest.mark.unit
def test_match_google_callback_url():
    url = "http://localhost:19003/api/gateway/auth/callback/google?state=S&code=4/0Ab&scope=x"
    assert oauth_paste.match_oauth_callback(f"ecco {url}") == ("google", url)


@pytest.mark.unit
@pytest.mark.parametrize("text", ["ciao", "http://localhost:19003/health", "code=abc"])
def test_no_match_for_normal_text(text):
    assert oauth_paste.match_oauth_callback(text) is None


@pytest.mark.unit
def test_complete_success_reply():
    with patch.object(oauth_paste, "route_service_command",
                      return_value=(True, {"status": "authorized"})) as route:
        reply = oauth_paste.complete_oauth_from_paste("google", "http://x/api/gateway/auth/callback/google?code=1")
    assert "collegato" in reply
    assert route.call_args.kwargs["path"] == "/api/gateway/auth/complete/google"
    assert route.call_args.kwargs["body"] == {"code": "http://x/api/gateway/auth/callback/google?code=1"}


@pytest.mark.unit
def test_complete_error_reply_shows_hint():
    payload = {"detail": {"error": "Token exchange failed: invalid_grant", "hint": "Run initiate again."}}
    with patch.object(oauth_paste, "route_service_command", return_value=(False, payload)):
        reply = oauth_paste.complete_oauth_from_paste("google", "u")
    assert "invalid_grant" in reply and "Run initiate again." in reply
