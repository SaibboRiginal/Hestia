#!/usr/bin/env python3
"""Run every governance gate locally, before pushing (seconds, no pytest, no network).

Most red CI runs on pull requests were a forgotten doc or a Hub tag, found only after the push. This runs the
same gates as `.github/workflows/governance-checks.yml` on the branch's changes against ``origin/main``:

    python tools/governance/precheck.py            # base = merge-base with origin/main
    python tools/governance/precheck.py --base <sha>

Uncommitted changes are not seen by the diff gates: commit first. A gate whose dependency is not installed
here (Telegram's bot library, pydantic) is reported as skipped, not failed; CI runs it anyway.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GOV = ROOT / "tools" / "governance"


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", help="Base revision (default: merge-base with origin/main)")
    args = parser.parse_args()
    base = args.base or git("merge-base", "origin/main", "HEAD")
    if not base:
        print("precheck: no origin/main here; run `git fetch origin main` or pass --base")
        return 2
    if git("status", "--porcelain", "--untracked-files=no"):
        print("precheck: [!] uncommitted changes are not checked by the diff gates; commit first")

    gates = [
        ("Docs sync", ["check_docs_sync.py", "--base", base, "--head", "HEAD"]),
        ("Command contracts", ["check_command_contracts.py", "--base", base, "--head", "HEAD"]),
        ("Icons, not emoji", ["check_icons.py"]),
        ("Hub tags", ["check_hub_tags.py"]),
        ("Expected test files", ["check_test_sync.py"]),
        ("Every function on Telegram", ["check_telegram.py"]),
    ]
    failed, skipped = [], []
    for title, cmd in gates:
        res = subprocess.run([sys.executable, str(GOV / cmd[0]), *cmd[1:]], cwd=ROOT, capture_output=True,
                             text=True, check=False)
        out = (res.stdout + res.stderr).strip()
        if res.returncode and "ModuleNotFoundError" in out:
            skipped.append(title)
            print(f"[skip] {title}: {out.splitlines()[-1]}")
        elif res.returncode:
            failed.append(title)
            print(f"[FAIL] {title}\n{out}\n")
        else:
            print(f"[ ok ] {title}")
    print(f"\nprecheck: {len(gates) - len(failed) - len(skipped)} ok, {len(failed)} failed, {len(skipped)} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
