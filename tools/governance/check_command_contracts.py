#!/usr/bin/env python3
"""Governance gate: validate command metadata and detect contract drift.

Checks:
1) Validate Telegram local command catalog entries include required fields.
2) If command-contract files changed, require capability inventory and Swagger sync.
3) Verify maintenance-eligible services each expose a *_reconcile command that
   routes to /api/module/maintenance/reconcile (Phase 5 contract enforcement).
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

# Services that must expose a *_reconcile maintenance command (Phase 5 contract).
# Each entry: (service_label, path_to_hub_registration_source_file)
MAINTENANCE_ELIGIBLE_SERVICES: list[tuple[str, str]] = [
    ("archive", "Hestia-Archive/app/main.py"),
    ("scout", "Hestia-Scout/app/main.py"),
    ("chronos", "Hestia-Chronos/app/core/hub_client.py"),
    ("iris", "Hestia-Iris/app/main.py"),
]
MAINTENANCE_RECONCILE_PATH = "/api/module/maintenance/reconcile"


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


def check_maintenance_contracts(errors: list[str]) -> None:
    """Phase 5: verify each eligible service has a reconcile command registered."""
    for service_label, rel_path in MAINTENANCE_ELIGIBLE_SERVICES:
        src_file = ROOT / rel_path
        if not src_file.exists():
            errors.append(
                f"Maintenance contract check: source file not found for {service_label}: {rel_path}"
            )
            continue

        source = src_file.read_text(encoding="utf-8")

        # Check 1: a command name ending in _reconcile is declared
        has_reconcile_cmd = "_reconcile" in source and "command" in source
        # Check 2: the canonical maintenance path is present
        has_maintenance_path = MAINTENANCE_RECONCILE_PATH in source

        if not has_reconcile_cmd:
            errors.append(
                f"Maintenance contract: {service_label} has no *_reconcile command registered in {rel_path}. "
                "Add a '<service>_reconcile' entry to capabilities.commands."
            )
        if not has_maintenance_path:
            errors.append(
                f"Maintenance contract: {service_label} does not reference the canonical path "
                f"'{MAINTENANCE_RECONCILE_PATH}' in {rel_path}. "
                "Ensure the reconcile command points to the standardized endpoint."
            )


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
            if "architecture-and-flow-map.md" not in changed_set:
                errors.append(
                    "Contract-related changes detected but architecture-and-flow-map.md was not updated."
                )
            if "Hestia-Swagger/swagger.yml" not in changed_set:
                errors.append(
                    "Contract-related changes detected but Hestia-Swagger/swagger.yml was not updated."
                )

    # Phase 5: maintenance contract enforcement (always runs, not diff-gated)
    check_maintenance_contracts(errors)

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
