"""«Copy for AI» of the Development page (SPEC docs/work/2026-10-18-core-modules-and-external-mcp §B5).

Markdown of some Forge tasks for an AI working elsewhere (claude.ai, a PC checkout…): request, state, error,
dossier path and how to hand a fix back through Hestia's MCP (forge_task_note / forge_submit_branch). Built from the
same views as the MCP tools forge_tasks (``brief``) and forge_task (``overview``), so both paths say the same thing.
Returned to the browser only (clipboard or .md download): nothing is written to the repo — task text can carry
personal data and the repo is public.
"""
from __future__ import annotations

from typing import Any

MAX_EXPORT = 50

_STATE_EN = {
    "new": "new", "proposed": "to approve", "scheduled": "scheduled", "queued": "queued",
    "running": "in progress", "awaiting_review": "diff to review", "approved": "merging",
    "merging": "merging", "merged": "applied", "deployed": "in production", "failed": "failed",
    "rejected": "rejected", "rolled_back": "undone (rollback)", "no_changes": "no changes",
}


def _clip(text: Any, n: int) -> str:
    s = str(text or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _task_md(t: dict, branch_states: set[str], user_sources: set[str]) -> list[str]:
    tid = str(t.get("id") or "")
    state = str(t.get("state") or "?")
    out = [f"## Task `{tid[:6]}` — {_STATE_EN.get(state, state)}", ""]
    out.append(f"- **Id**: `{tid}`")
    out.append(f"- **State**: `{state}`")
    src = t.get("source") or "user"
    out.append(f"- **Origin**: {'proposed by ' + str(src) if src not in user_sources else 'asked by the owner'}"
               f" (via {src})")
    if t.get("engine"):
        out.append(f"- **Engine**: {t['engine']}")
    services = t.get("services") or t.get("touched_services") or []
    if services:
        out.append(f"- **Services**: {', '.join(map(str, services))}")
    if t.get("workdoc"):
        out.append(f"- **Dossier**: `docs/work/{t['workdoc']}/` (SPEC.md, PROGRESS.md, CHANGELOG.md)")
    if t.get("branch"):
        out.append(f"- **Forge branch**: `{t['branch']}`")
    if t.get("merge_sha"):
        out.append(f"- **Merge**: `{str(t['merge_sha'])[:12]}`")
    if t.get("parent_task"):
        out.append(f"- **Follows task**: `{str(t['parent_task'])[:6]}`")
    tests = t.get("tests")
    if isinstance(tests, dict) and tests.get("ok") is not None:
        out.append(f"- **Tests**: {'passed' if tests.get('ok') else 'failed'}")
    out += ["", "### Request", "", str(t.get("request") or "").strip() or "(empty)", ""]
    if t.get("context"):
        out += ["### Context", "", str(t["context"]).strip(), ""]
    if t.get("error"):
        out += ["### Error", "", "```", _clip(t["error"], 3000), "```", ""]
    if isinstance(tests, dict) and tests.get("ok") is False and tests.get("tail"):
        out += ["### Test tail", "", "```", _clip(tests["tail"], 1500), "```", ""]
    if t.get("summary"):
        out += ["### Engine summary", "", _clip(t["summary"], 2000), ""]
    ext = t.get("external_branch")
    if isinstance(ext, dict) and ext.get("branch"):
        out += ["### Branch already delivered", "",
                f"`{ext['branch']}` from {ext.get('by') or '?'} ({ext.get('at') or ''}): {_clip(ext.get('summary'), 500)}", ""]
    notes = t.get("notes") or []
    if notes:
        out += ["### Notes", ""]
        out += [f"- {n.get('at') or n.get('ts') or ''} · {n.get('by') or '?'}: {_clip(n.get('text'), 800)}"
                for n in notes[-10:] if isinstance(n, dict)]
        out.append("")
    history = t.get("history") or []
    if history:
        out += ["### Latest steps", ""]
        out += [f"- {h.get('ts') or ''} · {h.get('state') or ''}" + (f" — {_clip(h.get('note'), 200)}" if h.get("note") else "")
                for h in history[-6:] if isinstance(h, dict)]
        out.append("")
    out += ["### How to deliver a fix", ""]
    out.append(f"- Up-to-date details: MCP `forge_task(task_id=\"{tid[:6]}\")`"
               + (f", dossier `forge_dossier(name=\"{t['workdoc']}\")`" if t.get("workdoc") else "")
               + (", diff `forge_task_diff`" if t.get("branch") else "") + ".")
    out.append(f"- Analysis or directions: `forge_task_note(task_id=\"{tid[:6]}\", text=\"…\")` — the engine uses it when the task starts or is retried.")
    if state in branch_states:
        out.append(f"- Fix ready: push a branch to origin (not `auto/forge/*`), then `forge_submit_branch(task_id=\"{tid[:6]}\", branch=\"<name>\", summary=\"…\")`. Forge runs its tests and asks the owner for approval; merge, restart and rollback stay with Forge.")
    else:
        out.append(f"- In state `{state}` Forge does not accept a branch: deliverable only in {', '.join(sorted(branch_states))}. Leave a note.")
    out.append("")
    return out


def export_markdown(tasks: list[dict], brief_lines: list[str], branch_states: set[str],
                    user_sources: set[str], missing: list[str] | None = None) -> str:
    """``tasks`` = forge_task views (``router.overview``), ``brief_lines`` = forge_tasks lines of the same tasks."""
    out = ["# Hestia development task (Forge)", "",
           "Hestia develops itself with Forge (Hephaestus). Work following the repo's `CLAUDE.md`: dossier in `docs/work/<name>/` (SPEC, PROGRESS, CHANGELOG), tests with pytest, no secrets in files. Approval, merge and rollback are done only by Forge after the owner's ok.", ""]
    if brief_lines:
        out += ["Summary:", ""] + [f"- {line}" for line in brief_lines] + [""]
    for t in tasks:
        out += _task_md(t, branch_states, user_sources)
    if missing:
        out += [f"_Tasks not found: {', '.join(missing)}_", ""]
    return "\n".join(out).rstrip() + "\n"
