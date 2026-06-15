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
