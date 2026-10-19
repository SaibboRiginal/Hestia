"""Bank statements (Hype monthly PDF and similar) → preview → commit → undo.

Hype sends no summary by email; its app exports the movement list as PDF. Plutus reads the text (``pypdf``, no model),
finds the movement rows with a layout-tolerant parser (a date, a description, an amount), and asks Oracle only when no
row is recognised. Every row gets a stable ``external_ref`` (re-uploading the same PDF adds nothing). The user sees a
preview (new / already there / linked to a PayPal payment) and confirms; an import can be undone.
No real statements in the repo: tests use synthetic text and a generated PDF.
"""
from __future__ import annotations

import base64
import hashlib
import io
import logging
import re
from collections import Counter
from datetime import date

from . import catalog
from .service import Invalid, NotFound, Plutus, _d, _id, _json_from
from .store import now_iso

logger = logging.getLogger("hestia_plutus.statements")

_MONTHS = {"gen": 1, "feb": 2, "mar": 3, "apr": 4, "mag": 5, "giu": 6, "lug": 7, "ago": 8, "set": 9, "ott": 10,
           "nov": 11, "dic": 12, "jan": 1, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "dec": 12}
_DATE_RE = re.compile(r"^\s*(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2}\s+[a-zA-Z]{3,9}\.?\s+\d{4})\b")
_AMOUNT_END_RE = re.compile(r"([-+−]?\s*€?\s*\d{1,3}(?:[.\s]\d{3})*,\d{2}|[-+−]?\s*€?\s*\d+[.,]\d{2})\s*(?:€|EUR)?\s*$")
_INCOME_WORDS = re.compile(r"accredit|bonifico (?:ricevuto|in entrata|da)|ricarica|rimborso|stipendio|entrata|"
                           r"ricevut|cashback|interessi", re.I)
_SKIP_RE = re.compile(r"saldo (?:iniziale|finale|disponibile|contabile)|totale|pagina \d|estratto conto|"
                      r"lista movimenti|data\s+(?:operazione|valuta)|^\s*data\s", re.I)


def _date(text: str) -> date | None:
    text = text.strip()
    m = re.match(r"(\d{1,2})\s+([a-zA-Z]{3,9})\.?\s+(\d{4})", text)
    if m:
        month = _MONTHS.get(m.group(2)[:3].lower())
        return date(int(m.group(3)), month, int(m.group(1))) if month else None
    return _d(text)


def pdf_text(data: bytes) -> str:
    """Text of every page (pypdf). Raises Invalid for something that is not a readable PDF."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as exc:
        raise Invalid(f"PDF non leggibile: {exc}") from exc


def parse_rows(text: str) -> list[dict]:
    """Movement rows ``{date, description, amount, sign_guessed}`` from statement text. A line with a date at the
    start and an amount at the end is a row; lines in between continue the previous description."""
    rows: list[dict] = []
    for raw in (text or "").splitlines():
        line = raw.replace(" ", " ").strip()
        if not line or _SKIP_RE.search(line):
            continue
        dm = _DATE_RE.match(line)
        am = _AMOUNT_END_RE.search(line)
        if dm and am:
            when = _date(dm.group(1))
            amount = catalog.parse_amount(am.group(1))
            if not when or amount is None or amount == 0:
                continue
            middle = line[dm.end():am.start()].strip()
            # a second date (value date) right after the first one is not part of the description
            middle = _DATE_RE.sub("", middle, count=1).strip(" -|·")
            explicit = bool(re.match(r"\s*[-+−]", am.group(1)))
            rows.append({"date": when.isoformat(), "description": re.sub(r"\s{2,}", " ", middle)[:200],
                         "amount": amount, "sign_guessed": not explicit})
        elif rows and not dm and len(line) < 120 and not _AMOUNT_END_RE.search(line):
            rows[-1]["description"] = f"{rows[-1]['description']} {line}".strip()[:200]
    for r in rows:
        if r["sign_guessed"]:
            r["amount"] = abs(r["amount"]) if _INCOME_WORDS.search(r["description"]) else -abs(r["amount"])
    return rows


def merchant_of(description: str) -> str:
    """Readable merchant from a bank line («PAGAMENTO POS ESSELUNGA MILANO 12/10» → «Esselunga Milano»)."""
    d = re.sub(r"^(pagamento|pag\.?|acquisto|addebito)\s+(pos|carta|online|con carta|contactless)?\s*", "",
               description.strip(), flags=re.I)
    d = re.sub(r"\b(carta|card)\s*\*+\s*\d+|\b\d{2}[/.]\d{2}(?:[/.]\d{2,4})?\b|\bore\s+\d{1,2}[:.]\d{2}\b", "", d,
               flags=re.I)
    d = re.sub(r"\s{2,}", " ", d).strip(" -*")
    return d.title()[:80] if d.isupper() else d[:80]


def _row_refs(account: str, rows: list[dict]) -> list[str]:
    """Stable ids: same date, amount and text twice in one statement (two coffees) stay two rows."""
    seen: Counter = Counter()
    refs = []
    for r in rows:
        base = f"{account}|{r['date']}|{r['amount']:.2f}|{catalog.slug(r['description'])[:60]}"
        seen[base] += 1
        refs.append("stmt:" + hashlib.sha1(f"{base}|{seen[base]}".encode()).hexdigest()[:20])
    return refs


class Statements:
    def __init__(self, plutus: Plutus, hub=None):
        self.p = plutus
        self.hub = hub

    def _llm_rows(self, text: str) -> list[dict]:
        if not self.p.llm:
            return []
        out: list[dict] = []
        chunk = 6000
        for i in range(0, min(len(text), 60000), chunk):
            prompt = ("Estratto conto bancario. Elenca i movimenti. SOLO JSON [{\"date\": \"YYYY-MM-DD\", "
                      "\"description\": testo, \"amount\": numero con segno (uscite negative)}]. Niente saldi o totali.\n"
                      + text[i:i + chunk])
            data = _json_from(self.p.llm(prompt))
            for r in data if isinstance(data, list) else []:
                when, amount = _d(r.get("date")), catalog.parse_amount(r.get("amount"))
                if when and amount:
                    out.append({"date": when.isoformat(), "description": str(r.get("description") or "")[:200],
                                "amount": amount, "sign_guessed": False})
        return out

    # ── preview ──────────────────────────────────────────────────────────────
    def preview(self, *, data_b64: str = "", text: str = "", name: str = "", account: str = "hype",
                blob_id: str = "", source: str = "webui") -> dict:
        raw = b""
        if data_b64:
            try:
                raw = base64.b64decode(data_b64)
            except Exception as exc:
                raise Invalid(f"file non valido: {exc}") from exc
        elif blob_id:
            raw = self._blob(blob_id)
        if raw:
            if not raw[:5].startswith(b"%PDF"):
                raise Invalid("serve il PDF dei movimenti (lista movimenti esportata dall'app)")
            text = pdf_text(raw)
        if not text.strip():
            raise Invalid("nessun testo nel file (PDF scansionato?)")
        rows, how = parse_rows(text), "parser"
        if not rows:
            rows, how = self._llm_rows(text), "oracle"
        if not rows:
            raise Invalid("non ho trovato movimenti in questo file")
        account = self.p.resolve_account(account or "hype")
        refs = _row_refs(account, rows)
        existing = {t.get("external_ref") for t in self.p._tx_rows()}
        paypal_rows = [t for t in self.p._tx_rows() if t.get("account") == "paypal"]
        out_rows = []
        for r, ref in zip(rows, refs):
            merchant = merchant_of(r["description"])
            state = "duplicate" if ref in existing else "new"
            if state == "new" and "paypal" in r["description"].lower():
                if any(abs(abs(p["amount"]) - abs(r["amount"])) <= 0.01 and abs((_d(p["date"]) - _d(r["date"])).days) <= 3
                       for p in paypal_rows):
                    state = "link"
            out_rows.append({**r, "merchant": merchant, "external_ref": ref, "state": state,
                             "category": self.p.categorize(merchant, r["description"])})
        dates = sorted(r["date"] for r in out_rows)
        iid = _id("imp")
        if raw and self.hub is not None and not blob_id:
            blob_id = self._save_blob(raw, name)
        data = {"name": name or "estratto conto", "account": account, "status": "preview", "how": how,
                "source": source, "blob_id": blob_id or None, "period": [dates[0], dates[-1]],
                "rows": out_rows, "counts": dict(Counter(r["state"] for r in out_rows)), "created_at": now_iso()}
        self.p.store.upsert("import", iid, data)
        logger.info("event=plutus_statement_preview import=%s rows=%d how=%s", iid, len(out_rows), how)
        return self.view(iid)

    def view(self, iid: str) -> dict:
        imp = self.p.get("import", iid)
        rows = imp.get("rows") or []
        spent = round(-sum(r["amount"] for r in rows if r["amount"] < 0 and r["state"] == "new"), 2)
        return {**imp, "total_new_spent": spent, "currency": self.p.currency()}

    def imports(self) -> list[dict]:
        self.p.store.refresh()
        items = [{k: v for k, v in i.items() if k != "rows"} for i in self.p.store.items("import")]
        return sorted(items, key=lambda i: i.get("created_at") or "", reverse=True)

    # ── commit / undo ────────────────────────────────────────────────────────
    def commit(self, iid: str) -> dict:
        imp = self.p.get("import", iid)
        if imp.get("status") == "committed":
            return self.view(iid)
        rows = [r for r in imp.get("rows") or [] if r["state"] != "duplicate"]
        unknown = sorted({r["merchant"] for r in rows if not r.get("category")})
        guessed = self.p.guess_categories(unknown)
        added = 0
        for r in rows:
            cat = r.get("category") or guessed.get(r["merchant"])
            out = self.p.add_tx({"date": r["date"], "amount": r["amount"], "merchant": r["merchant"],
                                 "description": r["description"], "account": imp["account"], "category": cat,
                                 "external_ref": r["external_ref"], "import_id": iid,
                                 "status": "confirmed" if cat else "to_review"}, source="statement", link=False)
            added += 0 if out.get("duplicate") else 1
        linked = self.p.link_pass()
        self.p.detect_recurring()
        data = {**{k: v for k, v in imp.items() if k != "id"}, "status": "committed", "committed_at": now_iso(),
                "added": added, "linked": linked}
        self.p.store.upsert("import", iid, data)
        logger.info("event=plutus_statement_committed import=%s added=%d linked=%d", iid, added, linked)
        return self.view(iid)

    def undo(self, iid: str) -> dict:
        imp = self.p.get("import", iid)
        removed = 0
        for t in self.p._tx_rows():
            if t.get("import_id") == iid:
                self.p.store.delete("tx", t["id"])
                removed += 1
        self.p.store.upsert("import", iid, {**{k: v for k, v in imp.items() if k != "id"}, "status": "undone",
                                            "undone_at": now_iso(), "removed": removed})
        return {"id": iid, "status": "undone", "removed": removed}

    def covers_month(self, start: date, end: date, account: str = "hype") -> bool:
        """Is there a committed import of ``account`` reaching the last days of [start, end)?"""
        last_days = date.fromordinal(end.toordinal() - 5).isoformat()
        first_days = date.fromordinal(start.toordinal() + 5).isoformat()
        return any(i.get("account") == account and i.get("status") == "committed" and i.get("period")
                   and i["period"][1] >= last_days and i["period"][0] <= first_days for i in self.imports())

    # ── blobs (Archive) ──────────────────────────────────────────────────────
    def _save_blob(self, raw: bytes, name: str) -> str | None:
        try:
            meta = self.hub.ok("archive", "POST", "api/blobs", body={
                "owner_module": "plutus", "content_type": "application/pdf",
                "data_base64": base64.b64encode(raw).decode(), "meta": {"name": name[:120], "kind": "statement"}},
                timeout=20) or {}
            return meta.get("blob_id")
        except Exception as exc:
            logger.warning("[🔄] event=plutus_blob_save_failed error=%s fallback=no_copy", exc)
            return None

    def _blob(self, blob_id: str) -> bytes:
        if self.hub is None:
            raise NotFound("archivio non configurato")
        try:
            data = self.hub.ok("archive", "GET", f"api/blobs/{blob_id}/base64", timeout=20) or {}
            return base64.b64decode(data.get("data_b64") or "")
        except Exception as exc:
            raise NotFound(f"file '{blob_id}' non trovato: {exc}") from exc

