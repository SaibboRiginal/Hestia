"""Hermes test suite conftest."""
from __future__ import annotations

import os
import sys

_HERMES_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_HERMES_SRC = os.path.join(_HERMES_ROOT, "src")
_SHARED = os.path.join(_HERMES_ROOT, "..", "Hestia-Shared")
for _p in [_HERMES_ROOT, _HERMES_SRC, _SHARED]:
    _abs = os.path.abspath(_p)
    if _abs not in sys.path:
        sys.path.insert(0, _abs)

os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("HUB_API_URL", "http://localhost:19001/api")
os.environ.setdefault("ARCHIVE_API_URL", "http://localhost:19002/api")
os.environ.setdefault("TELEGRAM_DISPATCH_URL",
                      "http://localhost:19006/api/dispatch/send")
os.environ.setdefault("STARTUP_WAIT_TIMEOUT_SECONDS", "0")
