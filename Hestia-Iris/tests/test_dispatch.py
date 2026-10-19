"""Iris mail dispatch (PUSH): subscriptions, matching, durable delivery, backfill.
SPEC docs/work/2026-10-19-email-push-spese §3.2. Hub is faked: Archive iris-store + raw records, Hecate, modules."""
from __future__ import annotations

import pytest

from dispatch import Dispatcher, fingerprint, gmail_query, header_match, sender_matches


class FakeHub:
    def __init__(self):
        self.store: dict[str, dict] = {}       # iris-store rows by id
        self.raw: dict[str, dict] = {}         # Archive raw records by reference_id
        self.rings: list[tuple] = []
        self.mails: dict[str, dict] = {}       # Hecate mailbox by gmail id
        self.searches: list[str] = []
        self.down: set[str] = set()

    def __call__(self, service, method, path, *, body=None, query=None, timeout=15):
        if service in self.down:
            return 0, "down"
        if service == "archive" and path == "api/iris-store/records":
            if method == "GET":
                return 200, {"rows": [{"kind": "subscription", "id": k, "data": v["data"], "deleted": v["deleted"]}
                                      for k, v in self.store.items()]}
            for r in body["rows"]:
                self.store[r["id"]] = r
            return 200, {"applied": [], "stale": []}
        if service == "archive" and path == "api/archive":
            self.raw.setdefault(body["reference_id"], body)
            return 200, {"id": len(self.raw)}
        if service == "hecate" and path.startswith("api/gateway/email/messages/"):
            gid = path.rsplit("/", 1)[1]
            return (200, {"message": self.mails[gid]}) if gid in self.mails else (404, {})
        if service == "hecate" and path == "api/gateway/email/messages":
            self.searches.append(query["q"])
            q = query["q"].lower()
            hits = [m for m in self.mails.values() if any(tok in m["from"].lower() for tok in
                                                          q.replace("from:(", "").replace(")", "").split(" or "))
                    or "paypal" in q and "paypal" in m["from"]]
            return 200, {"status": "ok", "messages": hits}
        self.rings.append((service, path, body))
        return 200, {"status": "ok"}


def mail(gid, sender, subject, labels=("INBOX",)):
    return {"id": gid, "from": sender, "subject": subject, "labels": list(labels), "body": f"body {gid}",
            "created_at": "2026-10-19T10:00:00+00:00", "thread_id": f"t{gid}"}


SCOUT = {"key": "listings", "title": "Annunci", "path": "/api/scout/mail", "domain": "real_estate",
         "senders": ["noreply@notifiche.immobiliare.it", "idealista.it"], "backfill_days": 0}
PLUTUS = {"key": "paypal", "title": "PayPal", "path": "/api/finance/mail", "domain": "finance",
          "senders": ["paypal.it", "paypal.com"], "backfill_days": 0}


@pytest.fixture()
def hub():
    return FakeHub()


@pytest.fixture()
def d(hub):
    disp = Dispatcher(hub)
    disp.register("scout", [SCOUT])
    disp.register("plutus", [PLUTUS])
    return disp


@pytest.mark.unit
class TestMatching:
    def test_sender_address_and_domain(self):
        assert sender_matches("a@idealista.it", ["idealista.it"])
        assert sender_matches("x@mail.idealista.it", ["@idealista.it"])
        assert sender_matches("service@paypal.it", ["service@paypal.it"])
        assert not sender_matches("service@paypal.it.evil.com", ["paypal.it"])
        assert not sender_matches("other@paypal.it", ["service@paypal.it"])

    def test_groups_and_or(self):
        rule = {"senders": ["paypal.it"], "subject_contains": ["ricevuta", "pagamento"]}
        assert header_match(rule, {"from": "PayPal <service@paypal.it>", "subject": "Ricevuta del tuo pagamento"})
        assert not header_match(rule, {"from": "PayPal <service@paypal.it>", "subject": "Novità"})
        assert header_match({"queries": ["x"]}, {"from": "a@b.c"}) is None

    def test_label_rule(self):
        assert header_match({"labels": ["Label_1"]}, {"labels": ["INBOX", "Label_1"]})
        assert not header_match({"labels": ["Label_1"]}, {"labels": ["INBOX"]})

    def test_gmail_query_for_backfill(self):
        assert gmail_query(SCOUT) == [("from:(noreply@notifiche.immobiliare.it OR idealista.it)", True)]
        assert gmail_query({"queries": 'FROM "a@b.it"||subject:x'}) == [('FROM "a@b.it"', False), ("subject:x", False)]

    def test_fingerprint_ignores_order_and_title(self):
        assert fingerprint(SCOUT) == fingerprint({**SCOUT, "title": "x", "senders": list(reversed(SCOUT["senders"]))})
        assert fingerprint(SCOUT) != fingerprint({**SCOUT, "senders": ["other.it"]})


@pytest.mark.unit
class TestDispatch:
    def test_each_module_gets_only_its_mail(self, d, hub):
        hub.mails = {"1": mail("1", "Idealista <nonrispondere@idealista.it>", "Nuove case"),
                     "2": mail("2", "PayPal <service@paypal.it>", "Ricevuta di pagamento"),
                     "3": mail("3", "friend@example.com", "ciao")}
        out = d.incoming([{k: m[k] for k in ("id", "from", "subject", "labels", "created_at")} for m in hub.mails.values()])
        assert out["ok"] and out["received"] == 3 and out["unmatched"] == 1
        assert set(hub.raw) == {"mail:real_estate:1", "mail:finance:2"}
        assert hub.raw["mail:finance:2"]["payload"]["body"] == "body 2"
        assert hub.raw["mail:finance:2"]["payload"]["subscription"] == "plutus:paypal"
        rings = {(s, p): b for s, p, b in hub.rings}
        assert rings[("scout", "api/scout/mail")]["reference_ids"] == ["mail:real_estate:1"]
        assert rings[("plutus", "api/finance/mail")]["count"] == 1
        assert d.list("plutus")[0]["delivered_total"] == 1

    def test_module_down_mail_kept_in_archive(self, d, hub):
        hub.mails = {"2": mail("2", "service@paypal.it", "Ricevuta")}
        hub.down.add("plutus")
        out = d.incoming([{"id": "2", "from": "service@paypal.it", "subject": "Ricevuta"}])
        assert out["ok"]                                    # stored: Hecate may advance its cursor
        assert "mail:finance:2" in hub.raw
        assert d.list("plutus")[0]["last_ring"] == "failed"
        assert d.log[0]["ring_ok"] is False

    def test_archive_down_asks_hecate_to_retry(self, d, hub):
        hub.mails = {"2": mail("2", "service@paypal.it", "Ricevuta")}
        hub.down.add("archive")
        out = d.incoming([{"id": "2", "from": "service@paypal.it", "subject": "Ricevuta"}])
        assert not out["ok"] and not hub.rings

    def test_same_mail_twice_is_stored_once(self, d, hub):
        hub.mails = {"2": mail("2", "service@paypal.it", "Ricevuta")}
        head = [{"id": "2", "from": "service@paypal.it", "subject": "Ricevuta"}]
        d.incoming(head)
        d.incoming(head)
        assert list(hub.raw) == ["mail:finance:2"]


@pytest.mark.unit
class TestSubscriptions:
    def test_register_is_idempotent_and_removes_dropped_keys(self, d, hub):
        assert d.register("scout", [SCOUT])["changed"] == 0
        d.register("scout", [{**SCOUT, "key": "other"}])
        assert [s["key"] for s in d.list("scout")] == ["other"]
        assert hub.store["scout:listings"]["deleted"] is True

    def test_survives_restart(self, d, hub):
        fresh = Dispatcher(hub)
        assert {s["id"] for s in fresh.list()} == {"scout:listings", "plutus:paypal"}

    def test_rule_needs_path_and_domain(self, d):
        with pytest.raises(ValueError):
            d.register("x", [{"key": "a"}])

    def test_backfill_delivers_recent_matching_mail(self, d, hub):
        hub.mails = {"7": mail("7", "PayPal <service@paypal.it>", "Ricevuta"),
                     "8": mail("8", "a@b.it", "no")}
        out = d.backfill("plutus:paypal", days=7)
        assert out["found"] == 1 and out["stored"] == 1
        assert "mail:finance:7" in hub.raw
        assert d.log[0]["source"] == "backfill"

    def test_new_rule_triggers_backfill(self, hub, monkeypatch):
        disp = Dispatcher(hub)
        started = []
        monkeypatch.setattr("dispatch.threading.Thread",
                            lambda target, args, **kw: type("T", (), {"start": lambda self: started.append(args)})())
        assert disp.register("plutus", [PLUTUS])["backfill"] == ["paypal"]
        assert disp.register("plutus", [{**PLUTUS, "title": "renamed"}])["backfill"] == []
        assert started == [("plutus:paypal",)]


@pytest.mark.api
class TestEndpoints:
    def test_incoming_503_when_not_stored(self, monkeypatch):
        from fastapi.testclient import TestClient
        import main
        hub = FakeHub()
        hub.down.add("archive")
        disp = Dispatcher(hub)
        disp.subs = {"plutus:paypal": {**PLUTUS, "owner": "plutus", "id": "plutus:paypal"}}
        disp.loaded = True
        monkeypatch.setattr(main, "dispatcher", disp)
        client = TestClient(main.app)
        r = client.post("/api/email/incoming", json={"messages": [{"id": "1", "from": "s@paypal.it", "subject": "x"}]})
        assert r.status_code == 503

    def test_manifest_has_email_page(self):
        from fastapi.testclient import TestClient
        import main
        r = TestClient(main.app).get("/api/ui/manifest")
        assert r.status_code == 200
        web = r.json()["clients"]["webui"]
        assert web["page"][0]["id"] == "email" and web["api_prefix"] == "/api/email/"
