from app.core import hub_client


class _DummyResponse:
    status_code = 200


def test_register_on_hub_payload_contains_topology_and_commands(monkeypatch):
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
    command_names = {row.get("command")
                     for row in payload["capabilities"]["commands"]}
    assert "agenda" in command_names
    assert "create_event" in command_names
    assert "calendar_list_events" in command_names
    assert "calendar_create_event" in command_names
    assert "calendar_update_event" in command_names
    assert "calendar_delete_event" in command_names
