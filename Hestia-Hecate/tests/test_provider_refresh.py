"""Unit tests for provider refresh() methods."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# GoogleCalendarProvider.refresh()
# ---------------------------------------------------------------------------


def test_google_provider_refresh_rebuilds_service(monkeypatch):
    """refresh() should re-call _setup and report is_available() truthfully."""
    from app.providers.google import GoogleCalendarProvider

    with patch.object(GoogleCalendarProvider, "_setup") as mock_setup:
        provider = GoogleCalendarProvider.__new__(GoogleCalendarProvider)
        provider._service = MagicMock()
        provider._init_error = None

        def side_effect():
            provider._service = MagicMock()
            provider._init_error = None

        mock_setup.side_effect = side_effect

        result = provider.refresh()

    assert result is True
    mock_setup.assert_called_once()


def test_google_provider_refresh_returns_false_on_failure(monkeypatch):
    """If credentials are unavailable after refresh, returns False."""
    from app.providers.google import GoogleCalendarProvider

    with patch.object(GoogleCalendarProvider, "_setup") as mock_setup:
        provider = GoogleCalendarProvider.__new__(GoogleCalendarProvider)
        provider._service = None
        provider._init_error = "no creds"

        def side_effect():
            provider._service = None
            provider._init_error = "still no creds"

        mock_setup.side_effect = side_effect

        result = provider.refresh()

    assert result is False


# ---------------------------------------------------------------------------
# OutlookCalendarProvider.refresh()
# ---------------------------------------------------------------------------


def test_outlook_provider_refresh_rebuilds_token(monkeypatch):
    """refresh() should re-call _setup and return is_available() result."""
    from app.providers.outlook import OutlookCalendarProvider

    with patch.object(OutlookCalendarProvider, "_setup") as mock_setup:
        provider = OutlookCalendarProvider.__new__(OutlookCalendarProvider)
        provider._token = "old-token"
        provider._user_id = "me"
        provider._init_error = None

        def side_effect():
            provider._token = "new-token"
            provider._init_error = None

        mock_setup.side_effect = side_effect

        result = provider.refresh()

    assert result is True
    mock_setup.assert_called_once()


def test_outlook_provider_refresh_returns_false_when_token_missing():
    """If MSAL cannot acquire a new token, is_available() is False."""
    from app.providers.outlook import OutlookCalendarProvider

    with patch.object(OutlookCalendarProvider, "_setup") as mock_setup:
        provider = OutlookCalendarProvider.__new__(OutlookCalendarProvider)
        provider._token = None
        provider._user_id = "me"
        provider._init_error = None

        def side_effect():
            provider._token = None
            provider._init_error = "Token acquisition failed"

        mock_setup.side_effect = side_effect

        result = provider.refresh()

    assert result is False
