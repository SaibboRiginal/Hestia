"""Iris test suite conftest."""
from __future__ import annotations

import os
import sys

_IRIS_APP = os.path.join(os.path.dirname(__file__), "..", "app")
_SHARED = os.path.join(os.path.dirname(__file__), "..", "..", "Hestia-Shared")
for _p in [_IRIS_APP, _SHARED]:
    _abs = os.path.abspath(_p)
    if _abs not in sys.path:
        sys.path.insert(0, _abs)

os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("HUB_API_URL", "http://localhost:19001/api")
os.environ.setdefault("STARTUP_WAIT_TIMEOUT_SECONDS", "0")


import pytest


class FakeHecateMailbox:
    """Stands in for Hecate's /api/gateway/email/* + mail/status (Iris now delegates mail to Hecate)."""

    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.calls: list[tuple] = []

    def __call__(self, method, path, *, query=None, body=None, timeout=30):
        self.calls.append((method, path, query, body))
        query = query or {}
        if path.endswith("/send"):
            row = {"id": f"m{len(self.messages)}", "to": body["to"], "subject": body["subject"],
                   "body": body["body"], "from": "me@example.com",
                   "thread_id": body["subject"].lower().removeprefix("re: ").strip(),
                   "created_at": f"2026-10-02T10:{len(self.messages):02d}:00+00:00"}
            self.messages.append(row)
            return {"status": "ok", "sent": dict(row)}
        if path.endswith("mail/status"):
            return {"status": "ok", "configured": True}
        q = str(query.get("q") or "").lower()
        if q.startswith("subject "):
            q = q.split(" ", 1)[1].strip('"')
        rows = [m for m in self.messages if not q or q in m["subject"].lower() or q in m["body"].lower()]
        rows = sorted(rows, key=lambda m: m["created_at"], reverse=True)[: int(query.get("limit", 50))]
        return {"status": "ok", "count": len(rows), "messages": rows}


@pytest.fixture(autouse=True)
def fake_hecate(monkeypatch):
    import app.main as iris_main

    box = FakeHecateMailbox()
    monkeypatch.setattr(iris_main, "_hecate", box)
    return box
