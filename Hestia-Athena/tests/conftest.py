"""Athena test suite conftest — sys.path + env setup."""
from __future__ import annotations

import os
import sys

# ── sys.path ─────────────────────────────────────────────────────────────────
_ATHENA_APP = os.path.join(os.path.dirname(__file__), "..", "app")
_SHARED = os.path.join(os.path.dirname(__file__), "..", "..", "Hestia-Shared")
for _p in [_ATHENA_APP, _SHARED]:
    _abs = os.path.abspath(_p)
    if _abs not in sys.path:
        sys.path.insert(0, _abs)

# ── env defaults ──────────────────────────────────────────────────────────────
os.environ.setdefault("HUB_API_URL", "http://localhost:19001/api")
os.environ.setdefault("HERMES_API_URL", "http://localhost:19005")
# disable background loop in tests
os.environ.setdefault("ATHENA_LOOP_ENABLED", "0")
os.environ.setdefault("LOG_LEVEL", "WARNING")
