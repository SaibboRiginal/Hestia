from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path
from typing import Any


def import_shared_symbol(module_name: str, symbol_name: str) -> Any:
    try:
        module = import_module(module_name)
    except ModuleNotFoundError:
        workspace_root = Path(__file__).resolve().parents[3]
        shared_pkg = workspace_root / "Hestia-Shared"
        if str(shared_pkg) not in sys.path:
            sys.path.insert(0, str(shared_pkg))
        module = import_module(module_name)
    return getattr(module, symbol_name)
