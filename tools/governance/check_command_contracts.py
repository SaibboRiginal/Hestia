#!/usr/bin/env python3
"""Governance gate: validate command metadata and detect contract drift.

Checks:
1) Validate Telegram local command catalog entries include required fields.
2) If command-contract files changed, require capability inventory and Swagger sync.
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

TELEGRAM_COMMAND_FILE = ROOT / "Hestia-Telegram" / "app" / "command_catalog.py"
REQUIRED_COMMAND_KEYS = {
    "command",
    "title",
    "description",
    "method",
    "path",
    "response_mode",
    "clients",
}

CONTRACT_KEYWORDS = (
    "command_catalog",
    "discovery",
    "capabilities",
    "route",
    "router",
)


def run_git(args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(result.stderr.strip() or result.stdout.strip(), file=sys.stderr)
        raise RuntimeError(
            f"git {' '.join(args)} failed with code {result.returncode}")
    return result.stdout


def normalize_paths(lines: str) -> list[str]:
    files = []
    for raw in lines.splitlines():
        path = raw.strip().replace("\\", "/")
        if path:
            files.append(path)
    return files


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", help="Base revision")
    parser.add_argument("--head", default="HEAD", help="Head revision")
    return parser.parse_args()


def extract_command_dict_keys(path: Path) -> list[set[str]]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    rows: list[set[str]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue

        keys: set[str] = set()
        for key_node in node.keys:
            if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
                keys.add(key_node.value)

        if "command" in keys:
            rows.append(keys)

    return rows


def has_contract_change(path: str) -> bool:
    lower = path.lower()
    if not lower.endswith((".py", ".yml", ".yaml", ".json")):
        return False
    return any(token in lower for token in CONTRACT_KEYWORDS)


def main() -> int:
    args = parse_args()
    if args.base:
        changed = normalize_paths(
            run_git(["diff", "--name-only", f"{args.base}..{args.head}"]))
    else:
        changed = normalize_paths(run_git(["diff", "--name-only", "--cached"]))

    errors: list[str] = []

    if not TELEGRAM_COMMAND_FILE.exists():
        errors.append("Missing Telegram command catalog file.")
    else:
        rows = extract_command_dict_keys(TELEGRAM_COMMAND_FILE)
        if not rows:
            errors.append(
                "No command entries found in Telegram command catalog.")
        else:
            for idx, keys in enumerate(rows, start=1):
                missing = sorted(REQUIRED_COMMAND_KEYS - keys)
                if missing:
                    errors.append(
                        "Telegram command entry #"
                        f"{idx} missing required keys: {', '.join(missing)}"
                    )

    if changed:
        changed_set = set(changed)
        has_contract_changes = any(has_contract_change(path)
                                   for path in changed)
        if has_contract_changes:
            if "capability-inventory.md" not in changed_set:
                errors.append(
                    "Contract-related changes detected but capability-inventory.md was not updated."
                )
            if "capability-inventory.json" not in changed_set:
                errors.append(
                    "Contract-related changes detected but capability-inventory.json was not updated."
                )
            if "Hestia-Swagger/swagger.yml" not in changed_set:
                errors.append(
                    "Contract-related changes detected but Hestia-Swagger/swagger.yml was not updated."
                )

    if errors:
        print("check_command_contracts: FAILED")
        for err in errors:
            print(f"- {err}")
        if changed:
            print("Changed files:")
            for path in changed:
                print(f"- {path}")
        return 1

    print("check_command_contracts: PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
