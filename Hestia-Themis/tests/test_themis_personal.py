"""Personal settings shared by every module (themis.personal.*): modules follow them, Themis pushes changes.

Markers: unit
"""
import sys
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
for _p in (str(_ROOT), str(_ROOT.parent / "Hestia-Shared")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from app.core.registry import Registry
from app.core.service import Themis
from hestia_common.reminders import reminder_event, reminder_settings
from hestia_common.settings_client import PERSONAL, SettingsClient


class FakeHub:
    def __init__(s):
        s.values = {}
        s.clients = {}

    def call(s, svc, method, path, body=None, query=None, timeout=8):
        q = {k: v for k, v in (query or {}).items() if v is not None}
        if svc == "archive" and path == "api/settings-store/values":
            if method == "GET":
                return 200, [dict(key=k[0], scope=k[1], scope_id=k[2], value=v) for k, v in s.values.items()
                             if (not q.get("key") or k[0] == q["key"])
                             and (not q.get("prefix") or k[0].startswith(q["prefix"]))
                             and (not q.get("scope") or k[1] == q["scope"])]
            if method == "PUT":
                s.values[(body["key"], body["scope"], body["scope_id"])] = body["value"]
                return 200, {}
        if path == "api/settings/reload" and svc in s.clients:
            c = s.clients[svc]
            c.apply(body["values"])
            c._shared_changed(body.get("shared"))
            return 200, {}
        return 200, {}

    def ok(s, svc, method, path, **kw):
        return s.call(svc, method, path, **kw)[1]


@pytest.mark.unit
def test_module_follows_personal_week_start():
    hub = FakeHub()
    registry = Registry(None)
    registry.register("themis", list(PERSONAL.values()))
    themis = Themis(hub, registry)
    client = SettingsClient("hercules", hub_api_url="http://x").declare(reminder_settings("hercules")).follow_personal()
    hub.clients["hercules"] = client
    client._call = lambda m, p, body=None, query=None, timeout=6: (200, themis.register(
        body["owner"], body["definitions"], body["presets"], body["effective"], body.get("follows")))
    assert client.register()
    assert client.get("themis.personal.week_start") == "monday"
    assert client.get("hercules.reminder.enabled") is False
    seen = []
    client.on_change(lambda c: seen.append(c))
    themis.set("themis.personal.week_start", "sunday")
    time.sleep(0.2)
    assert client.get("themis.personal.week_start") == "sunday"
    assert {"themis.personal.week_start": "sunday"} in seen


@pytest.mark.unit
def test_reminder_event_shape():
    body = reminder_event(module="wardrobe", domain="wardrobe", key="wardrobe.reminder", title="Guardaroba",
                          text="Cosa indossi oggi?", actions=[{"id": "skip"}], page="outfit")
    p = body["payload"]
    assert body["entity_id"] == "wardrobe.reminder" and p["replaces"] == "wardrobe.reminder"
    assert p["target"] == "owner" and p["_link"] == {"module": "wardrobe", "page": "outfit"}
    # Regression: Hermes' owner subscription listens on domain "system"; any other envelope domain
    # matched no subscription and the reminder was never delivered.
    assert body["domain"] == "system" and p["domain"] == "wardrobe"
