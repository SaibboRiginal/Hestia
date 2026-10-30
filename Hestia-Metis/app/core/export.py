"""Training dataset, phase D3 «Esporta» (docs/work/2026-10-30-dataset-allenamento §3.4).

Turns the saved turns into JSONL files any trainer reads (Unsloth, TRL, axolotl, online services), zipped and kept
as an Archive blob the owner downloads (WebUI Miglioramento, Telegram: the file arrives under the card):

- ``sft.jsonl``  — ``{"messages": [...], "tools": [...]}`` OpenAI format: system, user, assistant ``tool_calls`` +
  ``tool`` results, final answer. Only turns the review kept (``keep``) or corrected (``fix`` accepted, or your own
  answer ``edited``); a corrected turn loses the tool calls the review dropped and gets the corrected answer.
- ``dpo.jsonl``  — ``{"prompt": [...], "chosen": [...], "rejected": [...]}``: corrected answer vs the original one.
- ``eval.jsonl`` — like sft, about 10% of the conversations (by session, never also in sft), to test a model.
- ``card.json``  — counts, routes, models, date range, masked or not.

The owner picks at each export (Marko 2026-10-30): **oscurati** (default: names of Persone, e-mails, phones, IBAN,
addresses → ``<PERSONA_1>``…, the same masking as the nightly review) or **in chiaro** (the real text).
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import zipfile
from datetime import datetime, timezone
from typing import Callable

from hestia_common.module_kit import new_id, now_iso

from .review import Masker
from .traces import STORE

logger = logging.getLogger("hestia_metis.export")

EVAL_SHARE = 10          # % of sessions held out
_QUICK_TAIL = "MESSAGGIO UTENTE:"


def _eval_session(session_id: str) -> bool:
    return int(hashlib.sha256(str(session_id).encode()).hexdigest()[:8], 16) % 100 < EVAL_SHARE


def to_messages(trace: dict, review: dict | None) -> tuple[list[dict], str, str]:
    """(messages up to the final answer, final answer to train on, original answer)."""
    d = trace
    system, history, user = str(d.get("system") or ""), str(d.get("history") or ""), str(d.get("user") or "")
    if d.get("route") in ("quick", "quick_chat") and _QUICK_TAIL in system:
        system = system[: system.rfind(_QUICK_TAIL)].rstrip()          # the quick prompt ends with the message
    elif history:
        system = f"{system}\n\nCONTESTO CONVERSAZIONE:\n{history}".strip()
    msgs: list[dict] = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": user}]
    rv = review or {}
    drop = set(rv.get("remove_steps") or []) if rv.get("verdict") == "fix" else set()
    for i, s in enumerate(d.get("steps") or []):
        if i in drop:
            continue
        cid = f"call_{i}"
        msgs.append({"role": "assistant", "content": "", "tool_calls": [{
            "id": cid, "type": "function",
            "function": {"name": s.get("tool"), "arguments": json.dumps(s.get("params") or {}, ensure_ascii=False)}}]})
        msgs.append({"role": "tool", "tool_call_id": cid, "name": s.get("tool"), "content": str(s.get("result") or "")})
    original = str(d.get("answer") or "")
    final = str(rv.get("answer") or "").strip() if rv.get("verdict") == "fix" or rv.get("status") == "edited" else ""
    return msgs, final or original, original


def usable(review: dict | None, include_unreviewed: bool) -> bool:
    if not review:
        return include_unreviewed
    if review.get("status") == "edited":
        return True
    return review.get("status") == "accepted" and review.get("verdict") in ("keep", "fix")


class Exporter:
    def __init__(self, hub, people: Callable[[], list[str]]):
        self.hub = hub
        self.people = people

    def _rows(self, **query) -> list[dict]:
        out = self.hub.ok("archive", "GET", f"{STORE}/records", query=query, timeout=30) or {}
        return list(out.get("rows") or [])

    def _all_traces(self) -> list[dict]:
        out, seen, start = [], set(), None
        while True:
            q = {"kind": "trace", "order": "at", "limit": 1000}
            if start:
                q["at_from"] = start
            rows = [r for r in self._rows(**q) if r["id"] not in seen]
            if not rows:
                return out
            out += rows
            seen.update(r["id"] for r in rows)
            start = rows[-1].get("at")

    def _by_ids(self, kind: str, ids: list[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for i in range(0, len(ids), 100):
            part = ids[i:i + 100]
            for r in self._rows(kind=kind, ids=",".join(part), limit=len(part)):
                out[r["id"]] = r.get("data") or {}
        return out

    def build(self, *, masked: bool = True, include_unreviewed: bool = False) -> dict:
        names = self.people() if masked else []      # Hera away → raises: never export «oscurati» half-masked
        traces = self._all_traces()
        reviews = self._by_ids("review", [t["id"] for t in traces])
        toolsets = self._by_ids("toolset", sorted({(t.get("data") or {}).get("toolset_ref") for t in traces} - {"", None}))
        sft, dpo, ev = [], [], []
        card = {"routes": {}, "models": {}, "skipped": 0, "corrected": 0}
        for t in traces:
            d, rv = t.get("data") or {}, reviews.get(t["id"])
            if not usable(rv, include_unreviewed):
                card["skipped"] += 1
                continue
            msgs, final, original = to_messages(d, rv)
            tools = [{"type": "function", "function": {"name": x.get("name"), "description": x.get("description", ""),
                                                       "parameters": x.get("parameters") or {"type": "object"}}}
                     for x in (toolsets.get(d.get("toolset_ref") or "") or {}).get("tools") or []]
            masker = Masker(names) if masked else None
            m = (lambda v: masker.mask(v)) if masker else (lambda v: v)
            example = {"messages": m(msgs + [{"role": "assistant", "content": final}])}
            if tools:
                example["tools"] = tools
            (ev if _eval_session(t.get("parent_id") or "") else sft).append(example)
            if final.strip() != original.strip() and original.strip():
                card["corrected"] += 1
                dpo.append({"prompt": m(msgs), "chosen": m([{"role": "assistant", "content": final}]),
                            "rejected": m([{"role": "assistant", "content": original}])})
            card["routes"][d.get("route") or "?"] = card["routes"].get(d.get("route") or "?", 0) + 1
            card["models"][d.get("model") or "?"] = card["models"].get(d.get("model") or "?", 0) + 1
        ats = [t.get("at") for t in traces if t.get("at")]
        card.update(created_at=now_iso(), masked=masked, include_unreviewed=include_unreviewed,
                    sft=len(sft), dpo=len(dpo), eval=len(ev), turns=len(traces),
                    first=min(ats) if ats else None, last=max(ats) if ats else None,
                    format="OpenAI messages + tools (Unsloth / TRL / axolotl)")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for fname, rows in (("sft.jsonl", sft), ("dpo.jsonl", dpo), ("eval.jsonl", ev)):
                z.writestr(fname, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
            z.writestr("card.json", json.dumps(card, ensure_ascii=False, indent=2))
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
        name = f"hestia-dataset-{stamp}-{'oscurato' if masked else 'in-chiaro'}.zip"
        blob = self.hub.ok("archive", "POST", "api/blobs", body={
            "owner_module": "metis", "content_type": "application/zip",
            "data_base64": base64.b64encode(buf.getvalue()).decode(), "meta": {"name": name}}, timeout=60) or {}
        eid = new_id("x")
        row = {"name": name, "blob_id": blob.get("blob_id"), "size": len(buf.getvalue()), **card}
        self.hub.ok("archive", "PUT", f"{STORE}/records", body={"rows": [{
            "kind": "export", "id": eid, "at": now_iso(), "updated_at": now_iso(), "deleted": False, "data": row}]},
            timeout=20)
        logger.info("event=dataset_exported id=%s masked=%s sft=%d dpo=%d eval=%d skipped=%d bytes=%d",
                    eid, masked, len(sft), len(dpo), len(ev), card["skipped"], row["size"])
        return {"id": eid, **row}

    def list(self, limit: int = 10) -> list[dict]:
        return [{"id": r["id"], **(r.get("data") or {})}
                for r in self._rows(kind="export", order="-at", limit=max(1, min(int(limit), 50)))]

    def file_b64(self, export_id: str) -> dict:
        rows = self._rows(kind="export", ids=str(export_id), limit=1)
        if not rows:
            raise KeyError(export_id)
        d = rows[0].get("data") or {}
        blob = self.hub.ok("archive", "GET", f"api/blobs/{d.get('blob_id')}/base64", timeout=60) or {}
        return {"name": d.get("name"), "mime": "application/zip",
                "data_b64": blob.get("data_b64") or ""}
