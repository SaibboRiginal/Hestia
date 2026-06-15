"""Archive test suite conftest."""
from __future__ import annotations

import os
import sys

_ARCHIVE_APP = os.path.join(os.path.dirname(__file__), "..", "app")
_SHARED = os.path.join(os.path.dirname(__file__), "..", "..", "Hestia-Shared")
for _p in [_ARCHIVE_APP, _SHARED]:
    _abs = os.path.abspath(_p)
    if _abs not in sys.path:
        sys.path.insert(0, _abs)

os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_archive.db")
os.environ.setdefault("HUB_API_URL", "http://localhost:19001/api")
