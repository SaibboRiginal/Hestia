"""Optional ``display`` block next to a tool's data: how a client without a model shows the result
(docs/work/2026-10-23-telegram-da-zero §6).

A module returns its usual JSON plus ``"display": display(...)``. Telegram draws it as one card (title, subtitle,
lines, items, next-step buttons); the WebUI ignores it; Hestia-MCP removes it for every caller except Telegram, so
models and external AIs see the same data as before. No emoji, no ids, no module names: plain Italian.

    return {"items": rows, "display": display("Allenamento di oggi", subtitle="Push A · 5 esercizi",
                                              items=[item(r["name"], [f"{r['sets']}×{r['reps']}"]) for r in rows],
                                              actions=[action("Inizia", "fitness_start", style="primary")])}
"""
from __future__ import annotations

from typing import Any, Iterable

TONES = ("danger", "warning", "success", "info")
STYLES = ("primary", "success", "danger")


def item(title: str, meta: Iterable[Any] = (), *, url: str = "", tone: str = "") -> dict:
    """One line ``• title · meta · meta`` (``tone`` → a coloured dot instead of the bullet)."""
    out: dict[str, Any] = {"title": str(title or "").strip(),
                           "meta": [str(m) for m in meta if m not in (None, "") and str(m).strip()]}
    if url:
        out["url"] = str(url)
    if tone in TONES:
        out["tone"] = tone
    return out


def action(label: str, tool: str, args: dict | None = None, *, style: str = "") -> dict:
    """A button for the next step: runs ``tool`` with ``args`` preset (missing values are asked)."""
    out: dict[str, Any] = {"label": str(label), "tool": str(tool)}
    if args:
        out["args"] = dict(args)
    if style in STYLES:
        out["style"] = style
    return out


def display(title: str, *, subtitle: str = "", lines: Iterable[str] = (), items: Iterable[dict] = (),
            actions: Iterable[dict] = (), footer: str = "", tone: str = "", image: str = "",
            images: Iterable[str] = ()) -> dict:
    """The block. ``lines``: plain sentences; ``items``: :func:`item`; ``actions``: :func:`action` (max 6 drawn);
    ``image``/``images``: public https URLs shown as photo / album."""
    out: dict[str, Any] = {"title": str(title or "").strip()}
    if subtitle:
        out["subtitle"] = str(subtitle)
    lines = [str(x) for x in lines if str(x or "").strip()]
    if lines:
        out["lines"] = lines
    items = [i for i in items if isinstance(i, dict) and i.get("title")]
    if items:
        out["items"] = items
    actions = [a for a in actions if isinstance(a, dict) and a.get("label") and a.get("tool")][:6]
    if actions:
        out["actions"] = actions
    if footer:
        out["footer"] = str(footer)
    if tone in TONES:
        out["tone"] = tone
    if image:
        out["image"] = str(image)
    images = [str(i) for i in images if str(i).startswith("http")]
    if images:
        out["images"] = images
    return out


def strip(payload: Any) -> Any:
    """The same answer without the ``display`` block (for models and external AIs)."""
    if isinstance(payload, dict) and "display" in payload:
        return {k: v for k, v in payload.items() if k != "display"}
    return payload


def money(value: Any) -> str:
    """``1234.5`` → «1.234,50 €»."""
    try:
        n = float(value)
    except (TypeError, ValueError):
        return ""
    return f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"
