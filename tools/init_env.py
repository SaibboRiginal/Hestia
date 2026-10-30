#!/usr/bin/env python3
"""Create the .env files docker compose needs, from the committed .env.example templates.

Usage:  python tools/init_env.py [--generate-secrets [--new-db]]

- Reads every `env_file:` entry of docker-compose.global.yml and docker-compose.rpi.yml (+ the root .env).
- For each missing .env: copies the sibling .env.example, or creates an empty file when no template exists.
- Never overwrites an existing .env and never prints values.
- --generate-secrets (the installer): fills the root .env's WEBUI_SECRET_KEY when empty, and with --new-db (no
  Postgres volume yet) replaces the template's HESTIA_DB_PASSWORD with a random one. An existing value is never
  touched: a database already created keeps working.
"""

from __future__ import annotations

import re
import secrets
import shutil
import sys
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


TEMPLATE_DB_PASSWORD = "super_secret_local_password"


def generate_secrets(new_db: bool) -> int:
    """Random values for the root .env keys nobody should have to invent. Returns how many were set."""
    path = ROOT / ".env"
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    wanted = {"WEBUI_SECRET_KEY": ("",)}
    if new_db:
        wanted["HESTIA_DB_PASSWORD"] = ("", TEMPLATE_DB_PASSWORD)
    done: set[str] = set()
    for i, line in enumerate(lines):
        key, sep, value = line.partition("=")
        key = key.strip()
        if sep and key in wanted and key not in done and value.strip() in wanted[key]:
            lines[i] = f"{key}={secrets.token_urlsafe(24)}"  # URL-safe: the DB password is embedded in DATABASE_URL
            done.add(key)
            print(f"event=env_secret_generated key={key}")
    for key in wanted:
        if key not in done and not any(line.split("=", 1)[0].strip() == key for line in lines):
            lines.append(f"{key}={secrets.token_urlsafe(24)}")
            done.add(key)
            print(f"event=env_secret_generated key={key}")
    if done:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(done)


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
    if "--generate-secrets" in sys.argv[1:]:
        generate_secrets(new_db="--new-db" in sys.argv[1:])
    print(f"event=env_init_done created={created}")
    if created:
        print("Next: set TELEGRAM_BOT_TOKEN + ALLOWED_USER_ID (Hestia-Telegram/app/.env) and HESTIA_DB_PASSWORD (.env); see readme.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
