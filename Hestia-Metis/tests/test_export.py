"""Training dataset D3 «Esporta» (docs/work/2026-10-30-dataset-allenamento §3.4). Markers: unit"""
import base64
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
for _p in (str(_ROOT), str(_ROOT.parent / "Hestia-Shared")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.core.export import Exporter, _eval_session, to_messages, usable
from tests.test_review import Archive, Review, Teacher, seed

pytestmark = pytest.mark.unit


class BlobArchive(Archive):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.blobs: dict = {}

    def ok(self, service, method, path, *, body=None, query=None, timeout=8):
        if path == "api/blobs":
            bid = f"b{len(self.blobs) + 1}"
            self.blobs[bid] = body
            return {"blob_id": bid}
        if path.startswith("api/blobs/") and path.endswith("/base64"):
            b = self.blobs[path.split("/")[2]]
            return {"blob_id": path.split("/")[2], "mime": b["content_type"], "data_b64": b["data_base64"]}
        return super().ok(service, method, path, body=body, query=query, timeout=timeout)


STEPS = [{"tool": "people_save", "params": {"name": "Laura Rossi"}, "ok": True, "result": "ok"},
         {"tool": "memory_save", "params": {"fact": "mamma Laura Rossi"}, "ok": True, "result": "ok"}]


def unzip(arc, out):
    raw = base64.b64decode(arc.blobs[out["blob_id"]]["data_base64"])
    z = zipfile.ZipFile(io.BytesIO(raw))
    rows = {n: [json.loads(x) for x in z.read(n).decode().splitlines() if x] for n in z.namelist() if n.endswith(".jsonl")}
    return rows, json.loads(z.read("card.json"))


def test_to_messages_applies_the_fix():
    d = {"system": "SYS", "history": "Tu: ciao", "user": "Mia mamma?", "answer": "Laura, salvata.", "steps": STEPS,
         "route": "agent"}
    msgs, final, original = to_messages(d, {"verdict": "fix", "answer": "Laura.", "remove_steps": [1]})
    assert msgs[0]["role"] == "system" and "CONTESTO CONVERSAZIONE" in msgs[0]["content"]
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "tool"]
    assert msgs[2]["tool_calls"][0]["function"]["name"] == "people_save"
    assert (final, original) == ("Laura.", "Laura, salvata.")
    quick = to_messages({"system": "SYS\nMESSAGGIO UTENTE: ciao", "user": "ciao", "answer": "Ciao!", "route": "quick"},
                        None)[0]
    assert quick[0]["content"] == "SYS"


@pytest.mark.parametrize("rv,inc,ok", [
    (None, False, False), (None, True, True), ({"status": "accepted", "verdict": "keep"}, False, True),
    ({"status": "pending", "verdict": "fix"}, False, False), ({"status": "rejected", "verdict": "drop"}, True, False),
    ({"status": "edited"}, False, True)])
def test_usable(rv, inc, ok):
    assert usable(rv, inc) is ok


def _reviewed():
    arc = BlobArchive()
    seed(arc, user="Mia mamma si chiama Laura Rossi", answer="Ho salvato Laura in Persone e in memoria.", steps=STEPS)
    seed(arc, tid="t2", user="Che ore sono?", answer="Le 10.")
    Review(arc, llm=Teacher({"verdict": "fix", "confidence": 0.95, "answer": "Ho salvato <PERSONA_1> in Persone.",
                             "remove_steps": [1]})).run()
    return arc


def test_masked_export_hides_people_and_has_dpo_pair():
    arc = _reviewed()
    ex = Exporter(arc, people=lambda: ["Laura Rossi"])
    out = ex.build()
    assert out["masked"] is True and out["name"].endswith("-oscurato.zip")
    rows, card = unzip(arc, out)
    dump = json.dumps(rows, ensure_ascii=False)
    assert "Laura" not in dump and "<PERSONA_1>" in dump
    assert card["sft"] + card["eval"] == 2 and card["dpo"] == 2 and card["corrected"] == 2
    t1 = next(r for r in rows["sft.jsonl"] + rows["eval.jsonl"] if "Persone" in r["messages"][-1]["content"])
    assert t1["messages"][-1]["content"] == "Ho salvato <PERSONA_1> in Persone."
    assert not any(m.get("name") == "memory_save" for m in t1["messages"]) and t1["tools"]
    assert ex.list()[0]["id"] == out["id"]
    f = ex.file_b64(out["id"])
    assert f["name"] == out["name"] and base64.b64decode(f["data_b64"])[:2] == b"PK"


def test_clear_export_keeps_real_text_and_skips_unreviewed():
    arc = _reviewed()
    seed(arc, tid="t3", sid="s9", user="Nuovo", answer="Ok.")
    called = []
    out = Exporter(arc, people=lambda: called.append(1) or []).build(masked=False)
    rows, card = unzip(arc, out)
    assert not called and out["name"].endswith("-in-chiaro.zip") and card["masked"] is False
    assert "Laura Rossi" in json.dumps(rows, ensure_ascii=False)
    assert card["skipped"] == 1 and card["turns"] == 3


def test_masked_export_refuses_without_people():
    arc = _reviewed()

    def down():
        raise OSError("hera down")
    with pytest.raises(OSError):
        Exporter(arc, people=down).build()
    assert not arc.blobs


def test_eval_split_is_by_session():
    assert _eval_session("abc") == _eval_session("abc")
    share = sum(_eval_session(f"s{i}") for i in range(2000)) / 2000
    assert 0.05 < share < 0.15
