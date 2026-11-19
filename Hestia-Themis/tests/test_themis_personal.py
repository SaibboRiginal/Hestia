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
            return 200, {"options": [{"value": "home", "label": "Casa · Milano"}]}
        return inner(svc, method, path, body=body, query=query, timeout=timeout)
    hub.call = call
    registry = Registry(None)
    registry.register("themis", list(PERSONAL.values()))
    themis = Themis(hub, registry)
    places = [{"id": "home", "name": "Casa", "address": "Milano", "kind": "home"}]
    assert themis.set("themis.personal.places", places)["value"] == places
    with pytest.raises(Exception):
        themis.set("themis.personal.places", [{"name": "X", "kind": "castello"}])
    # «hecate:/path» options source: asked to Hecate, not to the owner (Themis)
    opts = themis.options("themis.personal.places")
    assert opts["options"][0]["label"] == "Casa · Milano" and calls == [("hecate", "/api/gateway/weather/places")]


# ── Who you are and who the assistant is (docs/work/2026-11-12-identity-and-proactivity) ───────────────────────

@pytest.mark.unit
def test_identity_settings_are_personal_with_hestia_she_by_default():
    from hestia_common.settings_client import PERSONAL
    assert PERSONAL["themis.personal.assistant_name"]["default"] == "Hestia"
    assert PERSONAL["themis.personal.assistant_gender"]["default"] == "she"
    assert [o["value"] for o in PERSONAL["themis.personal.assistant_gender"]["options"]] == ["she", "he"]
    assert PERSONAL["themis.personal.owner_name"]["default"] == "" and "themis.personal.owner_call" in PERSONAL


@pytest.mark.unit
def test_identity_render_name_gender_owner():
    from hestia_common import identity
    template = "Sei {assistant}, {g:amica|amico} di {owner}. {owner_rule} JSON {\"a\": 1} {tools}"
    she = identity.render(template, identity.default())
    # Names and gendered words come from the template; what the library adds is English like every hidden text.
    assert she.startswith("Sei Hestia, amica di the person writing to you. You do not know their name yet")
    assert she.endswith('JSON {"a": 1} {tools}')                       # other braces untouched
    values = {identity.ASSISTANT_NAME: " Leo{}\n", identity.ASSISTANT_GENDER: "he",
              identity.OWNER_NAME: "Marco", identity.OWNER_CALL: ""}
    he = identity.render(template, identity.read(values.get))
    assert he.startswith("Sei Leo, amico di Marco. Their name is Marco: use it now and then")
    assert identity.read(lambda key: None) == identity.default()


@pytest.mark.unit
def test_language_is_personal_and_fills_owner_language():
    """One language setting for everything she writes on her own (docs/work/2026-11-14-personal-language)."""
    from hestia_common import identity
    from hestia_common.settings_client import PERSONAL
    spec = PERSONAL[identity.LANGUAGE]
    assert spec["default"] == "it" and spec["group"] == "You and the assistant"
    assert [o["value"] for o in spec["options"]] == list(identity.LANGUAGES)
    assert identity.render("Write in {owner_language}.", identity.default()) == "Write in Italian."
    values = {identity.LANGUAGE: "EN"}
    assert identity.render("Write in {owner_language}.", identity.read(values.get)) == "Write in English."
    assert identity.read({identity.LANGUAGE: "klingon"}.get)["language"] == "it"     # unknown → default


# ── The chosen name in every fixed text (docs/work/2026-11-16-name-everywhere) ──────────────────────────────────

@pytest.mark.unit
def test_named_fills_only_name_and_gender():
    from hestia_common import identity
    she = identity.named("Chiedi a {assistant}, {g:sola|solo} {0} {owner}")
    assert she == "Chiedi a Hestia, sola {0} {owner}"                  # other braces stay for str.format
    he = identity.named("Chiedi a {assistant}, {g:sola|solo}", {"assistant": "Leo", "gender": "he"})
    assert he == "Chiedi a Leo, solo" and identity.named("Nessun token") == "Nessun token"


@pytest.mark.unit
def test_fixed_texts_say_the_chosen_name_in_every_language(monkeypatch):
    from hestia_common import i18n
    values = {"themis.personal.assistant_name": "Leo", "themis.personal.assistant_gender": "he",
              "themis.personal.language": "it"}
    monkeypatch.setattr(i18n, "_reader", values.get)
    assert i18n.t("Planned by {assistant}") == "Pianificato da Leo"
    assert i18n.t("Requested by {0}. Cancel or move it from {assistant}'s agenda.", "te") == \
        "Richiesto da te. Annulla o sposta dall'agenda di Leo."
    assert i18n.localize({"label": "{assistant}'s agenda"}) == {"label": "Agenda di Leo"}
    values["themis.personal.language"] = "en"
    assert i18n.t("Planned by {assistant}") == "Planned by Leo"
    assert i18n.t("What {assistant} thinks on {g:her|his} own: observes, proposes, filters with the score, acts.") \
        .startswith("What Leo thinks on his own")
    monkeypatch.setattr(i18n, "_reader", None)
    assert i18n.t("Planned by {assistant}").endswith("Hestia")     # no reader yet → the default name


@pytest.mark.unit
def test_setting_labels_with_the_name_are_rendered_in_italian_too(monkeypatch):
    from hestia_common import i18n, settings_client
    monkeypatch.setattr(i18n, "_reader", {"themis.personal.assistant_name": "Leo",
                                          "themis.personal.language": "it"}.get)
    spec = {"key": "x.y", "label": "{assistant} in other AIs · most space", "help": "How {assistant} answers you, on every client."}
    out = settings_client.translated(spec, "it")
    assert out["label"] == "Leo in altre AI · spazio massimo" and out["help"] == "Come ti risponde Leo, su ogni client."


@pytest.mark.unit
def test_localize_walks_lists_under_kept_keys(monkeypatch):
    """Dossier 2026-11-18-real-test-problems C: a plugin's ``page`` list and an ``action`` object hold people texts;
    only string values under KEEP_KEYS stay as they are. A tag never reaches people."""
    from hestia_common import i18n
    values = {"themis.personal.language": "it"}
    monkeypatch.setattr(i18n, "_reader", values.get)
    out = i18n.localize({"page": [{"id": "consegne", "label": "Deliveries"}], "action": {"label": "Plan"},
                         "status": "Deliveries", "area_label": "alt::Day", "args": {"q": "Deliveries"}})
    assert out["page"] == [{"id": "consegne", "label": "Consegne"}]
    assert out["status"] == "Deliveries"                 # a string under a kept key is an id, never translated
    assert out["area_label"] == "Giornata"
    assert out["args"] == {"q": "Deliveries"}            # the owner's data stays as it is
    values["themis.personal.language"] = "en"
    assert i18n.localize({"area_label": "alt::Day"}) == {"area_label": "Day"}
