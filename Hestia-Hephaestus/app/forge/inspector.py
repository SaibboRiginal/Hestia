"""Per-task detail for the WebUI "Sviluppo" page: changed files, diff, dossier,
tests, logs, timeline.  Read-only; works for live tasks (worktree on disk:
uncommitted changes included) and for finished ones (git objects in the repo)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import git_ops
from .repo_browser import parse_name_status, parse_numstat

_MAX_DIFF = 300_000
_MAX_DOC = 200_000


class TaskInspector:
    def __init__(self, forge):
        self.forge = forge

    @property
    def repo(self) -> Path:
        return self.forge.cfg.repo_path

    def _task(self, task_id: str) -> dict:
        return self.forge._require(task_id)

    def _source(self, task: dict) -> tuple[Path, str, str | None]:
        """(git dir, base, head) — head None = working tree of the live worktree."""
        base = task.get("base_sha") or ""
        worktree = Path(task.get("worktree") or "")
        if task.get("worktree") and worktree.is_dir():
            return worktree, base, None
        return self.repo, base, task.get("commit_sha")

    # ── changes ────────────────────────────────────────────────────────────
    def files(self, task_id: str, with_diff: bool = True) -> dict[str, Any]:
        task = self._task(task_id)
        where, base, head = self._source(task)
        if not base or (head is None and where == self.repo):
            return {"task_id": task["id"], "live": False, "files": [], "diff": "", "truncated": False}
        spec = [base] if head is None else [f"{base}...{head}"]
        try:
            files = parse_numstat(git_ops.git(where, "diff", "--numstat", "-M", *spec))
            status = parse_name_status(git_ops.git(where, "diff", "--name-status", "-M", *spec))
            diff = git_ops.git(where, "diff", "-M", *spec, timeout=120) if with_diff else ""
            untracked = (git_ops.git(where, "ls-files", "--others", "--exclude-standard").splitlines()
                         if head is None else [])
        except git_ops.GitError as exc:
            return {"task_id": task["id"], "live": head is None, "files": [], "diff": "", "error": str(exc)[:500]}
        for row in files:
            row["status"] = status.get(row["path"], "M")
        for path in untracked:
            files.append({"path": path, "added": None, "deleted": None, "binary": False, "status": "?"})
        truncated = len(diff) > _MAX_DIFF
        return {"task_id": task["id"], "live": head is None, "base": base, "head": head or "worktree",
                "files": files, "diff": diff[:_MAX_DIFF], "truncated": truncated,
                "totals": {"files": len(files), "added": sum(f.get("added") or 0 for f in files),
                           "deleted": sum(f.get("deleted") or 0 for f in files)}}

    # ── dossier ────────────────────────────────────────────────────────────
    def workdoc(self, task_id: str) -> dict[str, Any]:
        """docs/work/<workdoc>/*.md + every other .md the task changed."""
        task = self._task(task_id)
        name = task.get("workdoc") or ""
        where, _base, head = self._source(task)
        ref = head or (None if where != self.repo else task.get("merge_sha") or task.get("base_branch"))
        docs: list[dict[str, Any]] = []
        folder = f"docs/work/{name}" if name else ""

        def read(path: str) -> str | None:
            if ref is None:
                target = where / path
                try:
                    return target.read_text(encoding="utf-8", errors="replace")[:_MAX_DOC]
                except (FileNotFoundError, IsADirectoryError):
                    return None
            try:
                return git_ops.git(self.repo, "show", f"{ref}:{path}", timeout=20)[:_MAX_DOC]
            except git_ops.GitError:
                return None

        if folder:
            if ref is None:
                d = where / folder
                names = sorted(p.name for p in d.glob("*.md")) if d.is_dir() else []
            else:
                try:
                    names = sorted(Path(p).name for p in git_ops.git(
                        self.repo, "ls-tree", "--name-only", f"{ref}:{folder}").splitlines() if p.endswith(".md"))
                except git_ops.GitError:
                    names = []
            order = {"SPEC.md": 0, "PROGRESS.md": 1, "CHANGELOG.md": 2}
            for fname in sorted(names, key=lambda n: (order.get(n, 9), n)):
                content = read(f"{folder}/{fname}")
                if content is not None:
                    docs.append({"path": f"{folder}/{fname}", "name": fname, "group": "dossier", "content": content})
        changed = [f["path"] for f in self.files(task_id, with_diff=False).get("files", [])]
        for path in changed:
            if path.lower().endswith(".md") and not (folder and path.startswith(folder + "/")):
                content = read(path)
                if content is not None:
                    docs.append({"path": path, "name": Path(path).name, "group": "changed", "content": content})
        return {"task_id": task["id"], "workdoc": name or None, "ref": ref or "worktree", "docs": docs}

    # ── tests / logs / timeline ────────────────────────────────────────────
    def tests(self, task_id: str) -> dict[str, Any]:
        task = self._task(task_id)
        t = task.get("tests") or {}
        output = self.forge.artifacts.read_text(task["id"], "tests.txt") or str(t.get("output_tail") or "")
        return {"task_id": task["id"], "ok": t.get("ok"), "ran": bool(t), "output": output,
                "summary": _pytest_summary(output)}

    def logs(self, task_id: str) -> dict[str, Any]:
        task = self._task(task_id)
        a = self.forge.artifacts
        return {"task_id": task["id"],
                "engine": a.read_text(task["id"], "engine.log") or str(task.get("engine_log_tail") or ""),
                "deploy": a.read_text(task["id"], "deploy.log") or str((task.get("deploy") or {}).get("output_tail") or ""),
                "error": task.get("error"),
                "hint": f"Log dei container: docker logs hestia_hephaestus / hestia_oracle (event=forge_* task_id={task['id']})"}

    def events(self, task_id: str) -> dict[str, Any]:
        task = self._task(task_id)
        return {"task_id": task["id"], "state": task.get("state"), "events": list(task.get("history") or [])}


def _pytest_summary(output: str) -> dict[str, Any]:
    """Counts from the pytest final line ("3 passed, 1 failed in 2.1s")."""
    import re
    out: dict[str, Any] = {}
    tail = output[-2000:]
    for count, word in re.findall(r"(\d+) (passed|failed|errors?|skipped|deselected|xfailed|xpassed)", tail):
        out["error" if word.startswith("error") else word] = int(count)
    failed = re.findall(r"^FAILED (\S+)", output, re.M)
    if failed:
        out["failed_tests"] = failed[:50]
    return out
