"""Hecate test suite conftest."""
from __future__ import annotations

import os
import sys

_HECATE_APP = os.path.join(os.path.dirname(__file__), "..", "app")
_SHARED = os.path.join(os.path.dirname(__file__), "..", "..", "Hestia-Shared")
for _p in [_HECATE_APP, _SHARED]:
    _abs = os.path.abspath(_p)
    if _abs not in sys.path:
        sys.path.insert(0, _abs)

os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("HUB_API_URL", "http://localhost:19001/api")
os.environ.setdefault("ARCHIVE_API_URL", "http://localhost:19002/api")
# Disable real OAuth providers in tests
os.environ.setdefault("HECATE_ENABLE_PROVIDER_GOOGLE", "0")
os.environ.setdefault("HECATE_ENABLE_PROVIDER_MICROSOFT", "0")
os.environ.setdefault("STARTUP_WAIT_TIMEOUT_SECONDS", "0")
# Keep OAuth token/pending files out of /code/data during tests.
import tempfile as _tempfile
_TOKEN_DIR = _tempfile.mkdtemp(prefix="hecate-test-")
os.environ["GOOGLE_TOKEN_FILE"] = os.path.join(_TOKEN_DIR, "google_token.json")
# Blank out credential env vars BEFORE load_dotenv() runs so .env values
# don't leak into the test environment (load_dotenv respects existing vars).
for _key in (
    "GOOGLE_TOKEN_JSON", "GOOGLE_CREDENTIALS_JSON",
    "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN",
    "GOOGLE_SERVICE_ACCOUNT_JSON",
    "OUTLOOK_CLIENT_ID", "OUTLOOK_CLIENT_SECRET",
    "OUTLOOK_TENANT_ID", "OUTLOOK_REFRESH_TOKEN",
):
    if _key not in os.environ:
        os.environ[_key] = ""


import glob as _glob
import pytest as _pytest


@_pytest.fixture(autouse=True)
def _clean_token_dir():
    """Each test starts without a persisted token or pending OAuth flow."""
    for f in _glob.glob(os.path.join(_TOKEN_DIR, "*")):
        os.remove(f)
    yield
    for f in _glob.glob(os.path.join(_TOKEN_DIR, "*")):
        os.remove(f)
