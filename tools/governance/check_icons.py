"""Icons, not emoji, in the web clients (docs/work/2026-10-20-icone-nei-client).

1. The WebUI icon set (hx-icon) and the plugin SDK set (hxk-icon) have the same names and paths.
2. WebUI code and module plugin code draw no emoji or pictographs (comments are ignored).
   Telegram is not checked: it has no icons and keeps emoji.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEBUI_ICONS = ROOT / "Hestia-WebUI/frontend/src/app/ui/icon.component.ts"
SDK_ICONS = ROOT / "Hestia-Shared/webui-sdk/src/kit/basics.ts"
CLIENT_DIRS = [ROOT / "Hestia-WebUI/frontend/src", ROOT / "Hestia-Shared/webui-sdk/src",
               *sorted(ROOT.glob("Hestia-*/ui/src"))]
SUFFIXES = {".ts", ".html", ".scss", ".css"}
# Emoji / pictographs and the dingbat stars, ticks and crosses that read as emoji (arrows and math are fine).
GLYPH = re.compile("[\U0001F300-\U0001FAFF☀-➿⭐⭕⏩-⏺⌚⌛™ℹ️]")
COMMENT = re.compile(r"^\s*(//|\*|/\*)")
DUPLICATES: list[str] = []


def icon_set(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    start = text.index("const ICONS")
    block = text[text.index("{", start): text.index("\n};", start)]
    pairs = re.findall(r"^\s*'?([a-z0-9-]+)'?\s*:\s*'([^']*)',", block, re.M)
    names = [n for n, _ in pairs]
    for name in sorted({n for n in names if names.count(n) > 1}):
        DUPLICATES.append(f"{path.relative_to(ROOT)}: icon '{name}' defined twice")
    return dict(pairs)


def main() -> int:
    errors: list[str] = []
    web, sdk = icon_set(WEBUI_ICONS), icon_set(SDK_ICONS)
    errors.extend(DUPLICATES)
    for name in sorted(set(web) | set(sdk)):
        if web.get(name) != sdk.get(name):
            errors.append(f"icon '{name}' differs between hx-icon and hxk-icon (add it to both, same path)")
    for base in CLIENT_DIRS:
        for path in sorted(base.rglob("*")):
            if path.suffix not in SUFFIXES or "node_modules" in path.parts or not path.is_file():
                continue
            for no, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if COMMENT.match(line):
                    continue
                code = line.split(" // ", 1)[0]
                if GLYPH.search(code):
                    errors.append(f"{path.relative_to(ROOT)}:{no}: emoji in client code, use <hx-icon>/<hxk-icon>")
    for e in errors:
        print(e)
    print("check_icons:", "FAILED" if errors else "PASSED", f"({len(web)} icons)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
