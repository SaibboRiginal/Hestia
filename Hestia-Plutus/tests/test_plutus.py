"""Plutus: PayPal parser, transactions (sign, dedupe, learned rules), PayPal↔bank linking, budgets and alerts,
summaries, recurring payments, bank statements (text + generated PDF), mail processing, endpoints and manifest.

Service over a fake Archive store (same LWW + seq semantics as /api/finance-store). Synthetic data only: no real
receipts or statements in this public repo. Markers: unit, api
"""
import base64
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
for _p in (str(_ROOT), str(_ROOT.parent / "Hestia-Shared")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from app.core import catalog, paypal
from app.core.service import Invalid, Plutus
from app.core.statements import Statements, merchant_of, parse_rows
from app.core.store import Store, StoreUnavailable, parse_dt

pytestmark = pytest.mark.unit


class FakeArchive:
    """finance-store records + blobs + raw mail records (what Iris stored)."""

    def __init__(self):
        self.rows, self.seq, self.down = {}, 0, False
        self.blobs, self.mails, self.patched = {}, [], []

    def ok(self, service, method, path, *, body=None, query=None, timeout=8):
        if self.down:
            raise OSError("archive down")
        assert service == "archive", service
        if path == "api/finance-store/records":
            return self._records(method, body, query)
        if path == "api/blobs" and method == "POST":
            bid = f"b{len(self.blobs) + 1}"
            self.blobs[bid] = body["data_base64"]
            return {"blob_id": bid}
        if path.startswith("api/blobs/") and path.endswith("/base64"):
            return {"data_b64": self.blobs[path.split("/")[2]]}
        if path == "api/archive/finance/unevaluated":
            return [m for m in self.mails if m["id"] not in self.patched]
        if method == "PATCH" and path.startswith("api/archive/"):
            self.patched.append(int(path.rsplit("/", 1)[1]))
            return {"status": "ok"}
        raise AssertionError(f"unexpected {method} {path}")

    def _records(self, method, body, query):
        if method == "PUT":
            applied, stale = [], []
            for r in body["rows"]:
                key = (r["kind"], r["id"])
                old = self.rows.get(key)
                if old and parse_dt(old["updated_at"]) > parse_dt(r["updated_at"]):
                    stale.append(old)
                    continue
                self.seq += 1
                self.rows[key] = {**r, "seq": self.seq}
                applied.append({"kind": r["kind"], "id": r["id"], "seq": self.seq})
            return {"applied": applied, "stale": stale, "cursor": self.seq}
        since = int((query or {}).get("since_seq") or 0)
        rows = sorted((r for r in self.rows.values() if r["seq"] > since), key=lambda r: r["seq"])
        return {"rows": rows, "cursor": self.seq}


SETTINGS: dict = {}


def _cfg(key, default=None):
    return SETTINGS.get(key, default)


@pytest.fixture(autouse=True)
def _clean_settings():
    SETTINGS.clear()
    yield
    SETTINGS.clear()


@pytest.fixture
def pl():
    p = Plutus(Store(FakeArchive(), min_refresh_seconds=0), _cfg, tz_name="Europe/Rome")
    p.ensure_seed()
    return p


def _pdf(lines: list[str]) -> bytes:
    """A tiny valid PDF with one text line per row (enough for pypdf's text extraction)."""
    def esc(s):
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    ops = ["BT", "/F1 9 Tf", "40 800 Td", "12 TL"] + [f"({esc(line)}) Tj T*" for line in lines] + ["ET"]
    stream = "\n".join(ops).encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


# ── helpers / parsers ────────────────────────────────────────────────────────
def test_parse_amount_formats():
    assert catalog.parse_amount("1.234,56") == 1234.56
    assert catalog.parse_amount("1,234.56") == 1234.56
    assert catalog.parse_amount("€ 12,99") == 12.99
    assert catalog.parse_amount("-5") == -5.0
    assert catalog.parse_amount("−7,50 €") == -7.5
    assert catalog.parse_amount("1.234") == 1234.0
    assert catalog.parse_amount("niente") is None
    assert catalog.norm_merchant("PAYPAL *NETFLIX") == "netflix"


def test_paypal_parse_italian_payment():
    p = paypal.parse("Ricevuta del pagamento a Negozio Esempio",
                     "Hai inviato un pagamento di 23,50 € EUR a Negozio Esempio\nID transazione: 1AB23456CD789012E")
    assert p == {"kind": "payment", "amount": -23.5, "currency": "EUR", "merchant": "Negozio Esempio",
                 "txn_id": "1AB23456CD789012E"}


def test_paypal_parse_english_refund_received_and_noise():
    r = paypal.parse("You've got a refund from Example Shop", "Refund of $15.00 USD from Example Shop")
    assert r["kind"] == "refund" and r["amount"] == 15.0 and r["currency"] == "USD"
    got = paypal.parse("Hai ricevuto denaro", "Mario Rossi ti ha inviato 40,00 €")
    assert got["kind"] == "received" and got["amount"] == 40.0
    assert paypal.parse("Aggiornamento delle condizioni d'uso", "Abbiamo aggiornato le condizioni.") is None
    assert paypal.looks_like_money("Il tuo pagamento", "")


def test_statement_rows_and_merchant():
    text = "\n".join([
        "Lista movimenti", "Data operazione Data valuta Descrizione Importo",
        "02/10/2026 02/10/2026 PAGAMENTO POS ESSELUNGA MILANO -45,20",
        "03/10/2026 Bonifico ricevuto da Datore Esempio 1.500,00",
        "04/10/2026 PAYPAL *NETFLIX 12,99",
        "carta **** 1234",
        "Saldo finale 1.441,81"])
    rows = parse_rows(text)
    assert [r["amount"] for r in rows] == [-45.2, 1500.0, -12.99]
    assert rows[0]["date"] == "2026-10-02" and rows[2]["description"].endswith("carta **** 1234")
    assert merchant_of("PAGAMENTO POS ESSELUNGA MILANO 12/10") == "Esselunga Milano"


# ── transactions ─────────────────────────────────────────────────────────────
def test_manual_amount_is_expense_and_rules_categorize(pl):
    t = pl.add_tx({"amount": "12,50", "merchant": "Esselunga"})
    assert t["amount"] == -12.5 and t["category"] == "spesa" and t["status"] == "confirmed" and t["counted"]
    inc = pl.add_tx({"amount": 100, "type": "income", "merchant": "Rimborso amico"})
    assert inc["amount"] == 100 and inc["category"] == "entrate"
    with pytest.raises(Invalid):
        pl.add_tx({"amount": 0})


def test_dedupe_by_external_ref(pl):
    a = pl.add_tx({"amount": -9, "merchant": "X", "external_ref": "paypal:ABC"}, source="email")
    b = pl.add_tx({"amount": -9, "merchant": "X", "external_ref": "paypal:ABC"}, source="email")
    assert b["duplicate"] and b["id"] == a["id"] and len(pl.transactions()) == 1
    assert a["status"] == "to_review" and a["category"] == "altro"


def test_correction_learns_rule(pl):
    t = pl.add_tx({"amount": -30, "merchant": "Palestra Esempio"}, source="statement")
    assert t["status"] == "to_review"
    pl.update_tx(t["id"], {"category": "Salute"}, learn=True)
    again = pl.add_tx({"amount": -30, "merchant": "PALESTRA ESEMPIO"}, source="statement")
    assert again["category"] == "salute" and again["status"] == "confirmed"
    assert pl.get("tx", t["id"])["amount"] == -30


def test_paypal_bank_link_counts_once(pl):
    today = pl.today()
    pp = pl.add_tx({"amount": -12.99, "merchant": "Netflix", "account": "paypal", "external_ref": "paypal:N1",
                    "date": today.isoformat()}, source="email")
    bank = pl.add_tx({"amount": -12.99, "merchant": "PAYPAL *NETFLIX", "account": "hype",
                      "date": (today - timedelta(days=1)).isoformat()}, source="statement")
    bank = pl.get("tx", bank["id"])
    assert bank["linked_to"] == pp["id"]
    s = pl.summary()
    assert s["spent"] == 12.99 and s["linked"] == 1
    pl.delete_tx(pp["id"])                         # the bank row counts again
    assert not pl.get("tx", bank["id"])["linked_to"]


def test_transfer_not_counted(pl):
    pl.add_tx({"amount": -200, "category": "trasferimenti", "merchant": "Ricarica PayPal"})
    pl.add_tx({"amount": -20, "merchant": "Coop"})
    assert pl.summary()["spent"] == 20


def test_month_start_day(pl):
    SETTINGS["plutus.month_start_day"] = 27
    start, end = pl.month_range("2026-10-05")
    assert start == date(2026, 9, 27) and end == date(2026, 10, 27)
    assert pl.month_label(start) == "ottobre 2026"


# ── budgets / alerts / review / context ──────────────────────────────────────
def test_budgets_and_alerts(pl):
    pl.set_budget("spesa", 100)
    pl.set_budget("total", "500")
    pl.add_tx({"amount": 85, "merchant": "Lidl"})
    s = pl.summary()
    spesa = next(c for c in s["categories"] if c["id"] == "spesa")
    assert spesa["pct"] == 85 and s["budget"] == 500 and s["left"] == 415
    alerts = pl.budget_alerts()
    assert [a["category"] for a in alerts] == ["spesa"] and alerts[0]["level"] == 80
    pl.add_tx({"amount": 20, "merchant": "Lidl"})
    assert pl.budget_alerts()[0]["level"] == 100
    pl.set_budget("spesa", 0)
    assert "spesa" not in pl.budgets()
    with pytest.raises(Invalid):
        pl.set_budget("inesistente", 10)


def test_context_and_review(pl):
    pl.add_tx({"amount": 40, "merchant": "Pizzeria Esempio"})
    text = pl.context_text()
    assert text.startswith("Spese ") and "Ristoranti" in text
    r = pl.review()
    assert set(r) >= {"month", "spent", "previous_spent", "biggest_changes"}


# ── recurring ────────────────────────────────────────────────────────────────
def test_recurring_detection_and_dismiss(pl):
    d0 = pl.today() - timedelta(days=90)
    for i in range(4):
        pl.add_tx({"amount": -9.99, "merchant": "Spotify", "date": (d0 + timedelta(days=30 * i)).isoformat()})
    found = pl.detect_recurring()
    assert len(found) == 1 and found[0]["period"] == "monthly" and found[0]["status"] == "suggested"
    pl.set_recurring(found[0]["id"], "dismissed")
    assert pl.recurring() == []
    pl.detect_recurring()                           # a dismissed one is not proposed again
    assert pl.recurring() == []


# ── mails ────────────────────────────────────────────────────────────────────
def _mail(ref, subject, body, ts="2026-10-10T09:00:00"):
    return {"id": 1, "payload": {"reference_id": ref, "title": subject, "body": body, "timestamp": ts,
                                 "gmail_id": ref.rsplit(":", 1)[-1]}}


def test_process_mail_idempotent(pl):
    m = _mail("mail:finance:g1", "Ricevuta del pagamento a Shop Esempio",
              "Hai inviato un pagamento di 19,90 € a Shop Esempio\nID transazione: 9ZZ11122233344455")
    out = pl.process_mail(m)
    assert out["status"] == "added" and out["amount"] == -19.9
    tx = pl.get("tx", out["tx_id"])
    assert tx["account"] == "paypal" and tx["external_ref"] == "paypal:9ZZ11122233344455" and tx["date"] == "2026-10-10"
    assert pl.process_mail(m)["status"] == "seen"
    assert pl.process_mail(_mail("mail:finance:g2", "Novità", "Scopri le offerte"))["status"] == "ignored"


def test_process_mail_oracle_fallback(pl):
    pl.llm = lambda prompt: '{"kind": "payment", "amount": 7.5, "currency": "EUR", "merchant": "Bar Esempio", "txn_id": ""}'
    out = pl.process_mail(_mail("mail:finance:g3", "Il tuo pagamento", "Formato che il parser non conosce"))
    assert out["status"] == "added" and out["how"] == "oracle" and out["amount"] == -7.5
    assert pl.get("tx", out["tx_id"])["external_ref"] == "mail:g3"


# ── statements ───────────────────────────────────────────────────────────────
_STMT = ["Lista movimenti",
         "05/10/2026 PAGAMENTO POS CONAD CITTA -32,40",
         "06/10/2026 PAYPAL *SHOP ESEMPIO -19,90",
         "07/10/2026 Bonifico ricevuto da Esempio 250,00",
         "08/10/2026 BAR CENTRALE -1,20",
         "08/10/2026 BAR CENTRALE -1,20"]


def test_statement_pdf_preview_commit_undo(pl):
    st = Statements(pl, pl.store.hub)
    pl.add_tx({"amount": -19.9, "merchant": "Shop Esempio", "account": "paypal", "date": "2026-10-05",
               "external_ref": "paypal:S1"}, source="email")
    pdf = base64.b64encode(_pdf(_STMT)).decode()
    v = st.preview(data_b64=pdf, name="ottobre.pdf")
    assert v["how"] == "parser" and v["counts"] == {"new": 4, "link": 1} and v["blob_id"] == "b1"
    assert v["period"] == ["2026-10-05", "2026-10-08"] and v["total_new_spent"] == 34.8
    done = st.commit(v["id"])
    assert done["added"] == 5 and done["linked"] == 1 and done["status"] == "committed"
    assert len(pl.transactions(import_id=v["id"])) == 5
    again = st.preview(data_b64=pdf)                # same PDF twice: nothing new
    assert again["counts"] == {"duplicate": 5}
    assert st.undo(v["id"])["removed"] == 5 and pl.transactions(import_id=v["id"]) == []


def test_statement_from_blob_and_errors(pl):
    st = Statements(pl, pl.store.hub)
    pl.store.hub.blobs["chat1"] = base64.b64encode(_pdf(_STMT[:2])).decode()
    v = st.preview(blob_id="chat1", source="chat")
    assert v["blob_id"] == "chat1" and v["counts"] == {"new": 1}
    with pytest.raises(Invalid):
        st.preview(data_b64=base64.b64encode(b"not a pdf").decode())
    with pytest.raises(Invalid):
        st.preview(text="nessun movimento qui")


def test_covers_month(pl):
    st = Statements(pl, None)
    v = st.preview(text="\n".join(f"{d:02d}/09/2026 COOP -{d},00" for d in (2, 15, 29)))
    st.commit(v["id"])
    assert st.covers_month(date(2026, 9, 1), date(2026, 10, 1))
    assert not st.covers_month(date(2026, 8, 1), date(2026, 9, 1))


def test_store_unavailable(pl):
    pl.store.hub.down = True
    with pytest.raises(StoreUnavailable):
        pl.add_tx({"amount": 3, "merchant": "x"})


# ── API (FastAPI app over the same fake Archive) ─────────────────────────────
@pytest.fixture
def api(monkeypatch):
    from fastapi.testclient import TestClient

    from app import main
    fake = FakeArchive()
    store = Store(fake, min_refresh_seconds=0)
    p = Plutus(store, _cfg, tz_name="Europe/Rome")
    p.ensure_seed()
    monkeypatch.setattr(main, "hub", fake)
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "plutus", p)
    monkeypatch.setattr(main.coach, "p", p)
    monkeypatch.setattr(main, "statements", Statements(p, fake))
    monkeypatch.setattr(main, "_llm", lambda prompt: None)
    monkeypatch.setattr(main, "signals", _QuietSignals())
    return TestClient(main.app), main, fake


class _QuietSignals:
    """Stands in for the Signals publisher in API tests: counts ``changed()``, never touches the network."""

    def __init__(self):
        self.changes = 0

    def changed(self):
        self.changes += 1

    def run(self):
        return {"written": 0, "retracted": 0}


@pytest.mark.api
def test_api_quick_expense_and_undo(api):
    c, *_ = api
    r = c.post("/api/finance/quick/expense/ristoranti", json={"amount": "3,20", "note": "caffè"})
    assert r.status_code == 200 and r.json()["amount"] == -3.2 and "Ristoranti" in r.json()["label"]
    assert c.get("/api/finance/summary").json()["spent"] == 3.2
    assert c.delete("/api/finance/quick/expense/ristoranti").json()["deleted"]
    assert c.delete("/api/finance/quick/expense/ristoranti").status_code == 404


@pytest.mark.api
def test_api_crud_errors_and_tool(api):
    c, *_ = api
    assert c.post("/api/finance/transactions", json={"amount": 0}).status_code == 422
    assert c.get("/api/finance/transactions/tx_nope").status_code == 404
    r = c.post("/api/finance/tools/add", json={"amount": "8.5", "merchant": "Farmacia Esempio"})
    assert r.status_code == 200 and r.json()["saved"]
    items = c.get("/api/finance/transactions", params={"category": "salute"}).json()["items"]
    assert len(items) == 1 and items[0]["source"] == "chat"
    assert c.put(f"/api/finance/budgets/salute", json={"amount": 50}).json() == {"category": "salute", "amount": 50.0}


@pytest.mark.api
def test_api_mail_pending_marks_evaluated(api):
    c, main, fake = api
    fake.mails = [{"id": 41, "payload": {"reference_id": "mail:finance:g9", "title": "Ricevuta del pagamento a Y",
                                         "body": "Hai inviato un pagamento di 5,00 € a Y", "timestamp": "2026-10-11"}}]
    out = main.process_pending_mail()
    assert out == {"status": "ok", "processed": 1, "added": 1} and fake.patched == [41]
    assert main.process_pending_mail()["processed"] == 0


@pytest.mark.api
def test_api_import_upload_flow(api):
    c, *_ = api
    pdf = base64.b64encode(_pdf(_STMT)).decode()
    v = c.post("/api/finance/imports", json={"name": "m.pdf", "mime": "application/pdf", "data_b64": pdf}).json()
    assert v["status"] == "preview"
    assert c.post(f"/api/finance/imports/{v['id']}/commit").json()["added"] == 5
    assert c.get("/api/finance/imports").json()["items"][0]["status"] == "committed"


@pytest.mark.api
def test_manifest_pages_widgets_quick_action(api):
    c, *_ = api
    m = c.get("/api/ui/manifest").json()
    web = m["clients"]["webui"] if "clients" in m else m
    text = str(web)
    for el in ("plutus-overview", "plutus-transactions", "plutus-import", "plutus-month-widget", "Spesa veloce"):
        assert el in text


@pytest.mark.api
def test_api_chat_attachment_handoff(api):
    c, main, fake = api
    fake.blobs["chatblob"] = base64.b64encode(_pdf(_STMT)).decode()
    out = c.post("/api/finance/attachments", json={"blob_id": "chatblob", "filename": "ottobre.pdf"}).json()
    assert out["handled"] and "Li registro?" in out["text"] and out["import_id"] in out["text"]
    assert c.post("/api/finance/tools/import_statement",
                  json={"import_id": out["import_id"], "commit": "true"}).json()["committed"]
    again = c.post("/api/finance/attachments", json={"blob_id": "chatblob"}).json()
    assert again["handled"] and "ci sono già tutti" in again["text"]
    assert c.post("/api/finance/attachments", json={"blob_id": "missing"}).json()["handled"] is False
    caps = main._registration()["capabilities"]
    assert caps["attachment_handlers"][0]["path"] == "/api/finance/attachments"


# ── daily recap piece (docs/work/2026-10-20-recap-giornaliero) ─────────────
def test_recap_spent_today_by_category_and_budget(pl):
    pl.add_tx({"amount": "12,50", "merchant": "Esselunga", "category": "spesa"})
    pl.add_tx({"amount": 30, "merchant": "Esselunga", "category": "spesa"})
    pl.set_budget("total", "500")
    today = pl.today()
    facts = pl.recap(today, today + timedelta(days=1))
    assert facts["done"][0]["text"].startswith("Spesi 42,50 ")
    assert "Spesa" in facts["done"][0]["text"] and "su 500" in facts["note"]


def test_recap_quiet_day(pl):
    today = pl.today()
    assert pl.recap(today, today + timedelta(days=1)) == {"done": [], "next": [], "note": ""}


@pytest.mark.api
def test_api_recap_piece(api):
    c, *_ = api
    c.post("/api/finance/quick/expense/ristoranti", json={"amount": "3,20"})
    body = c.get("/api/module/recap").json()
    assert body["module"] == "plutus" and body["title"] == "Spese" and "3,20" in body["done"][0]["text"]


def test_mirror_reloads_when_archive_epoch_changes():
    """Backup rollback replaces Archive's database (seq goes back): the mirror must drop what it had."""
    class Epochs:
        def __init__(self):
            self.epoch, self.rows = "e1", [{"kind": "tx", "id": "a", "data": {}, "updated_at": "2026-10-01T00:00:00+00:00",
                                            "deleted": False, "seq": 5}]

        def ok(self, service, method, path, *, body=None, query=None, timeout=8):
            since = int((query or {}).get("since_seq") or 0)
            return {"rows": [r for r in self.rows if r["seq"] > since], "cursor": 5, "epoch": self.epoch}

    fake = Epochs()
    store = Store(fake, min_refresh_seconds=0)
    assert store.refresh(force=True) and store.get("tx", "a")
    fake.epoch = "e2"                                      # rolled back to a day without "a", seq restarted
    fake.rows = [{"kind": "tx", "id": "b", "data": {}, "updated_at": "2026-09-01T00:00:00+00:00", "deleted": False,
                  "seq": 2}]
    assert store.refresh(force=True)
    assert store.get("tx", "a") is None and store.get("tx", "b") and store.cursor == 2


# ── reflection signals (hestia_common.signals_client) ────────────────────────
def _at(pl, day):
    pl.today = lambda: day                       # fixed «today» (month pace and ISO weeks are date-driven)
    return day


def test_signals_budget_week_subscription_review(pl):
    today = _at(pl, date(2026, 10, 14))           # Wednesday, day 14 of 31
    for i in range(1, 9):                          # 8 previous weeks: 50 € each
        pl.add_tx({"amount": 50, "merchant": "Lidl", "date": (today - timedelta(weeks=i)).isoformat()})
    pl.add_tx({"amount": 200, "merchant": "Pizzeria Esempio", "date": today.isoformat()})
    pl.set_budget("ristoranti", 150)               # over → alta
    pl.set_budget("spesa", 100)                    # 50 € by day 14 → pace ~111 > 100 → attenzione
    for i in range(3):                             # monthly subscription, first seen today
        pl.add_tx({"amount": 9.99, "merchant": "Spotify", "date": (today - timedelta(days=60 - 30 * i)).isoformat()})
    for i in range(5):
        pl.add_tx({"amount": -3, "merchant": f"Boh {i}", "date": today.isoformat(), "status": "to_review"})
    sigs, mets = pl.signals()
    by = {s["key"]: s for s in sigs}
    assert by["budget_pace:ristoranti"]["severity"] == "alta" and by["budget_pace:ristoranti"]["page"] == "budget"
    assert by["budget_pace:spesa"]["severity"] == "attenzione"
    assert by["unusual_week"]["severity"] == "attenzione" and by["unusual_week"]["metrics"]["median_8w"] == 50
    assert any(k.startswith("new_subscription:rec_") for k in by)
    assert by["to_review"]["metrics"]["count"] == 5
    assert all("Plutus" not in s["text"] for s in sigs)
    spent = [m for m in mets if m["name"] == "finance.spent"]
    assert len(spent) == 12 and spent[-1]["week"] == "2026-W42" and spent[-1]["label"] == "Spesa settimanale"
    assert spent[-1]["value"] == round(200 + 9.99 + 5 * 3, 4)
    names = {m["name"] for m in mets}
    assert "finance.spent.ristoranti" in names and len(names) <= 5
    assert next(m for m in mets if m["name"] == "finance.spent.ristoranti")["label"] == "Ristoranti e bar"
    assert all(m["name"] != "finance.spent.entrate" for m in mets)          # expenses only


def test_signals_quiet_when_nothing_to_say(pl):
    _at(pl, date(2026, 10, 14))
    pl.add_tx({"amount": 10, "merchant": "Lidl", "date": "2026-10-13"})
    pl.add_tx({"amount": 1000, "merchant": "Stipendio", "type": "income", "date": "2026-10-13"})
    sigs, mets = pl.signals()
    assert sigs == []                              # no budget, no history for a median, nothing to review
    assert len([m for m in mets if m["name"] == "finance.spent"]) == 12
    assert [m["value"] for m in mets if m["name"] == "finance.spent"][-1] == 10


def test_topic_details(pl):
    today = _at(pl, date(2026, 10, 14))
    for i in range(1, 9):
        pl.add_tx({"amount": 50, "merchant": "Lidl", "date": (today - timedelta(weeks=i)).isoformat()})
    pl.add_tx({"amount": 200, "merchant": "Pizzeria Esempio", "date": today.isoformat()})
    pl.set_budget("ristoranti", 150)
    pl.set_budget("total", 300)
    t = pl.topic_text("budget_pace:ristoranti")
    assert "Ristoranti" in t and "200/150" in t and "Pizzeria Esempio" in t
    assert "Budget mese" in pl.topic_text("budget_pace:month")
    w = pl.topic_text("unusual_week")
    assert "2026-W42" in w and "mediana" in w and "Pizzeria Esempio" in w
    assert pl.topic_text("nope") is None and len(pl.topic_text("unusual_week", budget=40)) <= 40


@pytest.mark.api
def test_api_context_topic_and_signals_run(api, monkeypatch):
    c, main, fake = api
    c.post("/api/finance/transactions", json={"amount": 120, "merchant": "Pizzeria Esempio"})
    assert main.signals.changes == 1               # a write asks for a re-evaluation
    c.put("/api/finance/budgets/ristoranti", json={"amount": 100})
    normal = c.get("/api/module/context").json()
    assert set(normal) == {"module", "domain", "updated_at", "text"} and normal["text"].startswith("Spese ")
    detail = c.get("/api/module/context", params={"topic": "budget_pace:ristoranti", "budget": 300}).json()
    assert "120/100" in detail["text"] and detail["domain"] == "finance"
    assert c.get("/api/module/context", params={"topic": "boh"}).json()["text"] == normal["text"]
    # /signals/run → evaluate + sync through the (mocked) signals-store transport
    from hestia_common.signals_client import Signals
    calls = []

    def fake_call(self, method, path, *, body=None, query=None, timeout=10):
        calls.append((method, path, body))
        return {"rows": []} if method == "GET" else {"applied": []}
    monkeypatch.setattr(Signals, "_call", fake_call)
    monkeypatch.setattr(main, "signals", Signals("plutus", "finance", evaluate=main.plutus.signals))
    out = c.post("/api/finance/signals/run").json()
    assert out["signals"] >= 1 and out["metrics"] >= 12 and out["written"] == out["signals"] + out["metrics"]
    put = [b for m, _, b in calls if m == "PUT"][0]
    assert any(r["id"] == "plutus:budget_pace:ristoranti" for r in put["rows"])
    job = next(r for r in main._agenda_rules() if r["key"] == "plutus.signals")
    assert "/api/finance/signals/run" in str(job)


# ── coach of the weekly plan (SPEC 2026-10-20-coach-di-ogni-tipo §7.3) ───────
def test_coach_budget_targets_and_review_block(pl):
    from hestia_common.coach import validate_need

    from app.core.coach import REVIEW_NEED, PlutusCoach
    coach = PlutusCoach(pl)
    start = pl.today()
    assert coach.needs(start, start + timedelta(days=7))["needs"] == []       # no budget, nothing to review
    pl.set_budget("spesa", 100)
    pl.add_tx({"amount": 40, "merchant": "Lidl"})
    needs = coach.needs(start, start + timedelta(days=7))["needs"]
    t = next(n for n in needs if n["id"] == "finance.budget.spesa")
    assert t["kind"] == "target" and t["progress"] == 0.4 and 0 < t["value"] <= 60 and validate_need(t)
    SETTINGS["plutus.coach.review_threshold"] = 2
    for i in range(2):
        pl.add_tx({"amount": 5, "merchant": f"Sconosciuto {i}", "external_ref": f"r{i}"}, source="statement")
    assert coach.check() == "changed" and coach.check() is None
    block = next(n for n in coach.needs(start, start + timedelta(days=7))["needs"] if n["id"] == REVIEW_NEED)
    assert block["kind"] == "block" and block["minutes"] == 15 and validate_need(block)
    tx = next(t for t in pl.transactions() if t["status"] == "to_review")
    pl.update_tx(tx["id"], {"category": "spesa"})
    assert coach.check() == "done"
    r = coach.review(*pl.month_range())
    assert r["done"] == 1 and r["missed"] == 0 and r["adherence"] == 1.0


@pytest.mark.api
def test_api_coach_routes(api):
    c, *_ = api
    body = c.get("/api/coach/needs").json()
    assert body["module"] == "plutus" and body["domain"] == "finance" and body["refused"] == []
    assert c.get("/api/coach/review").status_code == 200
