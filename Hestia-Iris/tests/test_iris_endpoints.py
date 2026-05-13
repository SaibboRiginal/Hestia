"""Additional unit tests for Iris email domain endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app, _MESSAGES


@pytest.fixture(autouse=True)
def clear_messages():
    """Reset in-memory message store before each test."""
    _MESSAGES.clear()
    yield
    _MESSAGES.clear()


@pytest.fixture()
def client():
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["service"] == "hestia_iris"


# ---------------------------------------------------------------------------
# /api/email/inbox
# ---------------------------------------------------------------------------


def test_inbox_empty(client):
    resp = client.get("/api/email/inbox")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 0
    assert data["messages"] == []


def test_inbox_returns_sent_messages(client):
    client.post("/api/email/send",
                json={"to": "a@b.com", "subject": "Hello", "body": "World"})
    client.post("/api/email/send",
                json={"to": "c@d.com", "subject": "Second", "body": "Body"})

    resp = client.get("/api/email/inbox")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2


def test_inbox_respects_limit(client):
    for i in range(10):
        client.post("/api/email/send",
                    json={"to": f"u{i}@example.com", "subject": f"Msg {i}", "body": "."})

    resp = client.get("/api/email/inbox?limit=3")
    assert resp.status_code == 200
    assert len(resp.json()["messages"]) <= 3


# ---------------------------------------------------------------------------
# /api/email/send
# ---------------------------------------------------------------------------


def test_send_stores_message(client):
    resp = client.post(
        "/api/email/send",
        json={"to": "test@example.com",
              "subject": "Unit Test", "body": "Body text"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "id" in data["sent"]
    assert len(_MESSAGES) == 1
    assert _MESSAGES[0]["subject"] == "Unit Test"


def test_send_assigns_new_thread_if_none_provided(client):
    resp = client.post(
        "/api/email/send",
        json={"to": "a@b.com", "subject": "No thread", "body": "body"},
    )
    msg = resp.json()
    assert msg["sent"]["thread_id"] is not None


def test_send_uses_provided_thread_id(client):
    resp = client.post(
        "/api/email/send",
        json={"to": "a@b.com", "subject": "Reply",
              "body": "body", "thread_id": "thread-xyz"},
    )
    assert resp.json()["sent"]["thread_id"] == "thread-xyz"


# ---------------------------------------------------------------------------
# /api/email/messages (search)
# ---------------------------------------------------------------------------


def test_search_empty_store(client):
    resp = client.get("/api/email/messages?q=anything")
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


def test_search_matches_subject(client):
    client.post("/api/email/send", json={"to": "a@b.com",
                "subject": "Invoice #123", "body": "See attached"})
    client.post("/api/email/send", json={"to": "a@b.com",
                "subject": "Newsletter", "body": "Weekly roundup"})

    resp = client.get("/api/email/messages?q=invoice")
    data = resp.json()
    assert data["count"] >= 1
    assert all("Invoice" in m["subject"] or "invoice" in m.get(
        "body", "") for m in data["messages"])


def test_search_matches_body(client):
    client.post("/api/email/send", json={"to": "a@b.com",
                "subject": "Update", "body": "Your account has been upgraded"})

    resp = client.get("/api/email/messages?q=upgraded")
    assert resp.json()["count"] >= 1


def test_search_case_insensitive(client):
    client.post("/api/email/send",
                json={"to": "a@b.com", "subject": "FLIGHT BOOKING", "body": "details"})

    resp = client.get("/api/email/messages?q=flight")
    assert resp.json()["count"] >= 1


def test_search_respects_limit(client):
    for i in range(10):
        client.post("/api/email/send",
                    json={"to": f"u{i}@x.com", "subject": f"Same topic {i}", "body": "same"})

    resp = client.get("/api/email/messages?q=same&limit=4")
    assert len(resp.json()["messages"]) <= 4


def test_search_no_query_returns_all(client):
    client.post("/api/email/send",
                json={"to": "a@b.com", "subject": "Alpha", "body": "body1"})
    client.post("/api/email/send",
                json={"to": "b@c.com", "subject": "Beta", "body": "body2"})

    resp = client.get("/api/email/messages")
    assert resp.json()["count"] == 2


# ---------------------------------------------------------------------------
# /api/email/threads/{thread_id}
# ---------------------------------------------------------------------------


def test_thread_returns_matching_messages(client):
    client.post("/api/email/send", json={"to": "a@b.com",
                "subject": "Re: Topic", "body": "Reply", "thread_id": "t-001"})
    client.post("/api/email/send",
                json={"to": "c@d.com", "subject": "Other", "body": "Other"})

    resp = client.get("/api/email/threads/t-001")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["messages"][0]["thread_id"] == "t-001"


def test_thread_not_found_returns_404(client):
    resp = client.get("/api/email/threads/nonexistent-thread")
    assert resp.status_code == 404


def test_thread_collects_multiple_messages(client):
    for i in range(3):
        client.post(
            "/api/email/send",
            json={"to": "a@b.com", "subject": f"Part {i}",
                  "body": ".", "thread_id": "t-multi"},
        )
    client.post("/api/email/send",
                json={"to": "x@y.com", "subject": "Unrelated", "body": "."})

    resp = client.get("/api/email/threads/t-multi")
    assert resp.json()["count"] == 3


# ---------------------------------------------------------------------------
# /api/logs
# ---------------------------------------------------------------------------


def test_get_logs(client):
    resp = client.get("/api/logs?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert data["service"] == "hestia_iris"
    assert "logs" in data
