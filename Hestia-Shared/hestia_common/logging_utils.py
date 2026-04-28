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
