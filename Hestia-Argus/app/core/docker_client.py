"""Docker client — incremental log polling with per-container cursors.

Instead of streaming (which blocks a thread indefinitely and re-reads from the
start on reconnect), we poll each container on every monitor cycle using the
Docker SDK's ``since`` parameter.  Only log lines produced *after* the last
poll are fetched, so Argus never re-reads logs it has already seen — even for
containers that have been running for months.

Startup behaviour
-----------------
On the first poll for a container, the cursor is set to
``startup_time - ARGUS_LOG_BACKFILL_MINUTES`` (default 5 minutes), giving a
small look-back window to catch issues that occurred just before Argus started,
without reading the full log history.

Thread safety
-------------
All state (buffers, cursors) is protected by ``_lock``.  The public API is
safe to call from multiple threads.
"""
from __future__ import annotations

import logging
import os
import re
import struct
import threading
from collections import deque
from datetime import datetime, timedelta, timezone

import docker  # type: ignore

from schemas.reports import LogEvent

logger = logging.getLogger(f"hestia_argus.{__name__}")

BUFFER_SIZE = int(os.getenv("ARGUS_LOG_BUFFER_SIZE", "500"))
BACKFILL_MINUTES = int(os.getenv("ARGUS_LOG_BACKFILL_MINUTES", "5"))
LOG_LEVEL_PATTERN = re.compile(r"\b(WARNING|ERROR|CRITICAL)\b", re.IGNORECASE)
HEALTH_ACCESS_PATTERN = re.compile(
    r'"(?:GET|HEAD|OPTIONS)\s+/(?:health|healthz|ready|live)\b',
    re.IGNORECASE,
)
IGNORE_HEALTH_ACCESS = os.getenv("ARGUS_IGNORE_HEALTH_ACCESS", "true").lower() in {
    "1", "true", "yes", "on"
}

# Comma-separated substrings — log lines containing any of these are silently dropped.
# Set via ARGUS_IGNORE_PATTERNS env var.
_IGNORE_PATTERNS: list[str] = [
    p.strip().lower()
    for p in os.getenv("ARGUS_IGNORE_PATTERNS", "").split(",")
    if p.strip()
]

# Time when this module was imported — used as the default cursor base.
_MODULE_START: datetime = datetime.now(tz=timezone.utc)

# Per-container ring buffers and read cursors.
_buffers: dict[str, deque[LogEvent]] = {}
_cursors: dict[str, datetime] = {}   # container → last-fetched-up-to timestamp
_lock = threading.Lock()


def _get_docker_client() -> docker.DockerClient | None:
    try:
        return docker.from_env()
    except Exception as exc:
        logger.warning("event=cannot_connect_docker_socket Cannot connect to Docker socket: %s", exc)
        return None


def _parse_level(line: str) -> str | None:
    """Return the highest-severity keyword found in a log line, or None."""
    found = LOG_LEVEL_PATTERN.findall(line)
    if not found:
        return None
    for lvl in ("CRITICAL", "ERROR", "WARNING"):
        if any(f.upper() == lvl for f in found):
            return lvl
    return None


def _demux_docker_logs(raw: bytes) -> list[bytes]:
    """Demultiplex Docker log stream, stripping the 8-byte frame headers.

    Docker's log API uses a multiplexed stream format for non-TTY containers:
        [stream_type: 1 byte][padding: 3 bytes][payload_size: 4 bytes big-endian]
        [payload: payload_size bytes] ...

    stream_type: 1 = stdout, 2 = stderr.  TTY containers have no headers.
    We detect the multiplexed format by checking whether the first byte is 1 or 2
    and whether the encoded size is consistent with the buffer length.
    """
    if not raw:
        return []

    # Heuristic: valid multiplexed stream starts with stream_type 1 or 2
    # and the 4-byte size at bytes 4-8 must be <= remaining buffer length.
    if len(raw) >= 8 and raw[0] in (1, 2):
        size_hint = struct.unpack(">I", raw[4:8])[0]
        if size_hint <= len(raw) - 8:
            # Looks like a multiplexed stream — demux it properly.
            lines: list[bytes] = []
            pos = 0
            while pos < len(raw):
                if pos + 8 > len(raw):
                    break
                stream_type = raw[pos]
                if stream_type not in (1, 2):
                    # Frame header no longer valid — treat rest as raw.
                    lines.extend(raw[pos:].splitlines())
                    break
                size = struct.unpack(">I", raw[pos + 4: pos + 8])[0]
                pos += 8
                chunk = raw[pos: pos + size]
                pos += size
                lines.extend(chunk.splitlines())
            return lines

    # TTY container or already decoded raw bytes.
    return raw.splitlines()


def poll_container_logs(container_name: str, service_name: str) -> list[LogEvent]:
    """Fetch only NEW log lines from a container since the last poll.

    Returns the list of :class:`LogEvent` objects that were produced since the
    last call for this container.  An empty list is returned when the container
    is absent or has no new relevant log lines.

    Side-effect: appends new events to the in-memory ring buffer.
    """
    client = _get_docker_client()
    if client is None:
        return []

    with _lock:
        if container_name not in _cursors:
            # First time we see this container — look back a few minutes.
            _cursors[container_name] = _MODULE_START - timedelta(
                minutes=BACKFILL_MINUTES
            )
        since = _cursors[container_name]
        if container_name not in _buffers:
            _buffers[container_name] = deque(maxlen=BUFFER_SIZE)

    # Record fetch time BEFORE the request so we don't skip lines produced
    # between the request and when we update the cursor.
    fetch_at = datetime.now(tz=timezone.utc)

    try:
        container = client.containers.get(container_name)
    except docker.errors.NotFound:
        logger.debug(
            "event=container_found_may_running Container not found (may not be running): %s", container_name)
        return []
    except Exception as exc:
        logger.warning("event=cannot_get_container Cannot get container %s: %s", container_name, exc)
        return []

    try:
        raw: bytes = container.logs(
            since=since,
            until=fetch_at,
            stream=False,
            timestamps=False,
        )
    except Exception as exc:
        logger.warning("event=log_fetch_failed log fetch failed for %s: %s", container_name, exc)
        return []

    new_events: list[LogEvent] = []
    for raw_line in _demux_docker_logs(raw):
        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        if IGNORE_HEALTH_ACCESS and HEALTH_ACCESS_PATTERN.search(line):
            continue
        if _IGNORE_PATTERNS and any(p in line.lower() for p in _IGNORE_PATTERNS):
            continue
        level = _parse_level(line)
        if level is None:
            continue
        event = LogEvent(
            timestamp=fetch_at.isoformat(),
            service=service_name,
            container=container_name,
            level=level,
            message=line,
        )
        new_events.append(event)

    with _lock:
        _cursors[container_name] = fetch_at
        buf = _buffers[container_name]
        for evt in new_events:
            buf.append(evt)

    if new_events:
        logger.debug(
            "event=fetched_new_log_events_from Fetched %d new log events from %s", len(
                new_events), container_name
        )
    return new_events


def get_events(
    container_name: str | None = None,
    level_min: str = "WARNING",
) -> list[LogEvent]:
    """Return buffered log events, optionally filtered by container and level.

    ``level_min`` follows severity ordering: WARNING < ERROR < CRITICAL.
    """
    severity = {"WARNING": 0, "ERROR": 1, "CRITICAL": 2}
    min_sev = severity.get(level_min.upper(), 0)

    with _lock:
        if container_name:
            sources = {container_name: list(
                _buffers.get(container_name, deque()))}
        else:
            sources = {k: list(v) for k, v in _buffers.items()}

    events: list[LogEvent] = []
    for buf in sources.values():
        for evt in buf:
            if severity.get(evt.level.upper(), 0) >= min_sev:
                events.append(evt)

    events.sort(key=lambda e: e.timestamp)
    return events
