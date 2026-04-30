import json
import logging
import os
import re
from collections import deque
from threading import Lock
from typing import Any


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
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
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
