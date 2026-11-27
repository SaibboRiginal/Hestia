"""Batched entity dispatcher for Hermes.

Collects ``entity.upserted`` events for configured domains and, after a
settling window with no new arrivals, narrates all queued entities via Oracle
and publishes ONE notification per subscription (delivered to every client by
the notification center, or only to the origin client).

Flow
----
1. ``enqueue_entity()`` is called from HermesService for every matched
   subscription on a batched domain.
2. The entity is added to the queue for that (subscription_id, channel_type,
   channel_target) key and the flush timer is (re)started.
3. Every new entity resets the timer, so a burst settles into a single dispatch.
4. When the timer fires, Oracle narrates all queued entities as a single
   message in the owner's language. If Oracle fails, a compact HTML fallback
   list is sent instead.
5. Every queued entity has an Archive row (channel ``batch``, state ``queued``) that blocks a duplicate
   notification. The row becomes ``delivered`` when the batch is published and ``failed`` when Hermes gives up
   (so the next upsert of that entity can notify again); rows still ``queued`` at startup are put back in their
   batch (``restore_queued``): a restart during the settling window loses nothing.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from html import escape

from typing import Callable

from .oracle_client import narrate
from .hermes_settings import BATCH_MAX_ATTEMPTS, BATCH_WINDOW, settings
from hestia_common.i18n import t as tr  # fixed texts in the owner's language (path set up by hermes_settings)

logger = logging.getLogger("hestia_hermes.entity_batch")


# Domains / event types that are routed through the batch dispatcher
BATCHED_DOMAINS: frozenset[str] = frozenset({"real_estate"})
BATCHED_EVENT_TYPES: frozenset[str] = frozenset({"entity.upserted"})


@dataclass
class _BatchEntry:
    subscription_id: int
    channel_type: str
    channel_target: str
    domain: str
    filters: dict
    entities: list[dict] = field(default_factory=list)
    row_ids: list[str] = field(default_factory=list)   # Archive rows (channel batch) of the queued entities
    timer: threading.Timer | None = None
    attempts: int = 0



# Key: (subscription_id, channel_type, channel_target)
_queues: dict[tuple, _BatchEntry] = {}
_queues_lock = threading.Lock()

# (subscription_id, audience_key, domain, text) -> published; set by HermesService.
_publisher: Callable[..., bool] | None = None
# (row_id, lifecycle_state, detail) -> None: closes the Archive rows of a batch; set by HermesService.
_state_writer: Callable[[str, str, str], None] | None = None


def set_publisher(publisher: Callable[..., bool], state_writer: Callable[[str, str, str], None] | None = None) -> None:
    global _publisher, _state_writer
    _publisher = publisher
    _state_writer = state_writer


def _close_rows(entry: "_BatchEntry", state: str, detail: str) -> None:
    """Mark the batch rows ``delivered`` (sent) or ``failed`` (given up: no longer blocks a new notification)."""
    if _state_writer is None:
        return
    for row_id in entry.row_ids:
        try:
            _state_writer(row_id, state, detail)
        except Exception as exc:  # noqa: BLE001 — a bookkeeping failure never stops the batch
            logger.warning("[🔄] event=batch_row_state_failed row=%s state=%s error=%s", row_id, state, exc)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _queue_key(subscription_id: int, channel_type: str, channel_target: str) -> tuple:
    return (subscription_id, channel_type, channel_target)


def _schedule_flush(key: tuple, entry: _BatchEntry) -> None:
    """(Re)start the flush timer. Must be called while holding ``_queues_lock``."""
    if entry.timer is not None:
        entry.timer.cancel()
    timer = threading.Timer(float(settings.get(BATCH_WINDOW)), _flush, args=[key])
    timer.daemon = True
    timer.start()
    entry.timer = timer


def _batch_link(entities: list[dict]) -> dict | None:
    """One entity → its own ``_link``; several from one module → that module's list page (``_link.list``)."""
    links = [e.get("_link") for e in entities if isinstance(e, dict) and isinstance(e.get("_link"), dict)]
    if not links:
        return None
    if len(entities) == 1:
        return links[0]
    first = links[0]
    if first.get("list") and all(l.get("module") == first.get("module") for l in links):
        return {"module": first.get("module"), "page": first.get("list")}
    return None


def _flush(key: tuple) -> None:
    """Flush the batch for the given key — called from the timer thread."""
    with _queues_lock:
        entry = _queues.pop(key, None)

    if not entry or not entry.entities:
        return

    n = len(entry.entities)
    logger.info(
        "event=batch_flushing_entit_subscription_target [BATCH] Flushing %d entit%s | subscription=%s target=%s",
        n,
        "y" if n == 1 else "ies",
        entry.subscription_id,
        entry.channel_target,
    )

    text = _narrate_entities(entry)
    detail = "no publisher"
    ok = False
    if _publisher is not None:
        try:
            link = _batch_link(entry.entities)
            extra = {"link": link} if link else {}
            if any(isinstance(e, dict) and e.get("_voice") for e in entry.entities):
                extra["voice"] = True              # the module wants its notifications also as audio
            ok = bool(_publisher(entry.subscription_id, entry.channel_type, entry.domain, text, **extra))
            detail = "published" if ok else "no client reached"
        except Exception as exc:
            detail = str(exc)
    if ok:
        _close_rows(entry, "delivered", "published in entity batch")
        logger.info(
            "event=batch_dispatched_entit_subscription_target [BATCH] Dispatched %d entit%s | subscription=%s target=%s",
            n,
            "y" if n == 1 else "ies",
            entry.subscription_id,
            entry.channel_target,
        )
    else:
        logger.warning(
            "[🔄] event=batch_dispatch_failed_subscription_target [BATCH] Dispatch failed | subscription=%s target=%s attempt=%d detail=%s",
            entry.subscription_id,
            entry.channel_target,
            entry.attempts + 1,
            detail,
        )
        _requeue_failed(key, entry)


def _requeue_failed(key: tuple, entry: _BatchEntry) -> None:
    """Resilience: a failed batch is re-queued (merged with anything new) and
    retried with backoff instead of being dropped."""
    entry.attempts += 1
    if entry.attempts >= int(settings.get(BATCH_MAX_ATTEMPTS)):
        logger.error("event=batch_dispatch_gave_up subscription=%s entities=%d attempts=%d",
                     entry.subscription_id, len(entry.entities), entry.attempts)
        _close_rows(entry, "failed", "entity batch gave up")
        return
    with _queues_lock:
        pending = _queues.get(key)
        if pending is not None:
            if pending.timer is not None:
                pending.timer.cancel()
            entry.entities.extend(pending.entities)
            entry.row_ids.extend(pending.row_ids)
        _queues[key] = entry
        delay = min(1800.0, float(settings.get(BATCH_WINDOW)) * (2 ** entry.attempts))
        timer = threading.Timer(delay, _flush, args=[key])
        timer.daemon = True
        timer.start()
        entry.timer = timer


def _narrate_entities(entry: _BatchEntry) -> str:
    """Build an Oracle-narrated or fallback HTML message for a batch of entities."""
    entities = entry.entities
    n = len(entities)

    # Build structured text summary for Oracle
    lines: list[str] = []
    for e in entities:
        url = str(e.get("url") or "").strip()
        title = str(e.get("title") or "").strip()
        address = str(e.get("address") or "").strip()
        price = e.get("price")
        specs = e.get("specs") or {}
        summary = str(e.get("summary") or "").strip()

        parts: list[str] = []
        if title:
            parts.append(f"Title: {title}")
        if address:
            parts.append(f"Address: {address}")
        if price:
            try:
                parts.append(f"Price: €{int(float(price)):,}")
            except (TypeError, ValueError):
                parts.append(f"Price: {price}")
        if specs.get("surface_m2"):
            parts.append(f"Surface: {specs['surface_m2']} m²")
        if specs.get("rooms"):
            parts.append(f"Rooms: {specs['rooms']}")
        if specs.get("balcony_or_terrace"):
            parts.append("Balcony/terrace: yes")
        if specs.get("garage_or_parking"):
            parts.append("Garage/parking: yes")
        if summary:
            # Use a meaningful slice of the summary
            parts.append(f"Description: {summary[:400]}")
        if url:
            parts.append(f"Link: {url}")
        lines.append("\n".join(parts))

    raw = "\n\n---\n\n".join(lines)

    # Build human-readable filter context from subscription filters
    filters = entry.filters or {}
    filter_desc_parts: list[str] = []
    if filters.get("city"):
        filter_desc_parts.append(f"area {filters['city']}")
    if filters.get("max_price"):
        try:
            filter_desc_parts.append(
                f"max budget €{int(float(filters['max_price'])):,}")
        except (TypeError, ValueError):
            pass
    filters_desc = f" ({', '.join(filter_desc_parts)})" if filter_desc_parts else ""

    prompt = (
        f"You found {n} new real estate listing{'' if n == 1 else 's'}{filters_desc}. Tell the owner.\n"
        f"- Concise but informative: price, location and the most relevant features of each listing.\n"
        f"- Natural flowing text, no bulleted or numbered lists.\n"
        f"- Several listings: group them briefly by area or price range if it makes sense.\n"
        f"- Format: HTML only, no Markdown. Links: <a href=\"EXACT_URL\">address or title</a>.\n\n"
        f"LISTINGS:\n{raw}"
    )

    narrated = narrate(prompt)
    if narrated and narrated.strip():
        header = tr("🏠 <b>New real estate listing</b>") if n == 1 else tr("🏠 <b>New real estate listings</b>")
        return f"{header}\n\n{narrated.strip()}"

    # Fallback: compact HTML list (still better than one message per property)
    fallback_parts: list[str] = []
    for e in entities:
        url = str(e.get("url") or "").strip()
        label = str(e.get("address") or e.get("title") or url).strip()
        price = e.get("price")
        specs = e.get("specs") or {}
        line = f'<a href="{escape(url, quote=True)}">{escape(label)}</a>' if url else escape(label)
        details: list[str] = []
        if price:
            try:
                details.append(f"€{int(float(price)):,}")
            except (TypeError, ValueError):
                pass
        if specs.get("surface_m2"):
            details.append(f"{specs['surface_m2']} m²")
        if details:
            line += f" — {', '.join(details)}"
        fallback_parts.append(line)

    header = tr("🏠 <b>New real estate listing</b>") if n == 1 else tr("🏠 <b>New real estate listings</b>")
    return header + "\n\n" + "\n".join(fallback_parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def enqueue_entity(
    subscription_id: int,
    channel_type: str,
    channel_target: str,
    domain: str,
    entity_id: str,
    payload: dict,
    filters: dict,
    row_id: str = "",
) -> None:
    """Add an entity to the batch for the given subscription + channel.

    The flush timer is reset on every call so a burst of entities settles
    into a single dispatch after ``hermes.batch.window`` seconds of silence.
    """
    key = _queue_key(subscription_id, channel_type, channel_target)
    with _queues_lock:
        if key not in _queues:
            _queues[key] = _BatchEntry(
                subscription_id=subscription_id,
                channel_type=channel_type,
                channel_target=channel_target,
                domain=domain,
                filters=filters,
            )
        entry = _queues[key]
        entry.entities.append(payload)
        if row_id:
            entry.row_ids.append(row_id)
        _schedule_flush(key, entry)
        queued_count = len(entry.entities)

    logger.info(
        "event=batch_enqueued_entity_subscription_target [BATCH] Enqueued entity | subscription=%s target=%s queued=%d entity_id=%s",
        subscription_id,
        channel_target,
        queued_count,
        entity_id,
    )


def restore_queued(rows: list[dict]) -> int:
    """Startup: Archive rows still ``queued`` (Hermes stopped during the settling window) go back in their batch."""
    restored = 0
    for row in rows or []:
        stored = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        payload = stored.get("event_payload") if isinstance(stored.get("event_payload"), dict) else None
        if not payload or not row.get("outbound_event_id"):
            continue
        enqueue_entity(subscription_id=row.get("subscription_id"), channel_type=str(stored.get("audience_key") or "all"),
                       channel_target="", domain=str(row.get("domain") or ""), entity_id=str(row.get("entity_id") or ""),
                       payload=payload, filters=stored.get("filters") if isinstance(stored.get("filters"), dict) else {},
                       row_id=str(row["outbound_event_id"]))
        restored += 1
    if restored:
        logger.info("[🔄] event=batch_restored entities=%d", restored)
    return restored
