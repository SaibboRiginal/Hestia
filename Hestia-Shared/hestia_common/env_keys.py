"""Re-read a module's own ``.env`` for its provider keys without restarting the container.

The guided setup writes a key into the module's ``.env`` (Hephaestus ``setup/secrets.py``); ``env_file`` values
are read by Docker only when a container is created, so instead of re-creating the container (tens of seconds)
the module re-reads the file itself: only names starting with ``prefix`` (e.g. ``ORACLE_KEY_``) are taken, the
values go into ``os.environ`` and are never logged nor returned.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger("hestia_common.env_keys")


def read(path: Path, prefix: str) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        name, sep, value = line.partition("=")
        name, value = name.strip(), value.strip()
        if not sep or not name.startswith(prefix):
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[name] = value
    return out


def reload(path: Path, prefix: str) -> list[str]:
    """Apply the ``prefix*`` keys of ``path`` to ``os.environ``; returns the names that now have a value."""
    found = read(path, prefix)
    changed = 0
    for name, value in found.items():
        if value and os.environ.get(name) != value:
            os.environ[name] = value
            changed += 1
    names = sorted(n for n, v in found.items() if v)
    logger.info("event=env_keys_reloaded prefix=%s keys=%s changed=%s", prefix, len(names), changed)
    return names
