"""Schema bootstrap shared by startup and by a backup rollback (an older backup gains today's tables/columns).

Additive only — never remove columns.
"""
from __future__ import annotations

import logging

from sqlalchemy import text

from . import models

logger = logging.getLogger("hestia_archive")

ADDITIVE_COLUMNS = [
    ("calendar_items", "meta", "JSONB"),
    ("user_preferences", "memory_class", "VARCHAR"),
    ("user_preferences", "embedding", "vector(768)"),
    ("user_preferences", "domains", "JSONB"),
    ("user_preferences", "extra_data", "JSONB"),
    ("mcp_accesses", "client_id", "VARCHAR"),
    ("mcp_accesses", "refresh_hash", "VARCHAR"),
    ("mcp_accesses", "prev_refresh_hash", "VARCHAR"),
    ("mcp_accesses", "token_expires_at", "TIMESTAMPTZ"),
]


def migrate(engine) -> None:
    """pgvector + every table, then the additive columns. ``create_all`` never adds columns to existing tables;
    each ALTER runs in its own transaction, so a failure is rolled back instead of aborting every later
    statement ("current transaction is aborted")."""
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    models.Base.metadata.create_all(bind=engine)
    for table, col_name, col_type in ADDITIVE_COLUMNS:
        try:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col_name} {col_type}"))
        except Exception as exc:
            logger.warning("[🔄] event=archive_migration_failed table=%s column=%s error=%s",
                           table, col_name, str(exc)[:200])
