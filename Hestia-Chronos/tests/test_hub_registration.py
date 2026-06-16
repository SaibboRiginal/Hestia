from app.core import hub_client


class _DummyResponse:
    status_code = 200


def test_register_on_hub_payload_contains_topology_and_mcp(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["payload"] = json
        captured["timeout"] = timeout
        return _DummyResponse()

    monkeypatch.setattr(hub_client.requests, "post", fake_post)

    hub_client.register_on_hub(
        "http://hestia_hub:19001/api",
        "http://hestia_chronos:19007",
        max_attempts=1,
    )

    payload = captured["payload"]
    assert payload["name"] == "chronos"
    assert payload["topology_tags"] == [
        "layer:domain",
        "domain:calendar",
        "status:stable",
    ]

    # MCP endpoint must be present (replaces legacy commands list)
    caps = payload["capabilities"]
    assert "mcp_endpoint" in caps, f"Expected mcp_endpoint in capabilities, got keys: {list(caps.keys())}"
    assert caps["mcp_endpoint"].endswith("/mcp")

    # Tool endpoints still present for backward compat
    assert "tool_endpoints" in caps
