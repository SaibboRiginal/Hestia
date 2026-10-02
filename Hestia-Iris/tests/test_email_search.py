from fastapi.testclient import TestClient

from app.main import app


def test_email_search_delegates_to_hecate(fake_hecate):
    client = TestClient(app)
    client.post("/api/email/send", json={"to": "a@x.com", "subject": "Flight booking", "body": "Ticket"})
    client.post("/api/email/send", json={"to": "b@x.com", "subject": "Groceries", "body": "milk"})

    response = client.get("/api/email/messages", params={"q": "flight", "limit": 20})
    assert response.status_code == 200
    subjects = [row["subject"] for row in response.json()["messages"]]
    assert subjects == ["Flight booking"]
    method, path, query, _ = fake_hecate.calls[-1]
    assert (method, path) == ("GET", "api/gateway/mail/messages")
    assert query["q"] == "flight"


def test_imap_filter_and_since_are_forwarded(fake_hecate):
    client = TestClient(app)
    client.get("/api/email/messages", params={"q": 'FROM "noreply@idealista.it"', "since": "2026-10-01"})
    _, _, query, _ = fake_hecate.calls[-1]
    assert query["q"] == 'FROM "noreply@idealista.it"'
    assert query["since"] == "2026-10-01"
