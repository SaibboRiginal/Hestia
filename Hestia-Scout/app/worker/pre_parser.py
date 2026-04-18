"""Pre-parse email records to extract listing URLs without any LLM call.

This is the first stage of the optimized Scout pipeline.  It runs before
any AI call and produces the data structures needed to decide which records
require full LLM extraction vs. a lighter status-update path.
"""

from __future__ import annotations

import re

from worker.extractor import normalize_listing_url, sanitize_email_for_ai

# Matches markers injected by sanitize_email_for_ai for known property links.
_PROPERTY_LINK_RE = re.compile(
    r"\[PROPERTY_LINK:\s*(https?://[^\]]+)\]",
    re.IGNORECASE,
)


# ─────────────────────────────────────────────────────────────────────
#  Public types
# ─────────────────────────────────────────────────────────────────────

class EmailPreParseResult:
    """Grouping structures derived from a set of raw email records.

    Attributes
    ----------
    url_to_record_ids:
        Maps each discovered normalized listing URL to the list of
        record IDs whose email body mentions that URL.
    record_id_to_urls:
        Maps each record ID to the (possibly empty) list of normalized
        listing URLs found in that email.
    record_id_to_clean_text:
        Maps each record ID to its sanitized plain text (HTML stripped,
        [PROPERTY_LINK:] markers inserted).  Used for downstream
        keyword-based status detection.
    unclassified_record_ids:
        Record IDs from which no listing URL could be extracted.  These
        must still go through the LLM extraction path so that no email
        is silently dropped.
    """

    __slots__ = (
        "url_to_record_ids",
        "record_id_to_urls",
        "record_id_to_clean_text",
        "unclassified_record_ids",
    )

    def __init__(self) -> None:
        self.url_to_record_ids: dict[str, list[int]] = {}
        self.record_id_to_urls: dict[int, list[str]] = {}
        self.record_id_to_clean_text: dict[int, str] = {}
        self.unclassified_record_ids: list[int] = []


# ─────────────────────────────────────────────────────────────────────
#  Core logic
# ─────────────────────────────────────────────────────────────────────

def pre_parse_records(records: list[dict]) -> EmailPreParseResult:
    """Extract listing URLs from all email records without calling an LLM.

    Only URLs that appear as ``[PROPERTY_LINK: ...]`` markers survive the
    sanitizer, so detection is exact.  Records whose emails yield no markers
    (e.g. some Immobiliare.it formats) are placed in
    ``unclassified_record_ids`` and will be sent to the LLM anyway, preserving
    backward-compatible behaviour.
    """
    result = EmailPreParseResult()

    for record in records:
        record_id: int = record["id"]
        raw_html: str = (
            record.get("payload", {}).get("body", "")
            + " "
            + record.get("payload", {}).get("title", "")
        )

        clean_text = sanitize_email_for_ai(raw_html)
        result.record_id_to_clean_text[record_id] = clean_text

        found_urls = _extract_normalized_urls(clean_text)
        result.record_id_to_urls[record_id] = found_urls

        if not found_urls:
            result.unclassified_record_ids.append(record_id)
        else:
            for url in found_urls:
                result.url_to_record_ids.setdefault(url, []).append(record_id)

    return result


def select_representative_records(
    new_urls: set[str],
    url_to_record_ids: dict[str, list[int]],
    record_id_to_clean_text: dict[int, str],
) -> set[int]:
    """Choose the minimal set of record IDs that covers all *new* listing URLs.

    For each new URL the record with the most textual content is chosen as
    representative.  Because a single email can mention multiple new URLs, the
    resulting set is automatically deduplicated — if one record is already
    selected as representative for URL A, it also covers URL B in that email
    for free.
    """
    representative_ids: set[int] = set()

    for url in new_urls:
        candidate_ids = url_to_record_ids.get(url, [])
        if not candidate_ids:
            continue
        # Prefer the richest email so the LLM has the most context.
        best_id = max(
            candidate_ids,
            key=lambda rid: len(record_id_to_clean_text.get(rid, "")),
        )
        representative_ids.add(best_id)

    return representative_ids


# ─────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────

def _extract_normalized_urls(clean_text: str) -> list[str]:
    raw_urls = _PROPERTY_LINK_RE.findall(clean_text)
    seen: set[str] = set()
    result: list[str] = []
    for raw in raw_urls:
        normalized = normalize_listing_url(raw.strip())
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result
