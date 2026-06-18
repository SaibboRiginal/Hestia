import json
import logging
import os
import re
from collections import deque
from threading import Lock
from typing import Any

# ── Custom TRACE level (more verbose than DEBUG) ─────────────────────────────
_TRACE_LEVEL = 5
logging.addLevelName(_TRACE_LEVEL, "TRACE")


def _trace(self: logging.Logger, message: str, *args: Any, **kwargs: Any) -> None:
    if self.isEnabledFor(_TRACE_LEVEL):
        self._log(_TRACE_LEVEL, message, args, **kwargs)


logging.Logger.trace = _trace  # type: ignore[attr-defined]

# ── Monkey-patch uvicorn's AccessFormatter so it doesn't choke when our ─────
# ── filter rewrites record.args from 5→4 elements ──────────────────────────
try:
    from uvicorn.logging import AccessFormatter
    _orig_access_format_msg = AccessFormatter.formatMessage

    def _patched_access_format_msg(self, record: logging.LogRecord) -> str:
        # AccessFormatter expects exactly 5 positional args.  If our filter
        # has rewritten args to a different length, fall back to the standard
        # Formatter.formatMessage (record.msg % record.args).
        if record.args and len(record.args) == 5:
            return _orig_access_format_msg(self, record)
        return logging.Formatter.formatMessage(self, record)

    AccessFormatter.formatMessage = _patched_access_format_msg
except ImportError:
    pass  # uvicorn not installed — nothing to patch

# ── Runtime log-level state (mutable via set_log_level) ────────────────────
_LOG_LEVEL_LOCK = Lock()
_CURRENT_LOG_LEVEL: str = "INFO"


_SENSITIVE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(?i)(authorization\s*[:=]\s*)(bearer\s+)?[^\s,;]+"),
        r"\1[REDACTED]",
    ),
    (
        re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"),
        r"\1[REDACTED]",
    ),
    (
        re.compile(
            r"(?i)\b(api[_-]?key|token|access[_-]?token|refresh[_-]?token|password|passwd|secret|client_secret|x-api-key)\b\s*[:=]\s*(['\"]?)[^\s,'\"}]+\2"
        ),
        r"\1=[REDACTED]",
    ),
    (
        re.compile(r"(?i)(https?://[^\s/:@]+:)[^@\s/]+(@)"),
        r"\1[REDACTED]\2",
    ),
    (
        re.compile(r"(?i)(postgres(?:ql)?://[^\s/:@]+:)[^@\s/]+(@)"),
        r"\1[REDACTED]\2",
    ),
)


class _UvicornHealthAccessFilter(logging.Filter):
    """Control uvicorn health access logs via LOG_HEALTH_ACCESS_MODE.

    Modes:
        - info: keep level as-is
        - debug: downgrade to DEBUG
        - off: drop the record
    """

    _HEALTH_PATH_RE = re.compile(r'"[A-Z]+\s+/(?:health|healthz|ready|live)\b')

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != "uvicorn.access":
            return True
        try:
            message = record.getMessage()
        except Exception:
            return True
        if not self._HEALTH_PATH_RE.search(message):
            return True

        mode = os.getenv("LOG_HEALTH_ACCESS_MODE", "debug").strip().lower()
        if mode in {"off", "none", "false", "0", "disable", "disabled"}:
            return False
        if mode == "info":
            return True

        record.levelno = logging.DEBUG
        record.levelname = "DEBUG"
        return True


class _UvicornAccessLogFilter(logging.Filter):
    """Downgrade ALL uvicorn.access logs to TRACE and normalise format.

    Endpoint access logs (``GET /api/... 200``, etc.) are noisy at INFO.
    This filter pushes every uvicorn.access record down to TRACE so they
    only appear when ``LOG_LEVEL=TRACE`` is set explicitly.  Health-check
    records are handled separately by ``_UvicornHealthAccessFilter`` and
    may be dropped entirely before this filter runs.

    Uvicorn emits: ``'%s - "%s %s HTTP/%s" %d', client_addr, method,
    path, http_version, status_code`` — a 5-arg positional tuple.  The
    filter rewrites the message into Hestia's ``event= key=value`` style.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != "uvicorn.access":
            return True

        # Drop entirely unless LOG_LEVEL is TRACE or lower.  The level
        # check runs *before* filters (the record arrives at INFO), so
        # we must gate here — otherwise TRACE records leak at every level.
        if logging.getLogger().getEffectiveLevel() > _TRACE_LEVEL:
            return False

        record.levelno = _TRACE_LEVEL
        record.levelname = "TRACE"

        # Reformat to structured key=value style.
        # uvicorn args: (client_addr, method, path, http_version, status_code)
        try:
            if record.args and len(record.args) >= 5:
                record.msg = (
                    "event=http_access client=%s method=%s path=%s status=%s"
                )
                record.args = (
                    str(record.args[0]),
                    str(record.args[1]),
                    str(record.args[2]),
                    str(record.args[4]),
                )
        except Exception:
            pass  # Keep original message if parsing fails

        return True


class _HestiaMessageStyleFilter(logging.Filter):
    """Normalize internal logs to key/value style.

    Any internal Hestia log message that does not begin with ``event=`` is
    wrapped into a consistent fallback payload so all services emit a unified
    log style.
    """

    _THIRD_PARTY_PREFIXES = (
        "uvicorn",
        "fastapi",
        "starlette",
        "requests",
        "urllib3",
        "httpx",
        "telebot",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        logger_name = str(record.name or "")
        if logger_name.startswith(self._THIRD_PARTY_PREFIXES):
            return True
        if not logger_name.startswith("hestia_"):
            return True

        try:
            message = str(record.getMessage()).strip()
        except Exception:
            return True

        if not message or message.startswith("event="):
            return True

        compact = message.replace("\r", " ").replace("\n", " ").strip()
        record.msg = "event=legacy_log text=%s"
        record.args = (json.dumps(
            redact_sensitive_text(compact), ensure_ascii=True),)
        return True


def _attach_uvicorn_health_filter() -> None:
    """Attach health access filter to both logger and handlers.

    Uvicorn may install its own handlers, so attaching only on root handlers
    is not sufficient in all deployment modes.
    """
    health_filter = _UvicornHealthAccessFilter()

    target_loggers = [logging.getLogger(), logging.getLogger("uvicorn.access")]
    for target_logger in target_loggers:
        if not any(isinstance(current_filter, _UvicornHealthAccessFilter) for current_filter in target_logger.filters):
            target_logger.addFilter(health_filter)
        for handler in target_logger.handlers:
            if not any(isinstance(current_filter, _UvicornHealthAccessFilter) for current_filter in handler.filters):
                handler.addFilter(health_filter)


def _attach_uvicorn_access_filter() -> None:
    """Attach access-log→TRACE filter and strip uvicorn's AccessFormatter.

    Must run *after* ``_attach_uvicorn_health_filter`` so health checks
    are already dropped/downgraded before the blanket TRACE downgrade.

    Uvicorn installs an ``AccessFormatter`` on the ``uvicorn.access``
    handler that unpacks ``record.args`` as a 5-tuple.  Our filter
    rewrites the args to a 4-tuple (dropping ``http_version``), so we
    replace that formatter with a standard ``logging.Formatter`` that
    delegates to ``record.msg % record.args``.
    """
    access_filter = _UvicornAccessLogFilter()
    std_formatter = logging.Formatter(
        os.getenv("LOG_FORMAT", "%(asctime)s | %(levelname)s | %(name)s | %(message)s"))

    target_loggers = [logging.getLogger(), logging.getLogger("uvicorn.access")]
    for target_logger in target_loggers:
        if not any(isinstance(current_filter, _UvicornAccessLogFilter) for current_filter in target_logger.filters):
            target_logger.addFilter(access_filter)
        for handler in target_logger.handlers:
            if not any(isinstance(current_filter, _UvicornAccessLogFilter) for current_filter in handler.filters):
                handler.addFilter(access_filter)
            # Replace uvicorn's AccessFormatter so it doesn't choke on our 4-tuple args
            if handler.formatter is not None and type(handler.formatter).__name__ == "AccessFormatter":
                handler.setFormatter(std_formatter)


def _attach_hestia_style_filter() -> None:
    """Attach style normalizer to root logger and handlers."""
    style_filter = _HestiaMessageStyleFilter()

    target_loggers = [logging.getLogger(), logging.getLogger("uvicorn.access")]
    for target_logger in target_loggers:
        if not any(isinstance(current_filter, _HestiaMessageStyleFilter) for current_filter in target_logger.filters):
            target_logger.addFilter(style_filter)
        for handler in target_logger.handlers:
            if not any(isinstance(current_filter, _HestiaMessageStyleFilter) for current_filter in handler.filters):
                handler.addFilter(style_filter)


def redact_sensitive_text(value: str) -> str:
    text = value
    for pattern, replacement in _SENSITIVE_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _sanitize(value: Any) -> Any:
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, dict):
        return {k: _sanitize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


class InMemoryLogBufferHandler(logging.Handler):
    """Thread-safe in-memory log buffer for lightweight log APIs."""

    def __init__(self, capacity: int, log_format: str):
        super().__init__()
        self._records: deque[dict[str, Any]] = deque(maxlen=max(100, capacity))
        self._lock = Lock()
        self.setFormatter(logging.Formatter(log_format))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = redact_sensitive_text(record.getMessage())
            formatted = redact_sensitive_text(self.format(record))
            entry = {
                "ts": self.formatter.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
                "level": record.levelname,
                "logger": record.name,
                "message": message,
                "formatted": formatted,
            }
            with self._lock:
                self._records.append(entry)
        except Exception:
            self.handleError(record)

    def query(self, limit: int = 200, level: str | None = None, contains: str | None = None) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 2000))
        level_threshold = None
        if level:
            level_threshold = logging.getLevelName(level.upper())
            if not isinstance(level_threshold, int):
                level_threshold = None

        contains_lc = (contains or "").strip().lower()
        with self._lock:
            rows = list(self._records)

        if level_threshold is not None:
            rows = [
                row for row in rows
                if isinstance(logging.getLevelName(row.get("level", "")), int)
                and int(logging.getLevelName(row.get("level", ""))) >= level_threshold
            ]

        if contains_lc:
            rows = [
                row for row in rows
                if contains_lc in str(row.get("formatted", "")).lower()
            ]

        return [_sanitize(row) for row in rows[-limit:]]


def setup_service_logging(service_name: str) -> tuple[logging.Logger, InMemoryLogBufferHandler]:
    global _CURRENT_LOG_LEVEL
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    _CURRENT_LOG_LEVEL = level_name
    log_format = os.getenv(
        "LOG_FORMAT",
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    buffer_size = int(os.getenv("LOG_BUFFER_SIZE", "2000"))
    force_reconfigure = os.getenv("LOG_FORCE_RECONFIGURE", "true").lower() in {
        "1", "true", "yes", "on"
    }

    logging.basicConfig(level=level_name, format=log_format,
                        force=force_reconfigure)

    root_logger = logging.getLogger()
    _attach_uvicorn_health_filter()
    _attach_uvicorn_access_filter()
    _attach_hestia_style_filter()

    existing = next(
        (handler for handler in root_logger.handlers if isinstance(
            handler, InMemoryLogBufferHandler)),
        None,
    )
    if existing is not None:
        buffer_handler = existing
    else:
        buffer_handler = InMemoryLogBufferHandler(
            capacity=buffer_size, log_format=log_format)
        root_logger.addHandler(buffer_handler)

    logger = logging.getLogger(service_name)
    logger.info(
        "event=logging_configured service=%s level=%s buffer_size=%s",
        service_name,
        level_name,
        buffer_size,
    )
    return logger, buffer_handler


def set_log_level(level_name: str) -> str:
    """Change the effective log level at runtime across all loggers.

    Updates the root logger, all attached handlers, and uvicorn loggers
    so the new threshold takes effect immediately without a restart.

    Args:
        level_name: One of ``TRACE``, ``DEBUG``, ``INFO``, ``WARNING``,
                    ``ERROR``, ``CRITICAL`` (case-insensitive).

    Returns:
        The canonical (upper-case) level name that was applied.

    Raises:
        ValueError: If *level_name* is not a recognised log level.
    """
    global _CURRENT_LOG_LEVEL

    normalized = level_name.upper().strip()

    # TRACE (5) is a custom level — resolve it explicitly.
    if normalized == "TRACE":
        numeric_level = _TRACE_LEVEL
    else:
        numeric_level = logging.getLevelName(normalized)
        if not isinstance(numeric_level, int):
            raise ValueError(f"Unknown log level: {level_name!r}")

    # Root logger + handlers
    root = logging.getLogger()
    root.setLevel(numeric_level)
    for handler in root.handlers:
        handler.setLevel(numeric_level)

    # Uvicorn loggers (may have their own handlers installed by uvicorn)
    for logger_name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(logger_name)
        uvicorn_logger.setLevel(numeric_level)
        for handler in uvicorn_logger.handlers:
            handler.setLevel(numeric_level)

    with _LOG_LEVEL_LOCK:
        _CURRENT_LOG_LEVEL = normalized

    logging.getLogger("hestia_common.logging_utils").info(
        "event=log_level_changed level=%s", normalized)

    return normalized


def get_log_level() -> str:
    """Return the current effective log level name (e.g. ``"INFO"``)."""
    with _LOG_LEVEL_LOCK:
        return _CURRENT_LOG_LEVEL


def create_log_control_router(service_name: str):
    """Create a FastAPI router for runtime log-level control.

    Provides::

        GET  /api/logs/level   →  {"service": "<name>", "level": "INFO"}
        POST /api/logs/level   →  body: {"level": "DEBUG"}

    Mount in every FastAPI-based Hestia service::

        app.include_router(create_log_control_router("hestia_argus"))

    FastAPI and Pydantic are imported lazily — services that don't call
    this function (e.g. Telegram) are not required to install them.
    """
    from fastapi import APIRouter, HTTPException  # noqa: E402
    from pydantic import BaseModel                # noqa: E402

    class _SetLogLevelRequest(BaseModel):
        level: str

    router = APIRouter(tags=["meta"])

    @router.get("/api/logs/level")
    def _get_log_level():
        return {"service": service_name, "level": get_log_level()}

    @router.post("/api/logs/level")
    def _set_log_level(req: _SetLogLevelRequest):
        try:
            applied = set_log_level(req.level)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"service": service_name, "level": applied}

    return router


def log_event(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    parts = [f"event={event}"]
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            rendered = json.dumps(
                value, ensure_ascii=True, separators=(",", ":"))
        else:
            rendered = str(value)
        parts.append(f"{key}={rendered}")
    logger.log(level, " ".join(parts))
