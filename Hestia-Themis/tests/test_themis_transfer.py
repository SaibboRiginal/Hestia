"""Settings in export / import: one section per module, validated on import, actor ``import``, no session copies.

Markers: unit
"""
import itertools
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
for _p in (str(_ROOT), str(_ROOT.parent / "Hestia-Shared")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from app.core.hub import HubError
from app.core.registry import Registry
from app.core.service import Themis
from app.core.transfer import settings_sections
from hestia_common.settings_client import setting
from hestia_common.transfer import Transfer

pytestmark = pytest.mark.unit

DEFS = {
    "argus": [setting("argus.poll.interval", "Intervallo", "int", 30, min=5, max=600, group="Controlli"),
              setting("argus.mode", "Modo", "enum", "normal", options=[("calm", "Calmo"), ("normal", "Normale")])],
    "oracle": [setting("oracle.chat.tone", "Tono", "enum", "warm", scope="user", options=["warm", "neutral"])],
}


_CLOCK = itertools.count(1)


class FakeHub:
    def __init__(self):
        self.values, self.actors = {}, []

    def call(self, svc, method, path, body=None, query=None, timeout=8):
        q = {k: v for k, v in (query or {}).items() if v is not None}
        if svc != "archive":
            return 200, {}
        if path == "api/settings-store/values" and method == "GET":
            return 200, [dict(key=k[0], scope=k[1], scope_id=k[2], value=v["value"], updated_at=v["at"])
                         for k, v in self.values.items()
                         if (not q.get("key") or k[0] == q["key"]) and (not q.get("prefix") or k[0].startswith(q["prefix"]))
                         and (not q.get("scope") or k[1] == q["scope"])]
        if path == "api/settings-store/values" and method == "PUT":
            self.values[(body["key"], body["scope"], body["scope_id"])] = {"value": body["value"],
                                                                            "at": f"2026-10-20T10:{next(_CLOCK):02d}:00+00:00"}
            self.actors.append(body["actor"])
            return 200, {}
        if path == "api/settings-store/values" and method == "DELETE":
            self.values.pop((q["key"], q["scope"], q["scope_id"]), None)
            self.actors.append(q.get("actor"))
            return 200, {}
        return 200, {}

    def ok(self, svc, method, path, **kw):
        st, p = self.call(svc, method, path, **kw)
        if st >= 400:
            raise HubError(st, p)
        return p


def _themis(defs=DEFS):
    hub = FakeHub()
    t = Themis(hub, Registry(None))
    for owner, d in defs.items():
        t.register(owner, d, [], {})
    return hub, t, Transfer("themis", hub, sections=lambda: settings_sections(t))


def test_settings_roundtrip_layers_and_validation():
    _, cloud, cloud_t = _themis()
    cloud.set("argus.poll.interval", 60)
    cloud.set("argus.mode", "calm")
    cloud.set("oracle.chat.tone", "neutral")                                 # profile layer
    cloud.set("oracle.chat.tone", "warm", scope="session", scope_id="s1")    # session copy: never exported
    described = {s["id"]: s["count"] for s in cloud_t.describe()["sections"]}
    assert described["argus"] == 2 and described["oracle"] == 1 and "themis" in described
    data = json.loads(json.dumps(cloud_t.export()))
    assert [r["scope"] for r in data["sections"]["oracle"]["records"]] == ["profile"]

    home_hub, home, home_t = _themis({"argus": DEFS["argus"]})              # oracle not installed at home
    home.set("argus.mode", "normal")
    data["sections"]["argus"]["records"].append({"key": "argus.poll.interval|system|x", "setting": "argus.poll.interval",
                                                 "scope": "system", "scope_id": "", "value": 1})   # below min
    preview = home_t.import_(data, mode="append", dry_run=True)
    a = preview["sections"]["argus"]
    assert (a["added"], a["skipped"], a["problems"]) == (1, 1, 1)
    assert preview["sections"]["oracle"]["problems"] == 1                   # unknown here → reported, skipped
    done = home_t.import_(data, mode="merge", dry_run=False)["sections"]["argus"]
    assert (done["added"], done["updated"], done["skipped"]) == (1, 0, 1)     # home changed the mode later
    assert home.get("argus.mode")["value"] == "normal" and home.get("argus.poll.interval")["value"] == 60
    home_t.import_(data, mode="replace", dry_run=False, selection={"argus": {}})
    assert home.get("argus.mode")["value"] == "calm"
    assert set(home_hub.actors) == {"user", "import"}


def test_replace_resets_values_only_at_home():
    _, cloud, cloud_t = _themis()
    cloud.set("argus.mode", "calm")
    data = cloud_t.export({"argus": {}})
    home_hub, home, home_t = _themis()
    home.set("argus.poll.interval", 90)
    r = home_t.import_(data, mode="replace", dry_run=False)["sections"]["argus"]
    assert (r["added"], r["deleted"]) == (1, 1)
    assert home.get("argus.poll.interval")["value"] == 30                   # back to default
