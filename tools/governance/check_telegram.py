#!/usr/bin/env python3
"""Every function on Telegram, calm text (docs/work/2026-10-23-telegram-da-zero §5.7, §5.8).

Reads the tool declarations of every module (``MCPTool(...)`` and Hub inline commands with ``telegram_group``)
straight from the sources, then:
1. no emoji in tool titles or ``telegram`` labels (Telegram draws one area emoji itself);
2. every tool lands in a Telegram area with the default menu (none dropped; only section «interno» is hidden);
3. button labels fit (≤ 24 characters after Telegram's cut, never empty).
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GLYPH = re.compile("[\U0001F300-\U0001FAFF☀-➿⭐⭕⏩-⏺⌚⌛]")


def _literal(node):
    try:
        return ast.literal_eval(node)
    except Exception:  # noqa: BLE001 — not a literal (a variable, a call)
        return None


def module_tools(root: Path = ROOT) -> list[dict]:
    """``[{service, name, title, telegram_group, telegram, method, parameters}]`` of every module tool."""
    out: list[dict] = []
    for path in sorted(root.glob("Hestia-*/app/main.py")):
        service = path.parent.parent.name.removeprefix("Hestia-").lower()
        if service in ("telegram", "mcp", "dummy"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "MCPTool":
                kw = {k.arg: _literal(k.value) for k in node.keywords if k.arg}
                if not kw.get("name"):
                    continue
                params = kw.get("parameters") if isinstance(kw.get("parameters"), dict) else {}
                out.append({"service": service, "name": kw["name"], "title": kw.get("title") or kw["name"],
                            "telegram_group": kw.get("telegram_group") or "", "telegram": kw.get("telegram") or {},
                            "method": kw.get("method") or "GET", "parameters": params, "file": path})
            elif isinstance(node, ast.Dict):
                keys = [k.value for k in node.keys if isinstance(k, ast.Constant)]
                if "command" in keys and "telegram_group" in keys:
                    d = _literal(node) or {}
                    if isinstance(d, dict) and d.get("command"):
                        out.append({"service": service, "name": d["command"], "title": d.get("title") or d["command"],
                                    "telegram_group": d.get("telegram_group") or "", "telegram": d.get("telegram") or {},
                                    "method": d.get("method") or "GET", "parameters": {}, "file": path})
    return out


def main() -> int:
    sys.path[:0] = [str(ROOT / "Hestia-Telegram/app"), str(ROOT / "Hestia-Shared")]
    import os
    os.environ.setdefault("TELEGRAM_BOT_TOKEN", "0:governance")
    from telegram_bot import catalog, local_actions, ui
    from telegram_bot.menu import model

    errors: list[str] = []
    tools = module_tools()
    for t in tools:
        for text in (t["title"], (t["telegram"] or {}).get("label") or ""):
            if GLYPH.search(str(text)):
                errors.append(f"{t['file'].relative_to(ROOT)}: tool {t['name']} has an emoji in «{text}»")
    catalog_tools = [catalog.Tool(name=t["name"], title=t["title"], service=t["service"],
                                  group=str(t["telegram_group"]).lower(), hints=t["telegram"] or {}, index=i)
                     for i, t in enumerate(tools)] + local_actions.tools()
    menu = model.build(catalog_tools, {})
    for t in catalog_tools:
        if t.name in menu.hidden:
            continue
        if t.name not in menu.tool_area:
            errors.append(f"tool {t.name} is in no Telegram area")
        label = menu.label(t.name)
        if not label or len(label) > ui.LABEL_MAX:
            errors.append(f"tool {t.name}: button label «{label}» empty or too long")
    for e in errors:
        print(e)
    hidden = sorted(menu.hidden)
    print("check_telegram:", "FAILED" if errors else "PASSED",
          f"({len(catalog_tools)} actions, {len(menu.areas)} areas, hidden: {', '.join(hidden) or 'none'})")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
