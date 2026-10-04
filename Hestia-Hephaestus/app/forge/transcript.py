"""Task artifacts for the WebUI "Sviluppo" page.

Every Forge task gets a folder ``<data>/forge/tasks/<id>/``:

- ``transcript.jsonl`` — the engine conversation in ONE normalized format
  (Claude Code stream-json and the built-in local/cloud agent both end up here);
- ``tests.txt``        — full pytest output of Forge's own test run;
- ``engine.log``       — engine stderr / tool log;
- ``deploy.log``       — deploy command output.

Normalized transcript event (one JSON object per line)::

    {"i": 0, "ts": "...", "kind": "user|text|thinking|tool_use|tool_result|system|result|error",
     "text": "...", "tool": "Edit", "id": "toolu_..", "input": {...}, "is_error": false, "meta": {...}}

While a Claude run is going, Oracle writes the raw stream-json to the shared
mount (``<worktrees>/.transcripts/<id>.jsonl``): it is normalized on read, so
the page shows the run live. After the run it is normalized once and stored.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger("hestia_hephaestus.forge.transcript")

_MAX_TEXT = 20_000
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{4,64}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clip(text: Any, limit: int = _MAX_TEXT) -> str:
    text = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + f"\n...[cut {len(text) - limit} chars]"


def _tool_result_text(content: Any) -> str:
    """Claude tool_result content is a string or a list of {type:text|image}."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(block.get("text") if block.get("type") == "text" else f"[{block.get('type')}]")
        return "\n".join(p for p in parts if p)
    return "" if content is None else str(content)


def normalize_claude(raw_events: Iterable[dict]) -> list[dict]:
    """Claude Code ``--output-format stream-json`` lines → normalized events."""
    out: list[dict] = []
    for ev in raw_events:
        kind = ev.get("type")
        ts = ev.get("timestamp") or ""
        if kind == "system":
            if ev.get("subtype") == "init":
                out.append({"kind": "system", "ts": ts, "text": "Sessione Claude Code avviata",
                            "meta": {"model": ev.get("model"), "cwd": ev.get("cwd"),
                                     "tools": ev.get("tools"), "session_id": ev.get("session_id"),
                                     "permission_mode": ev.get("permissionMode")}})
            continue
        if kind in ("assistant", "user"):
            msg = ev.get("message") or {}
            content = msg.get("content")
            if isinstance(content, str):
                out.append({"kind": "text" if kind == "assistant" else "user", "ts": ts, "text": _clip(content)})
                continue
            for block in content or []:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text" and str(block.get("text") or "").strip():
                    out.append({"kind": "text" if kind == "assistant" else "user", "ts": ts,
                                "text": _clip(block.get("text"))})
                elif btype in ("thinking", "redacted_thinking"):
                    out.append({"kind": "thinking", "ts": ts,
                                "text": _clip(block.get("thinking") or "[ragionamento oscurato]")})
                elif btype == "tool_use":
                    out.append({"kind": "tool_use", "ts": ts, "tool": block.get("name"), "id": block.get("id"),
                                "input": block.get("input") or {}})
                elif btype == "tool_result":
                    out.append({"kind": "tool_result", "ts": ts, "id": block.get("tool_use_id"),
                                "text": _clip(_tool_result_text(block.get("content"))),
                                "is_error": bool(block.get("is_error"))})
            continue
        if kind == "result":
            out.append({"kind": "result" if not ev.get("is_error") else "error", "ts": ts,
                        "text": _clip(ev.get("result") or ev.get("subtype") or ""),
                        "is_error": bool(ev.get("is_error")),
                        "meta": {"turns": ev.get("num_turns"), "cost_usd": ev.get("total_cost_usd"),
                                 "duration_ms": ev.get("duration_ms"), "subtype": ev.get("subtype"),
                                 "usage": ev.get("usage")}})
            continue
        if kind == "clipped":
            out.append({"kind": "system", "ts": ts, "text": _clip(ev.get("text"))})
    _link_tool_names(out)
    return out


def _link_tool_names(events: list[dict]) -> None:
    """tool_result → name of the tool_use it answers (handy for the UI)."""
    names = {e.get("id"): e.get("tool") for e in events if e.get("kind") == "tool_use"}
    for e in events:
        if e.get("kind") == "tool_result" and not e.get("tool"):
            e["tool"] = names.get(e.get("id"))


def read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if isinstance(obj, dict):
                    rows.append(obj)
    except FileNotFoundError:
        pass
    return rows


class TaskArtifacts:
    """Per-task files under ``<base>/<task_id>/`` (see module docstring)."""

    def __init__(self, base: Path, worktrees: Path):
        self.base = base
        self.worktrees = worktrees

    def dir(self, task_id: str) -> Path:
        if not _SAFE_ID.match(str(task_id or "")):
            raise ValueError(f"bad task id {task_id!r}")
        return self.base / task_id

    def live_claude_path(self, task_id: str) -> Path:
        return self.worktrees / ".transcripts" / f"{task_id}.jsonl"

    # ── transcript ─────────────────────────────────────────────────────────
    def start_transcript(self, task_id: str, prompt: str, engine: str) -> None:
        d = self.dir(task_id)
        d.mkdir(parents=True, exist_ok=True)
        (d / "transcript.jsonl").unlink(missing_ok=True)
        self.append(task_id, {"kind": "system", "text": f"Motore: {engine}", "meta": {"engine": engine}})
        self.append(task_id, {"kind": "user", "text": _clip(prompt, 60_000), "meta": {"role": "task_prompt"}})

    def append(self, task_id: str, event: dict) -> None:
        try:
            d = self.dir(task_id)
            d.mkdir(parents=True, exist_ok=True)
            event = {"ts": event.get("ts") or _now(), **{k: v for k, v in event.items() if k != "ts"}}
            with (d / "transcript.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
        except Exception as exc:
            logger.debug("event=forge_transcript_append_failed task_id=%s error=%s", task_id, exc)

    def import_claude(self, task_id: str, raw_path: str | Path | None = None) -> int:
        """After a Claude run: normalize Oracle's raw stream-json into transcript.jsonl."""
        path = Path(raw_path) if raw_path else self.live_claude_path(task_id)
        events = normalize_claude(read_jsonl(path))
        for ev in events:
            self.append(task_id, ev)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return len(events)

    def transcript(self, task_id: str, offset: int = 0, limit: int = 500) -> dict[str, Any]:
        """Stored events + (while a Claude run is going) the live raw stream, normalized."""
        stored = read_jsonl(self.dir(task_id) / "transcript.jsonl")
        live_path = self.live_claude_path(task_id)
        live = live_path.exists()
        events = stored + (normalize_claude(read_jsonl(live_path)) if live else [])
        for i, ev in enumerate(events):
            ev["i"] = i
        offset = max(0, int(offset))
        limit = max(1, min(int(limit), 2000))
        return {"total": len(events), "offset": offset, "live": live, "events": events[offset:offset + limit]}

    # ── plain text files ───────────────────────────────────────────────────
    def write_text(self, task_id: str, name: str, text: str) -> None:
        try:
            d = self.dir(task_id)
            d.mkdir(parents=True, exist_ok=True)
            (d / name).write_text(text or "", encoding="utf-8")
        except Exception as exc:
            logger.debug("event=forge_artifact_write_failed task_id=%s name=%s error=%s", task_id, name, exc)

    def read_text(self, task_id: str, name: str, max_chars: int = 400_000) -> str:
        try:
            text = (self.dir(task_id) / name).read_text(encoding="utf-8", errors="replace")
        except (FileNotFoundError, ValueError):
            return ""
        return text if len(text) <= max_chars else text[-max_chars:]
