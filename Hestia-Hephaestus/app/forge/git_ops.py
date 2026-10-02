"""Thin, explicit git wrapper.  Every call is logged-friendly and raises
``GitError`` with stderr on failure.  ``safe.directory=*`` avoids the
"dubious ownership" refusal when the repo is bind-mounted into the container."""
from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


def git(cwd: Path | str, *args: str, timeout: int = 120, check: bool = True) -> str:
    cmd = ["git", "-c", "safe.directory=*", "-C", str(cwd), *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {(proc.stderr or proc.stdout).strip()[:800]}")
    return proc.stdout.strip()


def is_repo(path: Path) -> bool:
    try:
        return git(path, "rev-parse", "--is-inside-work-tree") == "true"
    except Exception:
        return False


def current_branch(repo: Path) -> str:
    return git(repo, "rev-parse", "--abbrev-ref", "HEAD")


def rev(repo: Path, ref: str = "HEAD") -> str:
    return git(repo, "rev-parse", ref)


def create_worktree(repo: Path, worktree: Path, branch: str, base: str) -> None:
    worktree.parent.mkdir(parents=True, exist_ok=True)
    git(repo, "worktree", "add", "-b", branch, str(worktree), base)


def remove_worktree(repo: Path, worktree: Path, branch: str | None = None, delete_branch: bool = False) -> None:
    if worktree.exists():
        git(repo, "worktree", "remove", "--force", str(worktree), check=False)
    git(repo, "worktree", "prune", check=False)
    if branch and delete_branch:
        git(repo, "branch", "-D", branch, check=False)


def commit_all(worktree: Path, message: str, name: str, email: str) -> str | None:
    """Stage everything and commit.  Returns the sha, or None when nothing changed."""
    git(worktree, "add", "-A")
    staged = git(worktree, "diff", "--cached", "--name-only")
    if not staged:
        return None
    git(worktree, "-c", f"user.name={name}", "-c", f"user.email={email}", "commit", "-q", "-m", message)
    return rev(worktree)


def changed_files(worktree: Path, base: str) -> list[str]:
    out = git(worktree, "diff", "--name-only", f"{base}...HEAD")
    return [line for line in out.splitlines() if line.strip()]


def diff_stat(worktree: Path, base: str) -> str:
    return git(worktree, "diff", "--stat", f"{base}...HEAD")


def diff(worktree_or_repo: Path, base: str, head: str = "HEAD", max_chars: int = 60000) -> str:
    out = git(worktree_or_repo, "diff", f"{base}...{head}")
    return out if len(out) <= max_chars else out[:max_chars] + "\n... [diff truncated]"


def is_clean(repo: Path) -> bool:
    return git(repo, "status", "--porcelain", "--untracked-files=no") == ""


def merge_no_ff(repo: Path, branch: str, message: str, name: str, email: str) -> str:
    try:
        git(repo, "-c", f"user.name={name}", "-c", f"user.email={email}",
            "merge", "--no-ff", "-m", message, branch, timeout=300)
    except GitError:
        git(repo, "merge", "--abort", check=False)
        raise
    return rev(repo)


def revert_merge(repo: Path, merge_sha: str, name: str, email: str) -> str:
    try:
        git(repo, "-c", f"user.name={name}", "-c", f"user.email={email}",
            "revert", "-m", "1", "--no-edit", merge_sha, timeout=300)
    except GitError:
        git(repo, "revert", "--abort", check=False)
        raise
    return rev(repo)


def push(repo: Path, branch: str) -> None:
    git(repo, "push", "-u", "origin", branch, timeout=180)
