"""Read-only git browser for the WebUI "Sviluppo" page (/api/hephaestus/repo/*).

Everything is ``git`` plumbing on the mounted checkout (``HEPHAESTUS_REPO_PATH``):
no writes, refs and paths validated, secret files never served, big outputs capped.
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath
from pathlib import Path
from typing import Any

from . import git_ops

_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@^~{}-]{0,200}$")
_SHA = re.compile(r"^[0-9a-fA-F]{4,40}$")
_SECRET_NAMES = {".env", "credentials.json", "google_token.json", "token.json", "id_rsa", "id_ed25519"}
_MAX_FILE = 400_000
_MAX_DIFF = 300_000
_FS, _RS = "\x01", "\x02"   # not whitespace: git_ops.git() strips its output


class RepoError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _ref(ref: str | None, default: str = "HEAD") -> str:
    ref = str(ref or "").strip() or default
    if not _REF.match(ref) or ".." in ref:
        raise RepoError(f"invalid ref {ref!r}")
    return ref


def _path(path: str | None) -> str:
    path = str(path or "").strip().strip("/")
    if not path:
        return ""
    parts = PurePosixPath(path).parts
    if any(p in ("..", ".git") for p in parts) or path.startswith("-"):
        raise RepoError(f"invalid path {path!r}")
    return path


def _secret(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    return name in _SECRET_NAMES or name.startswith(".env.") and not name.endswith(".example")


def _clip(text: str, limit: int) -> tuple[str, bool]:
    return (text, False) if len(text) <= limit else (text[:limit] + "\n... [troncato]", True)


def parse_numstat(out: str) -> list[dict[str, Any]]:
    """``git diff --numstat`` → [{path, added, deleted, binary, old_path?}]."""
    rows = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added, deleted, path = parts[0], parts[1], "\t".join(parts[2:])
        row: dict[str, Any] = {"path": path, "added": None if added == "-" else int(added),
                               "deleted": None if deleted == "-" else int(deleted), "binary": added == "-"}
        if " => " in path:  # rename: "dir/{a => b}/f" or "a => b"
            m = re.match(r"^(.*)\{(.*) => (.*)\}(.*)$", path)
            if m:
                row["old_path"] = f"{m[1]}{m[2]}{m[4]}".replace("//", "/")
                row["path"] = f"{m[1]}{m[3]}{m[4]}".replace("//", "/")
            else:
                row["old_path"], row["path"] = path.split(" => ", 1)
        rows.append(row)
    return rows


def parse_name_status(out: str) -> dict[str, str]:
    """``git diff --name-status`` → {path: A|M|D|R|C}."""
    status = {}
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            status[parts[-1]] = parts[0][:1]
    return status


class RepoBrowser:
    def __init__(self, repo: Path, base_branch: callable):
        self.repo = repo
        self._base = base_branch

    def _git(self, *args: str, timeout: int = 60) -> str:
        if not git_ops.is_repo(self.repo):
            raise RepoError(f"repo not mounted at {self.repo}", 503)
        try:
            return git_ops.git(self.repo, *args, timeout=timeout)
        except git_ops.GitError as exc:
            raise RepoError(str(exc), 404 if "unknown revision" in str(exc) or "does not exist" in str(exc)
                            or "bad revision" in str(exc) or "not a tree" in str(exc) else 400)

    def base(self) -> str:
        try:
            return self._base()
        except Exception:
            return "HEAD"

    # ── refs ───────────────────────────────────────────────────────────────
    def branches(self) -> dict[str, Any]:
        base = self.base()
        current = self._git("rev-parse", "--abbrev-ref", "HEAD")
        fmt = _FS.join(["%(refname:short)", "%(objectname)", "%(committerdate:iso-strict)",
                        "%(authorname)", "%(subject)", "%(upstream:short)"]) + _RS
        out = self._git("for-each-ref", "--sort=-committerdate", f"--format={fmt}", "refs/heads")
        rows = []
        for rec in out.split(_RS):
            f = rec.strip("\n").split(_FS)
            if len(f) < 6:
                continue
            name = f[0]
            ahead = behind = 0
            if name != base:
                try:
                    counts = self._git("rev-list", "--left-right", "--count", f"{base}...{name}").split()
                    behind, ahead = int(counts[0]), int(counts[1])
                except (RepoError, ValueError, IndexError):
                    pass
            rows.append({"name": name, "sha": f[1], "date": f[2], "author": f[3], "subject": f[4],
                         "upstream": f[5] or None, "current": name == current, "base": name == base,
                         "forge_task": name.split("/")[-1] if name.startswith("auto/forge/") else None,
                         "ahead": ahead, "behind": behind})
        return {"base": base, "current": current, "branches": rows}

    def tags(self) -> dict[str, Any]:
        fmt = _FS.join(["%(refname:short)", "%(objectname:short)", "%(creatordate:iso-strict)", "%(subject)"]) + _RS
        out = self._git("for-each-ref", "--sort=-creatordate", f"--format={fmt}", "refs/tags")
        tags = []
        for rec in out.split(_RS):
            f = rec.strip("\n").split(_FS)
            if len(f) >= 4:
                tags.append({"name": f[0], "sha": f[1], "date": f[2], "subject": f[3]})
        return {"tags": tags}

    # ── history ────────────────────────────────────────────────────────────
    _LOG_FMT = _FS.join(["%H", "%h", "%P", "%an", "%ae", "%aI", "%s", "%D"]) + _RS

    def _parse_log(self, out: str) -> list[dict[str, Any]]:
        commits = []
        for rec in out.split(_RS):
            f = rec.strip("\n").split(_FS)
            if len(f) < 8:
                continue
            commits.append({"sha": f[0], "short": f[1], "parents": f[2].split() if f[2] else [],
                            "author": f[3], "email": f[4], "date": f[5], "subject": f[6],
                            "refs": [r.strip() for r in f[7].split(",") if r.strip()]})
        return commits

    def log(self, ref: str | None = None, path: str | None = None, limit: int = 100,
            skip: int = 0, all_refs: bool = False) -> dict[str, Any]:
        limit = max(1, min(int(limit), 500))
        args = ["log", f"--format={self._LOG_FMT}", f"-n{limit}", f"--skip={max(0, int(skip))}", "--date-order"]
        args += ["--branches", "--tags"] if all_refs else [_ref(ref)]
        p = _path(path)
        if p:
            args += ["--", p]
        commits = self._parse_log(self._git(*args))
        return {"ref": "all" if all_refs else _ref(ref), "path": p, "skip": skip, "limit": limit,
                "commits": commits, "has_more": len(commits) == limit}

    def commit(self, sha: str) -> dict[str, Any]:
        sha = str(sha or "").strip()
        if not (_SHA.match(sha) or _REF.match(sha)):
            raise RepoError(f"invalid commit {sha!r}")
        fmt = _FS.join(["%H", "%h", "%P", "%an", "%ae", "%aI", "%cn", "%cI", "%s", "%b", "%D"])
        f = self._git("show", "-s", f"--format={fmt}", sha).split(_FS)
        if len(f) < 11:
            raise RepoError(f"commit {sha} not found", 404)
        parents = f[2].split() if f[2] else []
        # Merge commit: diff against the first parent (what the merge brought in).
        base = parents[0] if parents else "4b825dc642cb6eb9a060e54bf8d69288fbee4904"  # empty tree
        numstat = self._git("diff", "--numstat", "-M", base, f[0])
        status = parse_name_status(self._git("diff", "--name-status", "-M", base, f[0]))
        files = parse_numstat(numstat)
        for row in files:
            row["status"] = status.get(row["path"], "M")
        diff, truncated = _clip(self._git("diff", "-M", base, f[0], timeout=120), _MAX_DIFF)
        return {"sha": f[0], "short": f[1], "parents": parents, "author": f[3], "email": f[4], "date": f[5],
                "committer": f[6], "committed": f[7], "subject": f[8], "body": f[9].strip(),
                "refs": [r.strip() for r in f[10].strip().split(",") if r.strip()],
                "files": files, "diff": diff, "truncated": truncated}

    def compare(self, base: str | None, head: str | None) -> dict[str, Any]:
        b, h = _ref(base, self.base()), _ref(head)
        counts = self._git("rev-list", "--left-right", "--count", f"{b}...{h}").split()
        commits = self._parse_log(self._git("log", f"--format={self._LOG_FMT}", "-n300", f"{b}..{h}"))
        files = parse_numstat(self._git("diff", "--numstat", "-M", f"{b}...{h}"))
        status = parse_name_status(self._git("diff", "--name-status", "-M", f"{b}...{h}"))
        for row in files:
            row["status"] = status.get(row["path"], "M")
        diff, truncated = _clip(self._git("diff", "-M", f"{b}...{h}", timeout=120), _MAX_DIFF)
        return {"base": b, "head": h, "behind": int(counts[0]), "ahead": int(counts[1]),
                "commits": commits, "files": files, "diff": diff, "truncated": truncated}

    # ── files ──────────────────────────────────────────────────────────────
    def tree(self, ref: str | None = None, path: str | None = None) -> dict[str, Any]:
        r, p = _ref(ref), _path(path)
        out = self._git("ls-tree", "-l", "-z", r, *([p + "/"] if p else []))
        entries = []
        for rec in out.split("\0"):
            if not rec:
                continue
            meta, name = rec.split("\t", 1)
            mode, kind, sha, size = meta.split()
            entries.append({"name": PurePosixPath(name).name, "path": name, "type": kind, "sha": sha,
                            "size": None if size == "-" else int(size), "secret": _secret(name)})
        entries.sort(key=lambda e: (e["type"] != "tree", e["name"].lower()))
        return {"ref": r, "path": p, "entries": entries}

    def file(self, ref: str | None, path: str | None) -> dict[str, Any]:
        r, p = _ref(ref), _path(path)
        if not p:
            raise RepoError("path required")
        if _secret(p):
            raise RepoError("secret files are never served", 403)
        size = int(self._git("cat-file", "-s", f"{r}:{p}") or 0)
        raw = git_ops.git(self.repo, "show", f"{r}:{p}", timeout=60) if size <= _MAX_FILE * 4 else ""
        binary = "\0" in raw[:8000]
        content, truncated = ("", False) if binary else _clip(raw, _MAX_FILE)
        return {"ref": r, "path": p, "size": size, "binary": binary, "content": content,
                "truncated": truncated or size > _MAX_FILE * 4}

    # ── dossiers (docs/work) ───────────────────────────────────────────────
    def dossiers(self, ref: str | None = None) -> dict[str, Any]:
        r = _ref(ref)
        try:
            tree = self.tree(r, "docs/work")["entries"]
        except RepoError:
            return {"ref": r, "dossiers": []}
        rows = []
        for entry in tree:
            if entry["type"] != "tree":
                continue
            row = {"name": entry["name"], "path": entry["path"], "version": None, "status": None, "source": None,
                   "title": None, "progress": None}
            try:
                spec = git_ops.git(self.repo, "show", f"{r}:{entry['path']}/SPEC.md", timeout=20)
                row.update(spec_header(spec))
            except git_ops.GitError:
                pass
            try:
                prog = git_ops.git(self.repo, "show", f"{r}:{entry['path']}/PROGRESS.md", timeout=20)
                done, total = prog.count("- [x]") + prog.count("- [X]"), len(re.findall(r"- \[[ xX]\]", prog))
                row["progress"] = {"done": done, "total": total}
            except git_ops.GitError:
                pass
            rows.append(row)
        rows.sort(key=lambda d: d["name"], reverse=True)
        return {"ref": r, "dossiers": rows}


def spec_header(spec: str) -> dict[str, Any]:
    """Title + Version/Source/Status from a SPEC.md header table."""
    out: dict[str, Any] = {}
    m = re.search(r"^#\s+(.+)$", spec, re.M)
    if m:
        out["title"] = m[1].strip()
    for key in ("Version", "Source", "Status"):
        m = re.search(rf"^\|\s*\*\*{key}\*\*\s*\|\s*(.+?)\s*\|\s*$", spec, re.M)
        if m:
            out[key.lower()] = m[1].strip()
    return out
