"""Sandboxed file/test tools for the built-in coding agent.

All paths are resolved inside the task worktree; ``.git`` and secret files are
off limits.  Shell access is limited to the configured test command.
"""
from __future__ import annotations

import fnmatch
import shlex
import subprocess
from pathlib import Path
from typing import Any, Callable

_MAX_READ_LINES = 400
_MAX_OUT = 6000
_FORBIDDEN_PARTS = {".git"}
_FORBIDDEN_NAMES = {".env", "credentials.json", "google_token.json", "token.json"}


class ToolError(Exception):
    pass


def _clip(text: str, limit: int = _MAX_OUT) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n...[cut {len(text) - limit} chars]"


class AgentTools:
    def __init__(self, root: Path, test_runner: Callable[[list[str] | None], tuple[bool | None, str]]):
        self.root = root.resolve()
        self._test_runner = test_runner
        self.finished_summary: str | None = None

    # ── schema exposed to the LLM (OpenAI tools format) ────────────────────
    @staticmethod
    def schemas() -> list[dict[str, Any]]:
        def fn(name: str, desc: str, props: dict, required: list[str]) -> dict:
            return {"type": "function", "function": {
                "name": name, "description": desc,
                "parameters": {"type": "object", "properties": props, "required": required}}}

        s = {"type": "string"}
        return [
            fn("list_files", "List repo files. Optional dir prefix + glob.",
               {"path": s, "glob": s}, []),
            fn("read_file", "Read file with line numbers. Max 400 lines per call.",
               {"path": s, "start": {"type": "integer"}, "end": {"type": "integer"}}, ["path"]),
            fn("search", "Regex search in repo (git grep). Returns file:line:text.",
               {"pattern": s, "path": s}, ["pattern"]),
            fn("write_file", "Create or overwrite whole file.",
               {"path": s, "content": s}, ["path", "content"]),
            fn("edit_file", "Replace exact unique text in file.",
               {"path": s, "old": s, "new": s}, ["path", "old", "new"]),
            fn("run_tests", "Run pytest for given test dirs/files (default: changed services).",
               {"paths": {"type": "array", "items": s}}, []),
            fn("finish", "End task. Give short summary.", {"summary": s}, ["summary"]),
        ]

    # ── dispatch ───────────────────────────────────────────────────────────
    def call(self, name: str, args: dict[str, Any]) -> str:
        handler = getattr(self, f"t_{name}", None)
        if handler is None:
            return f"ERROR unknown tool {name}"
        try:
            return handler(**(args or {}))
        except ToolError as exc:
            return f"ERROR {exc}"
        except TypeError as exc:
            return f"ERROR bad args: {exc}"

    def _path(self, rel: str) -> Path:
        rel = str(rel or ".").strip().lstrip("/")
        target = (self.root / rel).resolve()
        if target != self.root and self.root not in target.parents:
            raise ToolError("path outside repo")
        parts = set(target.relative_to(self.root).parts)
        if parts & _FORBIDDEN_PARTS or target.name in _FORBIDDEN_NAMES or "data" in parts:
            raise ToolError("path forbidden")
        return target

    def _git_files(self) -> list[str]:
        out = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(self.root), "ls-files",
                              "--cached", "--others", "--exclude-standard"],
                             capture_output=True, text=True, timeout=30).stdout
        return [line for line in out.splitlines() if line]

    # ── tools ──────────────────────────────────────────────────────────────
    def t_list_files(self, path: str = "", glob: str = "") -> str:
        prefix = str(path or "").strip().strip("/")
        files = [f for f in self._git_files() if not prefix or f.startswith(prefix + "/") or f == prefix]
        if glob:
            files = [f for f in files if fnmatch.fnmatch(f, glob) or fnmatch.fnmatch(Path(f).name, glob)]
        more = f"\n...+{len(files) - 300} more" if len(files) > 300 else ""
        return "\n".join(files[:300]) + more or "(no files)"

    def t_read_file(self, path: str, start: int = 1, end: int | None = None) -> str:
        target = self._path(path)
        if not target.is_file():
            raise ToolError(f"not a file: {path}")
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, int(start or 1))
        end = min(len(lines), int(end) if end else start + _MAX_READ_LINES - 1, start + _MAX_READ_LINES - 1)
        body = "\n".join(f"{i}\t{lines[i - 1]}" for i in range(start, end + 1))
        tail = f"\n[lines {start}-{end} of {len(lines)}]"
        return _clip(body + tail, 20000)

    def t_search(self, pattern: str, path: str = "") -> str:
        cmd = ["git", "-c", "safe.directory=*", "-C", str(self.root), "grep", "-n", "-I", "-E", pattern]
        if path:
            cmd += ["--", str(path).strip("/")]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout
        lines = out.splitlines()
        more = f"\n...+{len(lines) - 80} more" if len(lines) > 80 else ""
        return _clip("\n".join(lines[:80]) + more) or "(no match)"

    def t_write_file(self, path: str, content: str) -> str:
        target = self._path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"OK wrote {path} ({len(content.splitlines())} lines)"

    def t_edit_file(self, path: str, old: str, new: str) -> str:
        target = self._path(path)
        if not target.is_file():
            raise ToolError(f"not a file: {path}")
        text = target.read_text(encoding="utf-8")
        count = text.count(old)
        if count == 0:
            raise ToolError("old text not found (read file again, copy exact text)")
        if count > 1:
            raise ToolError(f"old text found {count} times, add more context")
        target.write_text(text.replace(old, new, 1), encoding="utf-8")
        return f"OK edited {path}"

    def t_run_tests(self, paths: list[str] | None = None) -> str:
        if paths:
            for p in paths:
                self._path(p)
        ok, output = self._test_runner(paths)
        status = "PASS" if ok else ("NO TESTS" if ok is None else "FAIL")
        return f"{status}\n{output[-4000:]}"  # tail: the pytest summary is at the end

    def t_finish(self, summary: str) -> str:
        self.finished_summary = str(summary or "").strip() or "done"
        return "OK finished"


def run_test_command(root: Path, template: str, paths: list[str], timeout: int = 900) -> tuple[bool | None, str]:
    """Run the configured test command.  Returns (ok, output); ok=None if no paths."""
    if not paths:
        return None, "no test paths for changed services"
    cmd = template.replace("{test_paths}", " ".join(shlex.quote(p) for p in paths))
    try:
        proc = subprocess.run(cmd, shell=True, cwd=str(root), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"tests timed out after {timeout}s"
    output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    # pytest exit 5 = no tests collected (e.g. marker filter) -> not a failure
    if proc.returncode == 5:
        return None, output[-3000:]
    return proc.returncode == 0, output[-60000:]  # full-ish: shown in the Sviluppo page
