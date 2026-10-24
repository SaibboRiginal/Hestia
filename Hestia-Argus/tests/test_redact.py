"""hestia_common.redact: logs are cleaned before they reach a model (Cindy idea 19)."""
from __future__ import annotations

import pytest

from hestia_common.redact import found, redact, redact_obj

pytestmark = pytest.mark.unit


def test_secrets_and_personal_data_are_replaced():
    log = ("ERROR login failed for someone@example.com token=abc123secret456 "
           "https://user:pw@host/x?access_token=zzz chat_id=123456789 C:\\Users\\Someone\\x "
           "/home/someone/a 192.168.1.20 AIzaSyA1234567890123456789012345678901 "
           "Bearer abcdefghijklmnopqrstuv +39 333 123 4567 IT60 X054 2811 1010 0000 0123 456")
    out = redact(log)
    for secret in ("someone@example.com", "abc123secret456", "user:pw", "zzz", "123456789", "Someone",
                   "/home/someone", "192.168.1.20", "AIzaSy", "abcdefghijklmnopqrstuv", "333 123 4567", "IT60"):
        assert secret not in out, secret
    assert "[email]" in out and "[segreto]" in out and "[ip]" in out


def test_normal_log_text_is_kept():
    line = "2026-10-24 12:30:00.123 event=chat_done took 1234 ms port 19004 id 20261024 status=500"
    assert redact(line) == line
    assert found(line) == []


def test_objects_hide_secret_keys():
    out = redact_obj({"password": "hunter2", "nested": [{"msg": "mail me at a@b.it"}], "count": 3})
    assert out == {"password": "[segreto]", "nested": [{"msg": "mail me at [email]"}], "count": 3}


def test_argus_analysis_redacts_before_oracle(monkeypatch):
    from core import oracle_client

    sent = {}

    class _Resp:
        ok, content = True, b"{}"

        def raise_for_status(self):
            return None

        def json(self):
            return {"status_code": 200, "payload": {"response": "ok"}}

    def _post(url, json=None, timeout=None):
        sent.update(json["body"])
        return _Resp()

    monkeypatch.setattr(oracle_client.requests, "post", _post)
    assert oracle_client.analyze("token=supersecretvalue user x@y.com") == "ok"
    assert "supersecretvalue" not in sent["prompt"] and "x@y.com" not in sent["prompt"]
