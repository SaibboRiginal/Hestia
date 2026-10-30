"""Training dataset, phase D2 «Correggi» (docs/work/2026-10-30-dataset-allenamento §3.3).

At night (agenda job ``metis.dataset.review``) a stronger model — the *teacher*, Oracle use case
``metis.dataset.review`` (Marko 2026-10-30: a cloud model, with his personal data masked) — re-reads the saved turns
with their signals and Hestia's rules and says what the answer should have been:

- ``keep``  — good as it is;
- ``fix``   — corrected final answer and/or tool calls to drop (a duplicate write, a write on a question). It may
  never invent the result of a tool that was not run: a fix that needs another tool goes to the owner;
- ``drop``  — useless for training (broken turn, nothing to learn).

**Masking** before anything leaves Hestia: names of the people in Persone (Hera), e-mail addresses, phone numbers,
IBAN, street addresses become ``<PERSONA_1>``, ``<EMAIL_1>``…; the map stays in this process and the corrected text
gets the real values back. A turn whose masking fails is not sent.

A verdict with confidence ≥ ``metis.review.auto_accept`` and no doubt is accepted; the others wait in the list
**«Da rivedere»** (WebUI Miglioramento, Telegram ``metis_rivedi``): Accetta / Scarta / Correggi with your own text.
Your choice always wins. Rows in Archive ``dataset-store``, kind ``review`` (id = trace_id, parent_id = session,
ref_id = status ``accepted | pending | rejected | edited``) and one kind ``state`` row (where the last run stopped).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from hestia_common.module_kit import Invalid, now_iso

from .traces import STORE

logger = logging.getLogger("hestia_metis.review")

USE_CASE = "metis.dataset.review"
STATUSES = ("accepted", "pending", "rejected", "edited")
VERDICTS = ("keep", "fix", "drop")
MIN_AGE = timedelta(minutes=30)      # the next turns must have had the time to signal this one

RULES = """REGOLE HESTIA (assistente personale di un solo utente, italiano):
R1 breve, diretto, italiano; niente saluti a ogni risposta.
R2 mai dire «fatto/ho registrato/ho salvato» senza uno strumento riuscito in questo turno; mai promettere «riproverò».
R3 un fatto si salva una volta sola: una persona (nome, parente, compleanno) va in Persone, non anche in memoria;
   promemoria/compleanni/routine non in memoria.
R4 una domanda o un consiglio («mi consigli…», «cosa mi metto») non è una scrittura: nessuno strumento che scrive.
R5 usa il contesto e i risultati degli strumenti; non inventare dati; se manca un dato dillo o chiedi.
R6 non ripetere uguale uno strumento fallito; dì che non è riuscito.
R7 se esiste lo strumento giusto usalo invece di rispondere a memoria; stato di Hestia → strumenti di sistema.
R8 rispetta le richieste esplicite dell'utente (formato, lunghezza, lingua)."""

PROMPT = """Sei il revisore del dataset di allenamento di Hestia. Giudica UN turno.
{rules}

SEGNALI del turno (voti e reazioni dell'utente): {signals}

TURNO
utente: {user}
strumenti chiamati (indice: nome, argomenti, ok, risultato):
{steps}
risposta: {answer}

CONTESTO che il modello aveva (istruzioni e cronologia, tagliati):
{context}

Rispondi SOLO JSON:
{{"verdict":"keep|fix|drop","confidence":0.0-1.0,"answer":"risposta corretta (solo se fix, altrimenti vuoto)",
"remove_steps":[indici degli strumenti sbagliati da togliere],"reasons":["R2", ...],"needs_owner":false}}
Vincoli: non inventare risultati di strumenti non chiamati; se la correzione giusta richiede un altro strumento di
scrittura metti needs_owner=true. I segnaposto <PERSONA_1>, <EMAIL_1>… restano identici."""


# ── masking ─────────────────────────────────────────────────────────────────
_PATTERNS = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}(?:\s?[A-Z0-9]{1,3})?\b")),
    ("TEL", re.compile(r"(?<![\w])(?:\+\d{1,3}[\s.-]?)?(?:\d[\s.-]?){8,12}\d(?![\w])")),
    ("INDIRIZZO", re.compile(r"\b(?:via|viale|piazza|piazzale|corso|vicolo|largo|strada|località)\s+"
                             r"[A-ZÀ-Ü][\wÀ-ü'.]*(?:\s+[A-ZÀ-Ü][\wÀ-ü'.]*){0,3}(?:,?\s*\d+[a-zA-Z]?)?", re.IGNORECASE)),
]


class Masker:
    """Stable placeholders for one turn; ``unmask`` puts the real values back."""

    def __init__(self, names: list[str] | None = None):
        self.map: dict[str, str] = {}          # placeholder → real
        self._rev: dict[str, str] = {}         # real (lower) → placeholder
        self._counts: dict[str, int] = {}
        words: set[str] = set()
        for n in names or []:
            n = " ".join(str(n or "").split())
            if len(n) < 3:
                continue
            words.add(n)
            first = n.split(" ")[0]
            if len(first) >= 3:
                words.add(first)
        self._names = re.compile(r"\b(" + "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
                                 + r")\b", re.IGNORECASE) if words else None

    def _slot(self, kind: str, real: str) -> str:
        key = f"{kind}:{real.lower()}"
        if key in self._rev:
            return self._rev[key]
        self._counts[kind] = self._counts.get(kind, 0) + 1
        ph = f"<{kind}_{self._counts[kind]}>"
        self._rev[key], self.map[ph] = ph, real
        return ph

    def mask(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {k: self.mask(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.mask(v) for v in value]
        if not isinstance(value, str):
            return value
        text = value
        for kind, rx in _PATTERNS:
            text = rx.sub(lambda m, k=kind: self._slot(k, m.group(0)), text)
        if self._names:
            text = self._names.sub(lambda m: self._slot("PERSONA", m.group(0)), text)
        return text

    def unmask(self, text: str) -> str:
        out = str(text or "")
        for ph, real in self.map.items():
            out = out.replace(ph, real)
        return out


def parse_verdict(raw: str | None, steps: int) -> dict | None:
    """The teacher's JSON, validated; None when it is not usable."""
    if not raw:
        return None
    m = re.search(r"\{.*\}", str(raw), re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None
    verdict = str(data.get("verdict") or "").strip().lower()
    if verdict not in VERDICTS:
        return None
    try:
        conf = max(0.0, min(1.0, float(data.get("confidence") or 0)))
    except (TypeError, ValueError):
        conf = 0.0
    remove = sorted({int(i) for i in (data.get("remove_steps") or []) if str(i).lstrip("-").isdigit()
                     and 0 <= int(i) < steps})
    answer = str(data.get("answer") or "").strip()
    needs = bool(data.get("needs_owner"))
    if verdict == "fix" and not answer and not remove:
        needs = True                       # a fix with nothing to apply
    return {"verdict": verdict, "confidence": round(conf, 2), "answer": answer if verdict == "fix" else "",
            "remove_steps": remove if verdict == "fix" else [],
            "reasons": [str(r)[:40] for r in (data.get("reasons") or [])][:8], "needs_owner": needs}


class Review:
    def __init__(self, hub, *, llm: Callable[..., str | None], auto_accept: Callable[[], float] = lambda: 0.85,
                 batch: Callable[[], int] = lambda: 30, people: Callable[[], list[str]] | None = None):
        self.hub = hub
        self.llm = llm
        self.auto_accept = auto_accept
        self.batch = batch
        self.people = people or self._hera_people

    # ── Archive ───────────────────────────────────────────────────────────
    def _rows(self, **query) -> list[dict]:
        out = self.hub.ok("archive", "GET", f"{STORE}/records", query=query, timeout=20) or {}
        return list(out.get("rows") or [])

    def _write(self, rows: list[dict]) -> None:
        for r in rows:
            r.setdefault("updated_at", now_iso())
            r.setdefault("deleted", False)
        self.hub.ok("archive", "PUT", f"{STORE}/records", body={"rows": rows}, timeout=20)

    def _hera_people(self) -> list[str]:
        out = self.hub.ok("hera", "GET", "api/people", timeout=10) or {}
        return [str(p.get("name") or "") for p in (out.get("items") or []) if p.get("name")]

    def _votes(self, session_id: str) -> dict[str, list[dict]]:
        try:
            rows = self.hub.ok("archive", "GET", "api/feedback", query={"session_id": session_id, "limit": 200},
                               timeout=10) or []
        except Exception as exc:  # noqa: BLE001 — votes are a plus, the review goes on
            logger.info("[🔄] event=review_votes_unavailable session_id=%s error=%s", session_id, exc)
            return {}
        out: dict[str, list[dict]] = {}
        for r in rows if isinstance(rows, list) else []:
            tid = str(r.get("interaction_id") or "")
            if tid:
                out.setdefault(tid, []).append({"label": r.get("quality_label"), "text": r.get("feedback_text") or ""})
        return out

    # ── run (agenda job) ─────────────────────────────────────────────────
    def _pending_traces(self, limit: int) -> list[dict]:
        state = (self._rows(kind="state", ids="review") or [{}])[0].get("data") or {}
        start = state.get("last_at")
        cutoff = datetime.now(timezone.utc) - MIN_AGE
        query = {"kind": "trace", "order": "at", "limit": limit * 3, "at_to": cutoff.isoformat()}
        if start:
            query["at_from"] = start
        rows = self._rows(**query)
        if not rows:
            return []
        done = {r["id"] for r in self._rows(kind="review", ids=",".join(r["id"] for r in rows), limit=len(rows))}
        return [r for r in rows if r["id"] not in done][:limit]

    def run(self) -> dict:
        try:
            names = self.people()
        except Exception as exc:  # noqa: BLE001
            # Without the names of Persone nothing would hide them: no turn leaves Hestia tonight.
            logger.warning("[🔄] event=review_skipped reason=people_unavailable error=%s", exc)
            return {"reviewed": 0, "skipped": "people_unavailable"}
        todo = self._pending_traces(max(1, int(self.batch())))
        counts = {s: 0 for s in STATUSES}
        failed = 0
        last_at = None
        votes_by_session: dict[str, dict] = {}
        for row in todo:
            sid = row.get("parent_id") or ""
            if sid not in votes_by_session:
                votes_by_session[sid] = self._votes(sid)
            signals = self._signals(row["id"]) + [{"type": "vote", **v} for v in votes_by_session[sid].get(row["id"], [])]
            out = self.review_one(row, signals, names)
            if out is None:
                failed += 1
                break                       # the teacher is away: stop here, the next run starts from this turn
            counts[out["status"]] += 1
            last_at = row.get("at")
        if last_at:
            self._write([{"kind": "state", "id": "review", "at": last_at, "data": {"last_at": last_at}}])
        logger.info("event=review_run reviewed=%d failed=%d counts=%s", sum(counts.values()), failed, counts)
        return {"reviewed": sum(counts.values()), "failed": failed, **counts}

    def _signals(self, trace_id: str) -> list[dict]:
        return [{"type": (r.get("data") or {}).get("type"), "text": (r.get("data") or {}).get("text", "")}
                for r in self._rows(kind="signal", ref_id=trace_id, limit=20)]

    def review_one(self, row: dict, signals: list[dict], names: list[str]) -> dict | None:
        d = row.get("data") or {}
        steps = d.get("steps") or []
        masker = Masker(names)
        try:
            m = masker.mask({"user": d.get("user", ""), "answer": d.get("answer", ""),
                             "context": (str(d.get("system") or "")[-3000:] + "\n" + str(d.get("history") or "")[-3000:]),
                             "steps": [{"i": i, "tool": s.get("tool"), "params": s.get("params"), "ok": s.get("ok"),
                                        "result": str(s.get("result") or "")[:600]} for i, s in enumerate(steps)],
                             "signals": [s for s in signals if s.get("type")]})
        except Exception as exc:  # noqa: BLE001 — never send what could not be masked
            logger.warning("[🔄] event=review_mask_failed trace_id=%s error=%s", row["id"], exc)
            return None
        prompt = PROMPT.format(
            rules=RULES, signals=json.dumps(m["signals"], ensure_ascii=False) or "nessuno", user=m["user"],
            steps="\n".join(f"{s['i']}: {s['tool']} {json.dumps(s['params'], ensure_ascii=False)} ok={s['ok']} → "
                            f"{s['result']}" for s in m["steps"]) or "nessuno",
            answer=m["answer"], context=m["context"])
        verdict = parse_verdict(self.llm(prompt, use_case=USE_CASE, max_tokens=1200, temperature=0.1), len(steps))
        if verdict is None:
            logger.info("[🔄] event=review_teacher_unusable trace_id=%s", row["id"])
            return None
        verdict["answer"] = masker.unmask(verdict["answer"])
        negative = any(s.get("type") == "vote" and s.get("label") in ("poor", "rejected") and s.get("text")
                       for s in signals)
        status = "accepted" if (verdict["confidence"] >= float(self.auto_accept()) and not verdict["needs_owner"]
                                and not negative) else "pending"
        data = {**verdict, "trace_id": row["id"], "signals": signals, "teacher_at": now_iso(), "status": status,
                "masked": len(masker.map)}
        self._write([{"kind": "review", "id": row["id"], "parent_id": row.get("parent_id"), "ref_id": status,
                      "at": row.get("at"), "data": data}])
        return data

    # ── owner ─────────────────────────────────────────────────────────────
    def pending(self, limit: int = 10) -> dict:
        rows = self._rows(kind="review", ref_id="pending", order="at", limit=max(1, min(int(limit), 50)))
        traces = {r["id"]: r for r in self._rows(kind="trace", ids=",".join(r["id"] for r in rows), limit=len(rows))} \
            if rows else {}
        items = []
        for r in rows:
            d, t = r.get("data") or {}, (traces.get(r["id"]) or {}).get("data") or {}
            steps = t.get("steps") or []
            items.append({"trace_id": r["id"], "at": r.get("at"), "user": t.get("user", ""),
                          "answer": t.get("answer", ""), "verdict": d.get("verdict"), "fixed": d.get("answer", ""),
                          "remove": [steps[i].get("tool") for i in d.get("remove_steps") or [] if i < len(steps)],
                          "tools": [s.get("tool") for s in steps], "reasons": d.get("reasons") or [],
                          "confidence": d.get("confidence"), "needs_owner": d.get("needs_owner")})
        try:
            total = int((self.hub.ok("archive", "GET", f"{STORE}/count", query={"kind": "review"}, timeout=10)
                         or {}).get("count") or 0)
        except Exception:  # noqa: BLE001
            total = None
        return {"items": items, "pending": len(items), "reviews": total}

    def decide(self, trace_id: str, decision: str, answer: str = "") -> dict:
        tid = str(trace_id or "").strip()
        decision = str(decision or "").strip().lower()
        if decision not in ("accept", "reject", "edit"):
            raise Invalid("decision: accept | reject | edit")
        rows = self._rows(kind="review", ids=tid, limit=1)
        if not rows:
            raise Invalid("revisione non trovata")
        row = rows[0]
        data = dict(row.get("data") or {})
        if decision == "edit":
            if not str(answer or "").strip():
                raise Invalid("answer: la risposta giusta")
            data.update(answer=str(answer).strip()[:8000], verdict="fix", status="edited")
        else:
            data["status"] = "accepted" if decision == "accept" else "rejected"
        data["owner_at"] = now_iso()
        self._write([{"kind": "review", "id": tid, "parent_id": row.get("parent_id"), "ref_id": data["status"],
                      "at": row.get("at"), "data": data}])
        logger.info("event=review_decided trace_id=%s status=%s", tid, data["status"])
        return {"trace_id": tid, "status": data["status"]}

