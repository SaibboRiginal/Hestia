"""Draw the coloured icon tiles used by readme.md (docs/assets/icons/*.svg).

Paths come from the WebUI icon set (Hestia-WebUI/frontend/src/app/ui/icon.component.ts), so the README speaks the
same visual language as the clients: stroke icons coloured by tone, never emoji. Run again after changing a colour.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "Hestia-WebUI/frontend/src/app/ui/icon.component.ts"
OUT = ROOT / "docs/assets/icons"

# Mid tones: readable on GitHub's light and dark themes alike.
TILES = {
    "private": ("host", "#14B8A6"),
    "skills": ("puzzle", "#8B5CF6"),
    "improves": ("sparkle", "#F59E0B"),
    "talk": ("brain", "#3B82F6"),
    "plan": ("calendar", "#8B5CF6"),
    "care": ("heart", "#EC4899"),
    "money": ("wallet", "#22A06B"),
    "create": ("palette", "#F97316"),
    "health": ("pulse", "#EF4444"),
    "proactive": ("bell", "#EAB308"),
    "telegram": ("chat", "#229ED9"),
    "webapp": ("window", "#6366F1"),
    "voice": ("mic", "#EC4899"),
    "external": ("link", "#14B8A6"),
    "api": ("code", "#64748B"),
    "ask": ("chat", "#3B82F6"),
    "handle": ("zap", "#F59E0B"),
    "decide": ("check-circle", "#22A06B"),
}


def icon_paths() -> dict[str, str]:
    text = SRC.read_text(encoding="utf-8")
    return {m.group(1): m.group(2) for m in re.finditer(r"^\s+'?([a-z-]+)'?:\s*'([^']+)'", text, re.M)}


def tile(path: str, color: str) -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48">'
        f'<rect x="1" y="1" width="46" height="46" rx="13" fill="{color}" fill-opacity="0.18" '
        f'stroke="{color}" stroke-opacity="0.45"/>'
        f'<g transform="translate(12 12)" fill="none" stroke="{color}" stroke-width="2.2" '
        f'stroke-linecap="round" stroke-linejoin="round"><path d="{path}"/></g></svg>\n'
    )


def step(n: int) -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32">'
        '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#F59E0B"/><stop offset="1" stop-color="#EA580C"/></linearGradient></defs>'
        '<circle cx="16" cy="16" r="15" fill="url(#g)"/>'
        f'<text x="16" y="21.5" text-anchor="middle" font-family="Segoe UI, Helvetica, Arial, sans-serif" '
        f'font-size="15" font-weight="700" fill="#fff">{n}</text></svg>\n'
    )


def divider() -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="6" viewBox="0 0 1200 6" preserveAspectRatio="none">'
        '<defs><linearGradient id="d" x1="0" x2="1"><stop offset="0" stop-color="#F59E0B" stop-opacity="0"/>'
        '<stop offset=".2" stop-color="#F59E0B"/><stop offset=".5" stop-color="#EC4899"/>'
        '<stop offset=".8" stop-color="#8B5CF6"/><stop offset="1" stop-color="#8B5CF6" stop-opacity="0"/>'
        '</linearGradient></defs><rect y="2" width="1200" height="2" rx="1" fill="url(#d)"/></svg>\n'
    )


def main() -> None:
    paths = icon_paths()
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (icon, color) in TILES.items():
        (OUT / f"{name}.svg").write_text(tile(paths[icon], color), encoding="utf-8")
    for n in range(1, 6):
        (OUT / f"step-{n}.svg").write_text(step(n), encoding="utf-8")
    (OUT / "divider.svg").write_text(divider(), encoding="utf-8")
    print(f"readme_icons: {len(TILES) + 6} files in {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
