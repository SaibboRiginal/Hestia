from app import main as hecate_main


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.content = b"{}"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http_status={self.status_code}")

    def json(self):
        return self._payload


def test_route_via_hub_retries_once_after_auth_refresh(monkeypatch):
    monkeypatch.setenv("HUB_API_URL", "http://hestia_hub:19001/api")

    responses = [
        _FakeResponse(200, {"status_code": 401, "payload": {
                      "detail": "token expired"}}),
        _FakeResponse(200, {"status_code": 200, "payload": {"ok": True}}),
    ]

    calls = {"count": 0}

    def fake_post(url, json, timeout):
        _ = (url, json, timeout)
        calls["count"] += 1
        return responses[calls["count"] - 1]

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr(hecate_main, "gateway_auth_refresh", lambda provider: {
                        "provider": provider, "refreshed": True})

    status_code, payload = hecate_main._route_via_hub(
        "chronos",
        "/api/calendar/events/list",
        method="POST",
        body={"target_providers": ["google"]},
        timeout_seconds=10,
        auth_refresh_provider="google",
    )

    assert calls["count"] == 2
    assert status_code == 200
    assert payload == {"ok": True}
