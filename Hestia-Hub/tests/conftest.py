"""Hub test suite conftest."""
from __future__ import annotations

import os
import sys

_HUB_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_HUB_SRC = os.path.join(_HUB_ROOT, "src")
_SHARED = os.path.join(_HUB_ROOT, "..", "Hestia-Shared")
for _p in [_HUB_ROOT, _HUB_SRC, _SHARED]:
    _abs = os.path.abspath(_p)
    if _abs not in sys.path:
        sys.path.insert(0, _abs)

os.environ.setdefault("LOG_LEVEL", "WARNING")
