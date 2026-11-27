import time
from typing import Any, Iterator

import requests

DEADLINE_HEADER = "X-Hestia-Deadline"


def proxy_request(
    base_url: str,
    path: str,
    method: str,
    query: dict[str, Any],
    body: Any,
    headers: dict[str, str],
    timeout_seconds: float,
    stream: bool = False,
) -> tuple[int, Any] | Iterator[bytes]:
    normalized_path = path.lstrip("/")
    # When the caller stops waiting (epoch seconds): the target can skip work nobody will read (Oracle's LLM bus).
    timeout = max(1.0, float(timeout_seconds))
    headers = dict(headers or {})
    if not any(k.lower() == DEADLINE_HEADER.lower() for k in headers):
        headers[DEADLINE_HEADER] = f"{time.time() + timeout:.3f}"
    target = f"{base_url.rstrip('/')}/{normalized_path}" if normalized_path else base_url.rstrip("/")

    response = requests.request(
        method=method.upper(),
        url=target,
        params=query,
        json=body,
        headers=headers,
        timeout=timeout,
        stream=stream,
    )

    if stream:
        return response.iter_lines()

    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        return response.status_code, response.json()

    return response.status_code, {"raw": response.text}


_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def may_fail_over(method: str, error: BaseException) -> bool:
    """Whether a failed call may be sent again to the next instance of the same service.

    A read can always go elsewhere. A write (POST, PUT, PATCH, DELETE) goes elsewhere only when the first instance
    was never reached (connection refused, unknown host, connect timeout): after a read timeout or a connection cut
    mid-answer the first instance may have done the work already, and running it twice is worse than one error
    (core review 2026-11-27 §4.6)."""
    from urllib3.exceptions import NewConnectionError

    if str(method or "GET").upper() in _SAFE_METHODS:
        return True
    if isinstance(error, requests.ConnectTimeout):
        return True
    if isinstance(error, requests.ConnectionError) and not isinstance(error, requests.Timeout):
        cause = error.args[0] if error.args else None              # urllib3 MaxRetryError(reason=...)
        return isinstance(getattr(cause, "reason", cause), NewConnectionError)
    return False
