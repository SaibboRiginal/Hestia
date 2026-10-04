#!/usr/bin/env python3
"""Create the .env files docker compose needs, from the committed .env.example templates.

Usage:  python tools/init_env.py

- Reads every `env_file:` entry of docker-compose.global.yml and docker-compose.rpi.yml (+ the root .env).
- For each missing .env: copies the sibling .env.example, or creates an empty file when no template exists.
- Never overwrites an existing .env and never prints values.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILES = ("docker-compose.global.yml", "docker-compose.rpi.yml")
ENV_FILE_RE = re.compile(r"^\s*-\s*(\./\S*\.env)\s*$")


def env_targets() -> list[Path]:
    targets = {ROOT / ".env"}
    for name in COMPOSE_FILES:
        compose = ROOT / name
        if not compose.exists():
            continue
        lines = compose.read_text(encoding="utf-8-sig").splitlines()
        in_env_file = False
        for line in lines:
            if line.strip() == "env_file:":
                in_env_file = True
                continue
            match = ENV_FILE_RE.match(line) if in_env_file else None
            if match:
                targets.add((ROOT / match.group(1)).resolve())
            else:
                in_env_file = False
    return sorted(targets)


def main() -> int:
    created = 0
    for target in env_targets():
        rel = target.relative_to(ROOT)
        if target.exists():
            print(f"event=env_exists file={rel}")
            continue
        template = target.with_name(".env.example")
        target.parent.mkdir(parents=True, exist_ok=True)
        if template.exists():
            shutil.copyfile(template, target)
            print(f"event=env_created file={rel} from={template.relative_to(ROOT)}")
        else:
            target.write_text("# no template: add overrides here\n", encoding="utf-8")
            print(f"event=env_created file={rel} from=empty")
        created += 1
    print(f"event=env_init_done created={created}")
    if created:
        print("Next: set TELEGRAM_BOT_TOKEN + ALLOWED_USER_ID (Hestia-Telegram/app/.env) and HESTIA_DB_PASSWORD (.env); see readme.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
