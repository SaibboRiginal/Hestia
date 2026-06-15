"""Telegram test conftest — env setup, bot stubs, and HTTP mocks.

CRITICAL: TELEGRAM_BOT_TOKEN must be set before any telebot import, which
happens the moment telegram_bot.core is first imported. This conftest
sets the token in os.environ BEFORE any test module is loaded.

Fixtures:
    fake_message: Factory for a minimal telebot Message object.
    mock_bot: MagicMock standing in for core.bot.
    mock_oracle_stream: Patches the streaming NDJSON Oracle call.
    mock_hub_commands: Patches Hub command discovery with a fixed catalog.
    mock_archive_memory: Patches Archive memory retrieval.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch
import pytest

# ── Path setup ────────────────────────────────────────────────────────────────
_TELEGRAM_ROOT = Path(__file__).parents[1]
_APP_PATH = _TELEGRAM_ROOT / "app"
_REPO_ROOT = _TELEGRAM_ROOT.parent
_SHARED_PATH = _REPO_ROOT / "Hestia-Shared"

for _p in [str(_APP_PATH), str(_SHARED_PATH)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── Environment defaults (before any telebot / core import) ─────────────────
os.environ.setdefault("TELEGRAM_BOT_TOKEN",
                      "0000000000:AAFakeTokenForTestsOnly")
os.environ.setdefault("HUB_API_URL", "http://fake-hub:19001/api")
os.environ.setdefault("ORACLE_API_URL", "http://fake-oracle:19004/api/chat")
os.environ.setdefault("ORACLE_FORMAT_API_URL",
                      "http://fake-oracle:19004/api/format")
os.environ.setdefault("ALLOWED_USER_ID", "")
os.environ.setdefault("LOG_LEVEL", "WARNING")


# ── telebot patching — prevent real Telegram API calls ────────────────────────

class _FakeBot:
    """Stand-in for telebot.TeleBot — absorbs all method calls silently."""

    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        return MagicMock()


@pytest.fixture(autouse=True)
def _patch_telebot(monkeypatch):
    """Automatically stub telebot so no real Telegram API calls occur."""
    monkeypatch.setattr("telebot.TeleBot", _FakeBot)


# ── Fake message factory ───────────────────────────────────────────────────────


def _make_fake_message(
    text: str = "/help",
    chat_id: int = 12345,
    user_id: int = 99999,
    username: str = "test_user",
    message_id: int = 1,
) -> MagicMock:
    msg = MagicMock()
    msg.text = text
    msg.chat.id = chat_id
    msg.chat.type = "private"
    msg.from_user.id = user_id
    msg.from_user.username = username
    msg.from_user.first_name = "Test"
    msg.message_id = message_id
    msg.document = None
    msg.photo = None
    msg.audio = None
    msg.voice = None
    msg.video = None
    msg.video_note = None
    return msg


@pytest.fixture()
def fake_message():
    """Factory: call fake_message(text='/cmd') to get a telebot Message stub."""
    return _make_fake_message


def _make_fake_callback(data: str, message: MagicMock | None = None) -> MagicMock:
    cb = MagicMock()
    cb.data = data
    cb.from_user.id = 99999
    cb.from_user.username = "test_user"
    cb.message = message or _make_fake_message()
    cb.id = "cb_001"
    return cb


@pytest.fixture()
def fake_callback():
    """Factory for inline keyboard CallbackQuery stubs."""
    return _make_fake_callback


# ── Oracle stream mock ─────────────────────────────────────────────────────────


def _ndjson_stream(frames: list[dict]) -> bytes:
    return b"\n".join(json.dumps(f).encode() for f in frames)


@pytest.fixture()
def mock_oracle_stream(monkeypatch):
    """Patch requests.post so Oracle streaming returns controllable NDJSON frames.

    Usage::
        def test_chat(mock_oracle_stream):
            mock_oracle_stream([
                {"type": "token", "content": "Hello "},
                {"type": "token", "content": "world"},
                {"type": "done", "signals": []},
            ])
    """
    state: dict = {"frames": []}

    def _configure(frames: list[dict]) -> None:
        state["frames"] = frames

    class _FakeStreamResponse:
        status_code = 200
        ok = True

        def iter_lines(self, **kwargs):
            for frame in state["frames"]:
                yield json.dumps(frame).encode()

        def raise_for_status(self):
            pass

        def json(self):
            return {}

    monkeypatch.setattr("requests.post", lambda *a,
                        **kw: _FakeStreamResponse())
    return _configure


# ── Hub mock ──────────────────────────────────────────────────────────────────


SAMPLE_DYNAMIC_COMMANDS: list[dict] = [
    {
        "command": "meteo",
        "title": "🌤 Meteo",
        "description": "Mostra meteo corrente",
        "method": "GET",
        "path": "/api/meteo",
        "response_mode": "oracle_natural",
        "clients": ["telegram"],
        "service": "dummy",
    },
    {
        "command": "scout_listings",
        "title": "🏠 Annunci",
        "description": "Cerca annunci immobiliari",
        "method": "GET",
        "path": "/api/scout/listings",
        "response_mode": "direct",
        "clients": ["telegram"],
        "service": "scout",
    },
]


@pytest.fixture()
def mock_hub_commands(monkeypatch):
    """Patch Hub discovery so COMMAND_REGISTRY gets loaded with sample commands."""
    resp = MagicMock()
    resp.status_code = 200
    resp.ok = True
    resp.json.return_value = {"commands": SAMPLE_DYNAMIC_COMMANDS}
    monkeypatch.setattr("requests.get", lambda *a, **kw: resp)
    return SAMPLE_DYNAMIC_COMMANDS
