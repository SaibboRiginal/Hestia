"""Quality insights — where is Hestia doing badly?

Turns graded feedback into a compact "weak spots" report Athena can reason on
(and propose Forge improvements from).  Output is tiny on purpose: it is fed
into LLM prompts.
"""
from __future__ import annotations

from typing import Any

from . import metis_settings as ms


def _domain(record: dict) -> str:
    for tag in record.get("tags") or []:
        if str(tag).startswith("domain="):
            return str(tag).split("=", 1)[1] or "general"
    return "general"


def build_insights(records: list[dict[str, Any]], samples_per_domain: int = 2) -> dict[str, Any]:
    good_labels = {s.lower() for s in ms.labels(ms.GOOD_LABELS)}   # central setting (live)
    total = 0
    bad_by_domain: dict[str, dict[str, Any]] = {}
    for record in records or []:
        if not isinstance(record, dict):
            continue
        total += 1
        label = str(record.get("quality_label", "")).strip().lower()
        if not label or label in good_labels:
            continue
        domain = _domain(record)
        slot = bad_by_domain.setdefault(domain, {"domain": domain, "bad": 0, "labels": {}, "samples": []})
        slot["bad"] += 1
        slot["labels"][label] = slot["labels"].get(label, 0) + 1
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        if len(slot["samples"]) < samples_per_domain:
            slot["samples"].append({
                "user": str(payload.get("instruction") or payload.get("input") or "")[:160],
                "assistant": str(payload.get("output") or "")[:160],
                "note": str(record.get("comment") or payload.get("comment") or "")[:120],
            })
    weak = sorted(bad_by_domain.values(), key=lambda d: d["bad"], reverse=True)
    bad_total = sum(d["bad"] for d in weak)
    return {
        "total_feedback": total,
        "bad_feedback": bad_total,
        "bad_ratio": round(bad_total / total, 3) if total else 0.0,
        "weak_domains": weak[:5],
    }
