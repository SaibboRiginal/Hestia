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
