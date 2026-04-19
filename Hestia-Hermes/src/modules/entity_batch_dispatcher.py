"""Batched entity dispatcher for Hermes.

Collects ``entity.upserted`` events for configured domains and, after a
settling window with no new arrivals, narrates all queued entities via Oracle
and sends a single personalized Telegram message per subscription channel.

Flow
----
1. ``enqueue_entity()`` is called from HermesService for every matched
   subscription on a batched domain.
2. The entity is added to the queue for that (subscription_id, channel_type,
   channel_target) key and the flush timer is (re)started.
3. Every new entity resets the timer, so a burst settles into a single dispatch.
4. When the timer fires, Oracle narrates all queued entities as a single
   conversational Italian message. If Oracle fails, a compact HTML fallback
   list is sent instead.
"""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field

from .dispatch import DispatchService
from .oracle_client import narrate

logger = logging.getLogger("hestia_hermes.entity_batch")

BATCH_WINDOW_SECONDS = float(os.getenv("ENTITY_BATCH_WINDOW_SECONDS", "30"))

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
    timer: threading.Timer | None = None


# Key: (subscription_id, channel_type, channel_target)
_queues: dict[tuple, _BatchEntry] = {}
_queues_lock = threading.Lock()

_dispatch_service = DispatchService()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _queue_key(subscription_id: int, channel_type: str, channel_target: str) -> tuple:
    return (subscription_id, channel_type, channel_target)


def _schedule_flush(key: tuple, entry: _BatchEntry) -> None:
    """(Re)start the flush timer. Must be called while holding ``_queues_lock``."""
    if entry.timer is not None:
        entry.timer.cancel()
    timer = threading.Timer(BATCH_WINDOW_SECONDS, _flush, args=[key])
    timer.daemon = True
    timer.start()
    entry.timer = timer


def _flush(key: tuple) -> None:
    """Flush the batch for the given key — called from the timer thread."""
    with _queues_lock:
        entry = _queues.pop(key, None)

    if not entry or not entry.entities:
        return

    n = len(entry.entities)
    logger.info(
        "[BATCH] Flushing %d entit%s | subscription=%s target=%s",
        n,
        "y" if n == 1 else "ies",
        entry.subscription_id,
        entry.channel_target,
    )

    text = _narrate_entities(entry)
    ok, detail = _dispatch_service.send(
        channel=entry.channel_type,
        target=entry.channel_target,
        message=text,
    )
    if ok:
        logger.info(
            "[BATCH] Dispatched %d entit%s | subscription=%s target=%s",
            n,
            "y" if n == 1 else "ies",
            entry.subscription_id,
            entry.channel_target,
        )
    else:
        logger.warning(
            "[BATCH] Dispatch failed | subscription=%s target=%s detail=%s",
            entry.subscription_id,
            entry.channel_target,
            detail,
        )


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
            parts.append(f"Titolo: {title}")
        if address:
            parts.append(f"Indirizzo: {address}")
        if price:
            try:
                parts.append(f"Prezzo: €{int(float(price)):,}")
            except (TypeError, ValueError):
                parts.append(f"Prezzo: {price}")
        if specs.get("surface_m2"):
            parts.append(f"Superficie: {specs['surface_m2']} mq")
        if specs.get("rooms"):
            parts.append(f"Locali: {specs['rooms']}")
        if specs.get("balcony_or_terrace"):
            parts.append("Balcone/terrazzo: sì")
        if specs.get("garage_or_parking"):
            parts.append("Garage/parcheggio: sì")
        if summary:
            # Use a meaningful slice of the summary
            parts.append(f"Descrizione: {summary[:400]}")
        if url:
            parts.append(f"Link: {url}")
        lines.append("\n".join(parts))

    raw = "\n\n---\n\n".join(lines)

    # Build human-readable filter context from subscription filters
    filters = entry.filters or {}
    filter_desc_parts: list[str] = []
    if filters.get("city"):
        filter_desc_parts.append(f"zona {filters['city']}")
    if filters.get("max_price"):
        try:
            filter_desc_parts.append(
                f"budget massimo €{int(float(filters['max_price'])):,}")
        except (TypeError, ValueError):
            pass
    filters_desc = f" ({', '.join(filter_desc_parts)})" if filter_desc_parts else ""

    noun = "annuncio immobiliare" if n == 1 else "annunci immobiliari"
    prompt = (
        f"Hestia ha trovato {n} nuov{'o' if n == 1 else 'i'} {noun}{filters_desc}.\n\n"
        f"Ecco i dettagli:\n\n{raw}\n\n"
        f"Scrivi una notifica amichevole e personalizzata in italiano per l'utente. "
        f"Sii conciso ma informativo: menziona prezzo, posizione e caratteristiche più "
        f"rilevanti di ogni annuncio. "
        f"Includi i link come HTML: <a href=\"URL_ESATTO\">indirizzo o titolo</a>. "
        f"Non usare liste puntate o numerate — scrivi in modo naturale e scorrevole, "
        f"come se stessi segnalando opportunità a un amico. "
        f"Usa esclusivamente HTML per la formattazione (non markdown). "
        f"Se ci sono più annunci, raggruppali brevemente per zona o fascia di prezzo "
        f"se ha senso farlo."
    )

    narrated = narrate(prompt)
    if narrated and narrated.strip():
        header = f"🏠 <b>Nuov{'o' if n == 1 else 'i'} {noun}</b>"
        return f"{header}\n\n{narrated.strip()}"

    # Fallback: compact HTML list (still better than one message per property)
    fallback_parts: list[str] = []
    for e in entities:
        url = str(e.get("url") or "").strip()
        label = str(e.get("address") or e.get("title") or url).strip()
        price = e.get("price")
        specs = e.get("specs") or {}
        line = f'<a href="{url}">{label}</a>'
        details: list[str] = []
        if price:
            try:
                details.append(f"€{int(float(price)):,}")
            except (TypeError, ValueError):
                pass
        if specs.get("surface_m2"):
            details.append(f"{specs['surface_m2']} mq")
        if details:
            line += f" — {', '.join(details)}"
        fallback_parts.append(line)

    header = f"🏠 <b>Nuov{'o' if n == 1 else 'i'} {noun}</b>"
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
) -> None:
    """Add an entity to the batch for the given subscription + channel.

    The flush timer is reset on every call so a burst of entities settles
    into a single dispatch after ``ENTITY_BATCH_WINDOW_SECONDS`` of silence.
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
        _schedule_flush(key, entry)
        queued_count = len(entry.entities)

    logger.info(
        "[BATCH] Enqueued entity | subscription=%s target=%s queued=%d entity_id=%s",
        subscription_id,
        channel_target,
        queued_count,
        entity_id,
    )
