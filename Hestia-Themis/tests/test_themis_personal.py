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
    assert "_question" not in p
    q = {"kind": "single_choice", "options": ["Sì", "Dopo"], "service": "wardrobe", "path": "/api/x"}
    assert reminder_event(module="m", domain="d", key="k", title="t", text="?", actions=[],
                          question=q)["payload"]["_question"] == q


@pytest.mark.unit
def test_personal_places_validate_and_resolve_through_hecate():
    hub = FakeHub()
    calls = []
    inner = hub.call

    def call(svc, method, path, body=None, query=None, timeout=8):
        if svc == "hecate":
            calls.append((svc, path))
            return 200, {"options": [{"value": "casa", "label": "Casa · Milano"}]}
        return inner(svc, method, path, body=body, query=query, timeout=timeout)
    hub.call = call
    registry = Registry(None)
    registry.register("themis", list(PERSONAL.values()))
    themis = Themis(hub, registry)
    places = [{"id": "casa", "name": "Casa", "address": "Milano", "kind": "home"}]
    assert themis.set("themis.personal.places", places)["value"] == places
    with pytest.raises(Exception):
        themis.set("themis.personal.places", [{"name": "X", "kind": "castello"}])
    # «hecate:/path» options source: asked to Hecate, not to the owner (Themis)
    opts = themis.options("themis.personal.places")
    assert opts["options"][0]["label"] == "Casa · Milano" and calls == [("hecate", "/api/gateway/weather/places")]


# ── Who you are and who the assistant is (docs/work/2026-11-12-identita-e-proattivita) ───────────────────────

@pytest.mark.unit
def test_identity_settings_are_personal_with_hestia_she_by_default():
    from hestia_common.settings_client import PERSONAL
    assert PERSONAL["themis.personal.assistant_name"]["default"] == "Hestia"
    assert PERSONAL["themis.personal.assistant_gender"]["default"] == "lei"
    assert [o["value"] for o in PERSONAL["themis.personal.assistant_gender"]["options"]] == ["lei", "lui"]
    assert PERSONAL["themis.personal.owner_name"]["default"] == "" and "themis.personal.owner_call" in PERSONAL


@pytest.mark.unit
def test_identity_render_name_gender_owner():
    from hestia_common import identity
    template = "Sei {assistant}, {g:amica|amico} di {owner}. {owner_rule} JSON {\"a\": 1} {tools}"
    she = identity.render(template, identity.default())
    # Names and gendered words come from the template; what the library adds is English like every hidden text.
    assert she.startswith("Sei Hestia, amica di the person writing to you. You do not know their name yet")
    assert she.endswith('JSON {"a": 1} {tools}')                       # other braces untouched
    values = {identity.ASSISTANT_NAME: " Leo{}\n", identity.ASSISTANT_GENDER: "lui",
              identity.OWNER_NAME: "Marco", identity.OWNER_CALL: ""}
    he = identity.render(template, identity.read(values.get))
    assert he.startswith("Sei Leo, amico di Marco. Their name is Marco: use it now and then")
    assert identity.read(lambda key: None) == identity.default()
