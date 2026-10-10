"""Import helper for hestia_common (Docker: /code/hestia_common; workspace: ../Hestia-Shared)."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path


def import_shared(module: str):
    try:
        return importlib.import_module(module)
    except ModuleNotFoundError:
        for parent in Path(__file__).resolve().parents:
            shared = parent / "Hestia-Shared"
            if shared.is_dir():
                if str(shared) not in sys.path:
                    sys.path.insert(0, str(shared))
                break
        return importlib.import_module(module)
