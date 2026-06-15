#!/usr/bin/env python3
"""Governance gate: enforce docs synchronization for behavior changes.

Rules enforced:
1) If runtime behavior files change, documentation must also change.
2) Root readme.md must be updated when behavior changes.
3) Each impacted service must update its service doc hestia-<service>.md.
4) API-like changes should update Hestia-Swagger/swagger.yml.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

SERVICE_RE = re.compile(r"^(Hestia-[^/]+)/")

DOC_ALWAYS = {
    ".github/copilot-instructions.md",
    "readme.md",
    "Hestia-Swagger/swagger.yml",
    "architecture-and-flow-map.md",
}

NON_BEHAVIOR_PREFIXES = (
    ".git/",
    ".vscode/",
    "templates/",
    "__pycache__/",
)

NON_BEHAVIOR_SUFFIXES = (
    ".md",
    ".txt",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
)

TOPOLOGY_EXCLUDE = {
    "Hestia-Swagger",
}


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


def service_doc_for(service_folder: str) -> str:
    suffix = service_folder.replace("Hestia-", "").lower()
    return f"{service_folder}/hestia-{suffix}.md"


def is_doc_file(path: str) -> bool:
    if path in DOC_ALWAYS:
        return True
    if path.startswith("Hestia-") and path.endswith(".md"):
        return True
    return False


def is_behavior_file(path: str) -> bool:
    if is_doc_file(path):
        return False
    if any(path.startswith(prefix) for prefix in NON_BEHAVIOR_PREFIXES):
        return False
    if path.endswith(NON_BEHAVIOR_SUFFIXES):
        return False
    if path.startswith("Hestia-Swagger/"):
        return False
    return True


def is_api_like_change(path: str) -> bool:
    p = path.lower()
    api_tokens = (
        "/routers/",
        "/router",
        "main.py",
        "schemas.py",
        "command_catalog",
        "discovery",
        "route",
        "endpoint",
    )
    if not p.endswith((".py", ".yml", ".yaml", ".json")):
        return False
    return any(token in p for token in api_tokens)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", help="Base revision")
    parser.add_argument("--head", default="HEAD", help="Head revision")
    return parser.parse_args()


def expected_service_folders() -> list[str]:
    folders: list[str] = []
    for child in ROOT.iterdir():
        if not child.is_dir():
            continue
        name = child.name
        if not name.startswith("Hestia-"):
            continue
        if name in TOPOLOGY_EXCLUDE:
            continue
        folders.append(name)
    return sorted(folders)


def check_readme_topology_coverage() -> list[str]:
    readme_path = ROOT / "readme.md"
    if not readme_path.exists():
        return ["readme.md is missing."]

    content = readme_path.read_text(encoding="utf-8", errors="ignore").lower()
    missing = [
        folder
        for folder in expected_service_folders()
        if folder.lower() not in content
    ]
    return [
        "readme.md topology is missing service references: "
        + ", ".join(missing)
    ] if missing else []


def main() -> int:
    args = parse_args()
    if args.base:
        diff_range = ["diff", "--name-only", f"{args.base}..{args.head}"]
    else:
        diff_range = ["diff", "--name-only", "--cached"]

    changed = normalize_paths(run_git(diff_range))
    if not changed:
        print("check_docs_sync: no changed files detected")
        return 0

    changed_set = set(changed)
    behavior = [p for p in changed if is_behavior_file(p)]

    if not behavior:
        print("check_docs_sync: only docs/non-behavior changes detected")
        return 0

    errors: list[str] = []

    if "readme.md" not in changed_set:
        errors.append(
            "Behavior changes detected but readme.md was not updated.")
    else:
        errors.extend(check_readme_topology_coverage())

    impacted_services = {
        match.group(1)
        for path in behavior
        for match in [SERVICE_RE.match(path)]
        if match
    }

    for service in sorted(impacted_services):
        expected_doc = service_doc_for(service)
        if expected_doc not in changed_set:
            errors.append(
                f"Behavior changes in {service} require service doc update: {expected_doc}."
            )

    has_api_like_change = any(is_api_like_change(path) for path in behavior)
    if has_api_like_change and "Hestia-Swagger/swagger.yml" not in changed_set:
        errors.append(
            "API-like behavior changes detected but Hestia-Swagger/swagger.yml was not updated."
        )

    if errors:
        print("check_docs_sync: FAILED")
        for err in errors:
            print(f"- {err}")
        print("Changed files:")
        for path in changed:
            print(f"- {path}")
        return 1

    print("check_docs_sync: PASSED")
    print("Behavior files:")
    for path in behavior:
        print(f"- {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
