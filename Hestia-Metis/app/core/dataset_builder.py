"""Dataset Builder — pulls graded feedback, deduplicates, balances, stores.

In-memory dataset store (a dict keyed by dataset name). For production,
this would be persisted to Archive or a local file. For now, it lives in
the Metis process — datasets are rebuilt on restart, which is acceptable
for an on-demand tool.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from .hub_client import HubClient

logger = logging.getLogger("hestia_metis.dataset_builder")

_DEFAULT_QUALITY_LABELS = [
    lb.strip()
    for lb in os.getenv(
        "METIS_DEFAULT_QUALITY_LABELS", "excellent,good"
    ).split(",")
    if lb.strip()
]
_MAX_EXAMPLES = int(os.getenv("METIS_MAX_DATASET_EXAMPLES", "5000"))
_DEDUP_ENABLED = os.getenv(
    "METIS_DEDUPLICATE_ENABLED", "true"
).strip().lower() not in {"0", "false", "no"}

# In-memory dataset store: name → {metadata, examples}
_datasets: dict[str, dict[str, Any]] = {}


def _normalize_text(text: str) -> str:
    """Normalize for dedup hashing — lowercase, strip whitespace."""
    return " ".join(str(text or "").lower().split())


def _message_hash(user_msg: str, assistant_msg: str) -> str:
    """Stable hash for a user+assistant pair."""
    digest = hashlib.sha256(
        f"{_normalize_text(user_msg)}|{_normalize_text(assistant_msg)}".encode()
    ).hexdigest()[:16]
    return digest


def build_dataset(
    hub: HubClient,
    name: str,
    quality_labels: list[str] | None = None,
    min_score: int | None = None,
    since: str | None = None,
    max_examples: int = _MAX_EXAMPLES,
    deduplicate: bool = _DEDUP_ENABLED,
) -> dict[str, Any]:
    """Build a cleaned dataset from graded feedback records.

    Returns metadata dict with counts, domains, quality distribution.
    Stores the dataset in the in-memory _datasets dict.
    """
    labels = quality_labels or _DEFAULT_QUALITY_LABELS
    logger.info(
        "event=dataset_build_start name=%s labels=%s",
        name,
        labels,
    )
    all_records: list[dict[str, Any]] = []
    for label in labels:
        records = hub.fetch_feedback(
            quality_label=label,
            min_score=min_score,
            limit=max_examples,
            since=since,
        )
        if isinstance(records, list):
            all_records.extend(records)
        else:
            logger.warning(
                "event=unexpected_feedback_response label=%s type=%s",
                label, type(records).__name__,
            )

    if not all_records:
        return {
            "status": "empty",
            "name": name,
            "total_fetched": 0,
            "total_kept": 0,
        }

    examples: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    domains: dict[str, int] = {}
    quality_counts: dict[str, int] = {}
    skipped_duplicate = 0
    skipped_no_payload = 0

    for record in all_records:
        payload = record.get("payload") if isinstance(record, dict) else {}
        if not isinstance(payload, dict):
            skipped_no_payload += 1
            continue

        user_msg = str(payload.get("instruction") or payload.get("input") or "").strip()
        assistant_msg = str(payload.get("output") or "").strip()
        if not user_msg or not assistant_msg:
            skipped_no_payload += 1
            continue

        if deduplicate:
            h = _message_hash(user_msg, assistant_msg)
            if h in seen_hashes:
                skipped_duplicate += 1
                continue
            seen_hashes.add(h)

        qlabel = str(record.get("quality_label", "mixed")).strip().lower()
        quality_counts[qlabel] = quality_counts.get(qlabel, 0) + 1

        # Infer domain from tags or payload
        domain = "general"
        tags = record.get("tags") or []
        if isinstance(tags, list):
            for tag in tags:
                if str(tag).startswith("domain="):
                    domain = str(tag).split("=", 1)[1]
                    break

        domains[domain] = domains.get(domain, 0) + 1

        examples.append({
            "user": user_msg,
            "assistant": assistant_msg,
            "quality_label": qlabel,
            "domain": domain,
            "session_id": record.get("session_id", ""),
        })

        if len(examples) >= max_examples:
            break

    _datasets[name] = {
        "metadata": {
            "name": name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "total_fetched": len(all_records),
            "total_kept": len(examples),
            "skipped_duplicate": skipped_duplicate,
            "skipped_no_payload": skipped_no_payload,
            "domains": domains,
            "quality_distribution": quality_counts,
            "deduplicate": deduplicate,
            "quality_labels_used": labels,
        },
        "examples": examples,
    }

    logger.info(
        "event=dataset_built name=%s fetched=%s kept=%s dup=%s no_payload=%s domains=%s",
        name, len(all_records), len(examples),
        skipped_duplicate, skipped_no_payload,
        len(domains),
    )
    return _datasets[name]["metadata"]


def get_dataset_status(name: str | None = None) -> dict[str, Any]:
    """Return metadata for one or all datasets."""
    if name:
        ds = _datasets.get(name)
        if not ds:
            return {"status": "not_found", "name": name}
        return {"status": "ok", "dataset": ds["metadata"]}

    return {
        "status": "ok",
        "datasets": [
            {"name": k, **v["metadata"]}
            for k, v in _datasets.items()
        ],
    }


def get_dataset_examples(name: str) -> list[dict[str, Any]]:
    """Return the raw examples for a dataset."""
    ds = _datasets.get(name)
    if not ds:
        return []
    return ds.get("examples", [])
