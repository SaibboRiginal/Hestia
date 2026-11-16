#!/usr/bin/env python3
"""Every fixed text a person reads has its Italian translation (standard: docs/LANGUAGES.md).

The code is English. Scans ``tr("…")`` in the Python modules and ``tr('…')`` / ``'…' | tr`` in the WebUI shell, the
plugins and the SDK kit, and checks each English source text is a key of
``Hestia-Shared/hestia_common/locales/it/messages.json``.

    python tools/governance/check_i18n.py                  # list what is missing (exit 1 if any)
    python tools/governance/check_i18n.py --todo todo.json # also write {"Text": ""} to fill in
    python tools/governance/check_i18n.py --merge todo.json  # add the filled entries to the Italian catalog

No network, no imports of the modules: it reads the sources only.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "Hestia-Shared" / "hestia_common" / "locales" / "it" / "messages.json"

# A text with no letters ("{0} · {1}") needs no translation.
_WORDS = re.compile(r"[A-Za-z]{2,}")
# A quoted TS literal; `\\'` is an Angular template quote escaped inside a TS string.
_Q = r"""'(?:\\\\.|[^'\\\n]|\\.)*'""" + r'''|"(?:\\\\.|[^"\\\n]|\\.)*"'''
_TS_TR = re.compile(rf"""\btr\(\s*({_Q})\s*[,)]|({_Q})\s*\|\s*tr\b""")
_ESC = {"n": "\n", "t": "\t", "\\": "\\", "'": "'", '"': '"', "`": "`", "$": "$"}


def _ts_unquote(lit: str) -> str:
    body = re.sub(r"\\\\(['\"])", r"\1", lit[1:-1])

    def one(m: re.Match) -> str:
        code = m.group(1)
        if code[0] == "u" and len(code) > 1:
            return chr(int(code[1:].strip("{}"), 16))
        return _ESC.get(code, code)
    return re.sub(r"\\(u\{?[0-9a-fA-F]+\}?|.)", one, body)


def python_texts():
    """(path, text) of every ``tr("literal")`` in the modules (tests excluded)."""
    for path in sorted(ROOT.glob("Hestia-*/**/*.py")):
        if "/tests/" in path.as_posix() or "node_modules" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call) and getattr(n.func, "id", "") == "tr" and n.args
                    and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)
                    and _WORDS.search(re.sub(r"\{[^{}]*\}", "", n.args[0].value))):
                yield path, n.args[0].value


def web_texts():
    """(path, text) of every ``tr('literal')`` / ``'literal' | tr`` in the WebUI, the plugins and the SDK kit."""
    files = [*ROOT.glob("Hestia-WebUI/frontend/src/**/*.ts"), *ROOT.glob("Hestia-WebUI/frontend/src/**/*.html"),
             *ROOT.glob("Hestia-*/ui/src/**/*.ts"), *ROOT.glob("Hestia-Shared/webui-sdk/src/**/*.ts")]
    for path in sorted(files):
        if "node_modules" in path.parts or path.name == "i18n.ts":
            continue
        for m in _TS_TR.finditer(path.read_text(encoding="utf-8")):
            text = _ts_unquote(m.group(1) or m.group(2))
            if text and _WORDS.search(re.sub(r"\{[^{}]*\}", "", text)):
                yield path, text


def missing() -> dict[str, str]:
    """English source text → first file that uses it, for every text without an Italian entry."""
    en = json.loads(CATALOG.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for path, text in [*python_texts(), *web_texts()]:
        if text not in en:
            out.setdefault(text, path.relative_to(ROOT).as_posix())
    return out


def merge(todo: Path) -> int:
    """Add the filled entries of ``todo`` to the Italian catalog (empty ones are skipped)."""
    en = json.loads(CATALOG.read_text(encoding="utf-8"))
    filled = {k: v for k, v in json.loads(todo.read_text(encoding="utf-8")).items() if isinstance(v, str) and v}
    en.update(filled)
    CATALOG.write_text(json.dumps(en, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"check_i18n: {len(filled)} Italian texts added to {CATALOG.relative_to(ROOT)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--todo", type=Path, help="write the missing texts as {text: ''} to this file")
    parser.add_argument("--merge", type=Path, help="add the filled entries of this file to the Italian catalog")
    args = parser.parse_args()
    if args.merge:
        return merge(args.merge)
    gaps = missing()
    if args.todo:
        args.todo.write_text(json.dumps({k: "" for k in gaps}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if not gaps:
        print("check_i18n: every text has its Italian translation")
        return 0
    print(f"check_i18n: {len(gaps)} texts without Italian (add them to {CATALOG.relative_to(ROOT)}, "
          "or run with --todo file, fill it, then --merge file):")
    for text, where in list(gaps.items())[:50]:
        print(f"- {where}: {text[:80]!r}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
