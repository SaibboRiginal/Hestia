from typing import Any

import requests


def proxy_request(base_url: str, path: str, method: str, query: dict[str, Any], body: Any, headers: dict[str, str], timeout_seconds: float) -> tuple[int, Any]:
    normalized_path = path.lstrip("/")
    target = f"{base_url.rstrip('/')}/{normalized_path}" if normalized_path else base_url.rstrip("/")

    response = requests.request(
        method=method.upper(),
        url=target,
        params=query,
        json=body,
        headers=headers,
        timeout=max(1.0, float(timeout_seconds)),
    )

    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        return response.status_code, response.json()

    return response.status_code, {"raw": response.text}
