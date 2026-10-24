"""Components inside chat answers (Cindy idea 9, dossier docs/work/2026-10-24-tutto-brainstorm-cindy).

A capable model may put, in its WebUI answer, a fenced block ``hestia-ui`` with **one JSON object per line**; each
line is a component the WebUI draws with its own kit (``hxk-*``, stroke icons, theme tones — never emoji, never
invented colours). The same block reaches Telegram as plain text through ``to_text`` (one description, two
clients). Buttons only **send a visible message** in the chat, they never run a tool by themselves.

Components (``c``): ``card {title, text, tone, icon}`` · ``stat {label, value, hint, tone}`` ·
``table {cols, rows}`` · ``list {items: [{title, meta, tone}]}`` · ``chart {kind: bar|line, labels, values, unit}`` ·
``checklist {items: [{label, done}]}`` · ``button {label, send}``. Tones = roles only: primary, success, warning,
danger, info (mapped to the light/dark theme by the client).
"""
from __future__ import annotations

import json
import re
from typing import Any

FENCE = re.compile(r"```hestia-ui[ \t]*\n(.*?)```", re.DOTALL)
COMPONENTS = ("card", "stat", "table", "list", "chart", "checklist", "button")
TONES = ("", "primary", "success", "warning", "danger", "info")
MAX_ROWS = 50

# Added to the prompt only for the WebUI and only when the answering model is a capable one (locals stay caveman).
PROMPT = (
    "COMPONENTI (solo se aiutano, es. numeri, tabelle, elenchi, scelte): blocco ```hestia-ui con un oggetto JSON per "
    "riga. c = card{title,text,tone} | stat{label,value,hint,tone} | table{cols,rows} | list{items:[{title,meta}]} | "
    "chart{kind:bar|line,labels,values,unit} | checklist{items:[{label,done}]} | button{label,send}. tone solo: "
    "primary, success, warning, danger, info. Niente emoji, niente colori. button manda in chat il testo send. "
    "Il testo normale resta fuori dal blocco.")


def _clean(comp: Any) -> dict | None:
    if not isinstance(comp, dict):
        return None
    kind = str(comp.get("c") or comp.get("type") or "").strip().lower()
    if kind not in COMPONENTS:
        return None
    out = {k: v for k, v in comp.items() if k not in ("type",)}
    out["c"] = kind
    if str(out.get("tone") or "") not in TONES:
        out["tone"] = ""
    if kind == "table":
        out["cols"] = [str(c) for c in (out.get("cols") or [])][:12]
        out["rows"] = [[str(v) for v in (r if isinstance(r, list) else [r])][:12] for r in (out.get("rows") or [])][:MAX_ROWS]
    elif kind in ("list", "checklist"):
        out["items"] = [i if isinstance(i, dict) else {"title": str(i), "label": str(i)}
                        for i in (out.get("items") or [])][:MAX_ROWS]
    elif kind == "chart":
        labels = [str(v) for v in (out.get("labels") or [])][:60]
        values = []
        for v in (out.get("values") or [])[:60]:
            try:
                values.append(float(v))
            except (TypeError, ValueError):
                values.append(0.0)
        out.update(labels=labels, values=values, kind=out.get("kind") if out.get("kind") in ("bar", "line") else "bar")
    elif kind == "button":
        out["label"] = str(out.get("label") or "")[:60]
        out["send"] = str(out.get("send") or out.get("label") or "")[:500]
        if not out["label"]:
            return None
    return out


def parse_block(body: str) -> list[dict]:
    comps = []
    for line in (body or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            comp = _clean(json.loads(line))
        except ValueError:
            comp = None
        if comp:
            comps.append(comp)
    return comps


def segments(answer: str) -> list[dict]:
    """``[{"text": …} | {"ui": [components]}]`` in order (what the WebUI draws)."""
    out, pos = [], 0
    for m in FENCE.finditer(answer or ""):
        if m.start() > pos and answer[pos:m.start()].strip():
            out.append({"text": answer[pos:m.start()]})
        comps = parse_block(m.group(1))
        if comps:
            out.append({"ui": comps})
        pos = m.end()
    if pos < len(answer or "") and answer[pos:].strip():
        out.append({"text": answer[pos:]})
    return out


def has_blocks(answer: str) -> bool:
    return bool(FENCE.search(answer or ""))


def _num(v: float) -> str:
    return f"{v:.0f}" if float(v).is_integer() else f"{v:.2f}".replace(".", ",")


def component_text(c: dict) -> str:
    kind = c["c"]
    if kind == "card":
        return "\n".join(p for p in (str(c.get("title") or ""), str(c.get("text") or "")) if p)
    if kind == "stat":
        return f"{c.get('label', '')}: {c.get('value', '')}" + (f" ({c['hint']})" if c.get("hint") else "")
    if kind == "table":
        lines = [" · ".join(c.get("cols") or [])] if c.get("cols") else []
        lines += [" · ".join(r) for r in c.get("rows") or []]
        return "\n".join(lines)
    if kind == "list":
        return "\n".join(f"• {i.get('title') or i.get('label') or ''}" + (f" — {i['meta']}" if i.get("meta") else "")
                         for i in c.get("items") or [])
    if kind == "checklist":
        return "\n".join(f"{'☑' if i.get('done') else '☐'} {i.get('label') or i.get('title') or ''}"
                         for i in c.get("items") or [])
    if kind == "chart":
        unit = f" {c['unit']}" if c.get("unit") else ""
        return "\n".join(f"{lab}: {_num(val)}{unit}" for lab, val in zip(c.get("labels") or [], c.get("values") or []))
    if kind == "button":
        return f"→ {c.get('label')}"
    return ""


def to_text(answer: str) -> str:
    """The answer with every ``hestia-ui`` block turned into plain text (Telegram and other text clients)."""
    if not has_blocks(answer):
        return answer
    parts = []
    for seg in segments(answer):
        if "text" in seg:
            parts.append(seg["text"].strip("\n"))
        else:
            parts.append("\n\n".join(t for t in (component_text(c) for c in seg["ui"]) if t))
    return "\n\n".join(p for p in parts if p.strip())


def buttons(answer: str) -> list[dict]:
    """The buttons of an answer (Telegram shows them as reply buttons that send ``send``)."""
    return [c for seg in segments(answer) for c in seg.get("ui", []) if c["c"] == "button"]
