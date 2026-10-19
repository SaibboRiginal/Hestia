"""Mail watcher: the one look at the mailbox (history API) → headers pushed to Iris.
SPEC docs/work/2026-10-19-email-push-spese §3.1."""
from __future__ import annotations

import pytest

from core.mail_watch import MailWatcher
from providers.google import GmailHistoryExpired, GoogleMailAuthError


class FakeGmail:
    def __init__(self):
        self.history = "100"
        self.added: list[str] = []
        self.expired = False
        self.available = True
        self.auth_fail = False
        self.searches = []

    def is_available(self):
        return self.available

    def current_history_id(self):
        return self.history

    def added_since(self, start):
        if self.auth_fail:
            raise GoogleMailAuthError("revoked")
        if self.expired:
            raise GmailHistoryExpired(start)
        return list(self.added), self.history

    def list_messages(self, q="", limit=20, since=None, full=True):
        self.searches.append((q, since, full))
        return [{"id": i} for i in self.added]

    def headers(self, mid):
        return {"id": mid, "from": f"x{mid}@paypal.it", "subject": f"s{mid}", "labels": ["INBOX"],
                "body": "never sent"}


class FakeGateway:
    def __init__(self, gmail):
        self._g = gmail
        self.resets = 0

    def gmail(self):
        return self._g

    def reset(self):
        self.resets += 1


@pytest.fixture()
def env(tmp_path):
    gmail = FakeGmail()
    pushed = []
    state = {"ok": True}

    def push(rows, source):
        pushed.append((rows, source))
        return state["ok"]

    w = MailWatcher(tmp_path / "w.json", FakeGateway(gmail), push)
    return w, gmail, pushed, state


@pytest.mark.unit
class TestMailWatcher:
    def test_first_run_only_sets_cursor(self, env):
        w, gmail, pushed, _ = env
        assert w.run()["status"] == "initialized"
        assert w.state["history_id"] == "100" and not pushed

    def test_new_mail_pushed_headers_only(self, env):
        w, gmail, pushed, _ = env
        w.run()
        gmail.added, gmail.history = ["a", "b"], "105"
        out = w.run("agenda")
        assert out == {"status": "ok", "new": 2, "source": "history"}
        rows, source = pushed[0]
        assert [r["id"] for r in rows] == ["a", "b"] and "body" not in rows[0] and source == "history"
        assert w.state["history_id"] == "105" and w.state["pushed_total"] == 2

    def test_nothing_new_pushes_nothing(self, env):
        w, gmail, pushed, _ = env
        w.run()
        assert w.run()["new"] == 0 and not pushed

    def test_iris_down_keeps_cursor_and_retries(self, env, tmp_path):
        w, gmail, pushed, state = env
        w.run()
        gmail.added, gmail.history = ["a"], "105"
        state["ok"] = False
        assert w.run()["status"] == "error"
        assert w.state["history_id"] == "100" and w.state["pending"] == ["a"]
        # restart: state survives on disk
        w2 = MailWatcher(tmp_path / "w.json", w.gateway, w.push)
        state["ok"], gmail.added = True, []
        assert w2.run()["new"] == 1           # the pending mail is offered again
        assert w2.state["history_id"] == "105" and not w2.state["pending"]

    def test_history_expired_falls_back_to_search(self, env):
        w, gmail, pushed, _ = env
        w.run()
        gmail.expired, gmail.added, gmail.history = True, ["z"], "999"
        out = w.run()
        assert out["source"] == "fallback" and out["new"] == 1
        assert gmail.searches and gmail.searches[0][2] is False and w.state["history_id"] == "999"

    def test_not_authorized_is_skipped(self, env):
        w, gmail, pushed, _ = env
        gmail.available = False
        out = w.run()
        assert out["status"] == "skipped" and out["action_required"] == "reauth_google"

    def test_auth_failure_resets_gateway(self, env):
        w, gmail, pushed, _ = env
        w.run()
        gmail.auth_fail = True
        assert w.run()["status"] == "skipped" and w.gateway.resets == 1


@pytest.mark.api
class TestMailWatchEndpoints:
    def test_status_and_agenda_rule(self):
        from fastapi.testclient import TestClient
        import main
        r = TestClient(main.app).get("/api/gateway/mail/watch")
        assert r.status_code == 200
        body = r.json()
        assert body["agenda_job"] == "hecate.mail_watch" and body["push"]["configured"] is False
        assert body["interval_seconds"] == 900
        rules = main._mail_agenda_rules()
        assert [r["key"] for r in rules] == ["hecate.mail_watch"]
        assert rules[0]["recurrence"] == "FREQ=MINUTELY;INTERVAL=15"

    def test_pubsub_configured_adds_renew_and_slows_check(self, monkeypatch):
        import main
        monkeypatch.setenv("HECATE_GMAIL_PUBSUB_TOPIC", "projects/p/topics/t")
        monkeypatch.setenv("HECATE_GMAIL_PUBSUB_SUBSCRIPTION", "projects/p/subscriptions/s")
        rules = main._mail_agenda_rules()
        assert [r["key"] for r in rules] == ["hecate.mail_watch", "hecate.mail_watch_renew"]
        assert rules[0]["recurrence"] == "FREQ=MINUTELY;INTERVAL=360"

    def test_renew_inactive_without_config(self):
        from fastapi.testclient import TestClient
        import main
        r = TestClient(main.app).post("/api/gateway/mail/watch/renew")
        assert r.json()["status"] == "inactive"
