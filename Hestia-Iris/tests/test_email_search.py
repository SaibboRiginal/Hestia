from fastapi.testclient import TestClient

from app.main import app


def test_email_search_filters_messages_by_query():
    client = TestClient(app)

    send_a = {
        "to": "alice@example.com",
        "subject": "Flight booking",
        "body": "Ticket details attached",
    }
    send_b = {
        "to": "bob@example.com",
        "subject": "Groceries",
        "body": "Remember milk and bread",
    }

    client.post("/api/email/send", json=send_a)
    client.post("/api/email/send", json=send_b)

    response = client.get("/api/email/messages",
                          params={"q": "flight", "limit": 20})
    assert response.status_code == 200

    payload = response.json()
    assert payload["count"] >= 1
    subjects = [row.get("subject", "") for row in payload["messages"]]
    assert any("Flight booking" in value for value in subjects)
