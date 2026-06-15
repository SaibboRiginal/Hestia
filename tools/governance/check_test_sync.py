#!/usr/bin/env python3
"""Hestia test-sync governance checker.

Verifies that every service in the EXPECTED_TEST_FILES dictionary has its
required test file(s) on disk.  Run this as part of a CI gate to catch
missing test coverage after adding new services.

Usage:
    python check_test_sync.py          # prints report and exits 0 (ok) / 1 (missing)
    python check_test_sync.py --strict # exits 1 on ANY missing file
"""
from __future__ import annotations

import sys
from pathlib import Path

# ── Expected test files per service ──────────────────────────────────────────
# Map service directory name → list of relative test file paths that MUST exist.
EXPECTED_TEST_FILES: dict[str, list[str]] = {
    "Hestia-Oracle": [
        "tests/conftest.py",
        "tests/TESTING.md",
        "tests/test_agent_loop.py",
        "tests/test_memory_intent.py",
        "tests/test_chat_classifier.py",
        "tests/test_user_control_service.py",
        "tests/test_module_registry.py",
        "tests/test_agent_factory.py",
        "tests/test_oracle_api.py",
        "tests/test_live_tool_calling.py",
        "tests/test_live_formatting.py",
    ],
    "Hestia-Telegram": [
        "tests/conftest.py",
        "tests/TESTING.md",
        "tests/test_message_format.py",
        "tests/test_command_catalog.py",
        "tests/test_bot_handlers.py",
        "tests/test_command_execution.py",
        "tests/test_control_api.py",
        "tests/test_formatters.py",
    ],
    "Hestia-Athena": [
        "tests/conftest.py",
        "tests/TESTING.md",
        "tests/test_athena_runtime.py",
    ],
    "Hestia-Hub": [
        "tests/conftest.py",
        "tests/TESTING.md",
        "tests/test_hub_registry.py",
    ],
    "Hestia-Archive": [
        "tests/conftest.py",
        "tests/TESTING.md",
        "tests/test_archive.py",
    ],
    "Hestia-Hermes": [
        "tests/conftest.py",
        "tests/TESTING.md",
        "tests/test_hermes.py",
    ],
    "Hestia-Hecate": [
        "tests/conftest.py",
        "tests/TESTING.md",
        "tests/test_hecate.py",
    ],
    "Hestia-Chronos": [
        "tests/conftest.py",
        "tests/TESTING.md",
        "tests/test_chronos.py",
    ],
    "Hestia-Iris": [
        "tests/conftest.py",
        "tests/TESTING.md",
        "tests/test_iris.py",
    ],
    "Hestia-Argus": [
        "tests/conftest.py",
        "tests/TESTING.md",
        "tests/test_argus.py",
    ],
    "Hestia-Hephaestus": [
        "tests/conftest.py",
        "tests/TESTING.md",
        "tests/test_hephaestus.py",
    ],
    "Hestia-Scout": [
        "tests/conftest.py",
        "tests/TESTING.md",
        "tests/test_scout.py",
    ],
    "Hestia-Atlas": [
        "tests/conftest.py",
        "tests/TESTING.md",
        "tests/test_atlas.py",
    ],
    "Hestia-Dummy": [
        "tests/conftest.py",
        "tests/TESTING.md",
        "tests/test_dummy.py",
    ],
}

ROOT = Path(__file__).resolve().parents[2]


def check() -> dict[str, list[str]]:
    """Return mapping of service → list of MISSING file paths."""
    missing: dict[str, list[str]] = {}
    for service, files in EXPECTED_TEST_FILES.items():
        service_root = ROOT / service
        missing_here: list[str] = []
        for rel in files:
            full = service_root / rel
            if not full.exists():
                missing_here.append(str(full.relative_to(ROOT)))
        if missing_here:
            missing[service] = missing_here
    return missing


def main() -> int:
    strict = "--strict" in sys.argv
    missing = check()

    total_expected = sum(len(v) for v in EXPECTED_TEST_FILES.values())
    total_missing = sum(len(v) for v in missing.values())
    total_present = total_expected - total_missing

    print(f"\n{'='*60}")
    print(f"  Hestia test-sync report")
    print(f"{'='*60}")
    print(f"  Services checked : {len(EXPECTED_TEST_FILES)}")
    print(f"  Files expected   : {total_expected}")
    print(f"  Files present    : {total_present}")
    print(f"  Files missing    : {total_missing}")
    print(f"{'='*60}\n")

    if missing:
        print("MISSING test files:")
        for service, files in missing.items():
            print(f"\n  {service}:")
            for f in files:
                print(f"    X {f}")
        print()
        return 1

    print("All expected test files are present. [OK]\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
