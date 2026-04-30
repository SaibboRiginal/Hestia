"""Context loader — reads Hestia project documentation at startup.

At startup, Argus mounts the Hestia repository root as a read-only volume at
``HESTIA_DOCS_PATH`` (default ``/hestia_root``).  This module scans that path
for every ``hestia-*.md`` file (one per service) and concatenates them into a
single context string that is passed to Oracle when performing LLM analysis.

This gives Oracle (and therefore the operator) the knowledge of what each
Hestia service is supposed to do, so anomalies in logs or health can be
interpreted correctly in context.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(f"hestia_argus.{__name__}")

DOCS_PATH = Path(os.getenv("HESTIA_DOCS_PATH", "/hestia_root"))

_cached_context: str | None = None


def _load_docs() -> str:
    """Scan DOCS_PATH for hestia-*.md files and return concatenated content."""
    if not DOCS_PATH.exists():
        logger.warning(
            "event=hestia_docs_path_does_analysis_will_lack HESTIA_DOCS_PATH '%s' does not exist; analysis will lack project context.",
            DOCS_PATH,
        )
        return ""

    parts: list[str] = []
    md_files = sorted(DOCS_PATH.rglob("hestia-*.md"))

    if not md_files:
        logger.warning(
            "event=hestia_md_files_found_under No hestia-*.md files found under '%s'; analysis will lack project context.",
            DOCS_PATH,
        )
        return ""

    for path in md_files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            parts.append(f"--- {path.name} ---\n{text.strip()}")
        except Exception as exc:
            logger.warning("event=could_read Could not read %s: %s", path, exc)

    logger.info("event=loaded_project_context_file_from Loaded %d project context file(s) from %s",
                len(parts), DOCS_PATH)
    return "\n\n".join(parts)


def get_context() -> str:
    """Return the cached project context string (loaded once at startup)."""
    global _cached_context
    if _cached_context is None:
        _cached_context = _load_docs()
    return _cached_context


def reload() -> str:
    """Force a reload of context files (e.g. after a docs update)."""
    global _cached_context
    _cached_context = _load_docs()
    return _cached_context
