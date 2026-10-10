"""Themis core: validation, live/restart apply, presets, scopes, undo, proposals (mocked Hub/Archive).

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
from app.core.service import Themis, ThemisError
from app.core.hub import HubError
from hestia_common.settings_client import SettingsClient, setting, preset

class FakeArchive:
    def __init__(s): s.values={}; s.hist=[]; s.props={}; s.calls=[]
    def call(s, svc, method, path, body=None, query=None, timeout=8):
        s.calls.append((svc, method, path))
        q = {k:v for k,v in (query or {}).items() if v is not None}
        if svc == "archive":
            if path == "api/settings-store/values" and method == "GET":
                rows=[dict(key=k[0],scope=k[1],scope_id=k[2],value=v) for k,v in s.values.items()
                      if (not q.get("key") or k[0]==q["key"]) and (not q.get("prefix") or k[0].startswith(q["prefix"]))
                      and (not q.get("scope") or k[1]==q["scope"]) and ("scope_id" not in q or k[2]==q["scope_id"])]
                return 200, rows
            if path == "api/settings-store/values" and method == "PUT":
                k=(body["key"],body["scope"],body["scope_id"]); old=s.values.get(k); s.values[k]=body["value"]
                s.hist.insert(0, dict(key=k[0],scope=k[1],scope_id=k[2],old_value=old,new_value=body["value"],actor=body["actor"]))
                return 200, {}
            if path == "api/settings-store/values" and method == "DELETE":
                k=(q["key"],q["scope"],q["scope_id"]); old=s.values.pop(k,None)
                s.hist.insert(0, dict(key=k[0],scope=k[1],scope_id=k[2],old_value=old,new_value=None,actor=q.get("actor")))
                return 200, {}
            if path == "api/settings-store/history":
                return 200, [h for h in s.hist if h["key"]==q["key"] and h["scope"]==q["scope"]][:q.get("limit",10)]
            if path == "api/settings-store/proposals" and method == "POST":
                s.props[body["proposal_id"]] = dict(body, status="pending"); return 200, s.props[body["proposal_id"]]
            if path == "api/settings-store/proposals" and method == "GET":
                return 200, [p for p in s.props.values() if not q.get("status") or p["status"]==q["status"]]
            if path.startswith("api/settings-store/proposals/") and method == "PATCH":
                p = s.props[path.rsplit("/",1)[1]]
                if p["status"] != body["only_if_status"]: return 409, {"detail":"x"}
                p["status"]=body["status"]; return 200, p
        if path == "api/settings/effective":
            return 200, {"values": client.values()}
        if path == "api/settings/reload":
            client.apply(body["values"]); return 200, {}
        return 200, {}
    def ok(s, svc, method, path, **kw):
        st, p = s.call(svc, method, path, **kw)
        if st >= 400: raise HubError(st, p)
        return p



@pytest.mark.unit
def test_themis_end_to_end():
    global client
    fake = FakeArchive()
    themis = Themis(fake, Registry(None))
    client = SettingsClient("argus", hub_api_url="http://x")
    client.declare([setting("argus.poll.interval","Intervallo","int",30,min=5,max=600),
                    setting("argus.workers","Worker","int",2,apply="restart"),
                    setting("argus.mode","Modo","enum","normal",options=[("calm","Calmo"),("normal","Normale")])],
                   presets=[preset("calm","Tranquillo",group="Generale",values={"argus.poll.interval":120,"argus.mode":"calm"})]).declare_log_level()
    client._call = lambda m, p, body=None, query=None, timeout=6: (200, themis.register(body["owner"], body["definitions"], body["presets"], body["effective"]))
    assert client.register()
    seen=[]; client.on_change(lambda c: seen.append(c))
    user = SettingsClient("oracle", hub_api_url="http://x")
    user.declare([setting("oracle.chat.tone","Tono","enum","warm",scope="user",options=["warm","neutral"])])
    themis.register("oracle", user._defs and list(user._defs.values()), [], {})

    r = themis.set("argus.poll.interval", "60"); time.sleep(0.2)
    assert client.get("argus.poll.interval") == 60, client.values()
    themis.set("argus.workers", 4); time.sleep(0.2)
    assert client.get("argus.workers") == 2
    items = {i["key"]: i for i in themis.list(module="argus")["items"]}
    assert items["argus.workers"]["status"] == "restart_required", items["argus.workers"]
    assert items["argus.poll.interval"]["status"] == "ok"
    try: themis.set("argus.poll.interval", 1); pytest.fail("min not enforced")
    except ThemisError as e: assert e.status == 422, e
    try: themis.set("argus.mode", "x"); pytest.fail("enum not enforced")
    except ThemisError: pass
    themis.undo("argus.poll.interval"); time.sleep(0.2); assert client.get("argus.poll.interval") == 30, client.values()
    themis.apply_preset("argus","calm"); time.sleep(0.2)
    st = themis.list(module="argus")["presets"]; assert st[0]["active"] == "calm", st
    themis.set("argus.mode","normal"); assert themis.list(module="argus")["presets"][0]["active"] == "custom"
    themis.set("argus.log.level","DEBUG"); time.sleep(0.2)
    from hestia_common.logging_utils import get_log_level; assert get_log_level()=="DEBUG"
    # user scope
    themis.set("oracle.chat.tone","neutral")  # profile
    assert themis.get("oracle.chat.tone")["source"] == "profile"
    themis.init_session("s1","webui")
    it = themis.get("oracle.chat.tone", session="s1"); assert it["source"]=="session" and it["value"]=="neutral", it
    themis.set("oracle.chat.tone","warm",scope="session",scope_id="s1")
    assert themis.get("oracle.chat.tone")["value"]=="neutral"
    # proposals
    try: themis.set("argus.mode","calm",actor="oracle"); pytest.fail("assistant direct set allowed")
    except ThemisError as e: assert e.status==403
    p = themis.propose("argus.mode","calm",proposer="oracle",reason="meno rumore")
    assert p["status"]=="pending"; assert themis.propose("argus.mode","calm",proposer="athena")["status"]=="already_pending"
    assert client.get("argus.mode")=="normal"
    d = themis.decide(p["proposal_id"], True, by="webui"); time.sleep(0.2)
    assert client.get("argus.mode")=="calm"
    try: themis.decide(p["proposal_id"], False); pytest.fail("second answer accepted")
    except ThemisError as e: assert e.status==409
