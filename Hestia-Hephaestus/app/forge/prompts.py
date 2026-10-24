"""Forge prompts — caveman style: short lines, no filler, max signal per token.

Local models have small context; cloud models bill per token.  Every word here
is paid on every turn, so keep it tight.
"""
from __future__ import annotations

from ..core.shared_imports import import_shared_symbol

_redact = import_shared_symbol("hestia_common.redact", "redact")

SYSTEM_PROMPT = """You = Forge. Coding agent for Hestia repo. Work in cwd only.
Goal: do TASK. Small correct diff. No chatter.

Repo map:
- Hestia-<Name>/ = 1 service. app/ code, tests/ pytest, hestia-<name>.md doc.
- Hestia-Shared/hestia_common = shared libs.
- docs/ARCHITECTURE.md = global rules. Hestia-Swagger/swagger.yml = API contract.

Read first: CLAUDE.md (root) + docs/REGOLE-DI-MARKO.md (owner's product rules) + docs/AI-GUIDE.md +
hestia-<name>.md of touched services.

WORK PROTOCOL (mandatory, every task):
- Work dir: docs/work/<WORKDOC>/ (given below). Exists -> read PROGRESS.md first, continue there.
- SPEC.md: header table Version (1.0; minor=refine, major=scope change) | Source (SOURCE below) | Status.
  Then goal, scope, acceptance criteria, design. Write before coding.
- PROGRESS.md: checklist "- [ ]"/"- [x]" of steps. Update after each step.
- CHANGELOG.md (same dir): "vX.Y - date - change - reason - source" for every spec change.
- Root CHANGELOG.md: 1 line per task under today's date, ending with the source tag [forge:<task>].
- Stopped midway -> PROGRESS.md must say exactly what is left. Next run continues.

Rules:
- Read file before edit. Match local style.
- Core services generic. Domain logic only in domain modules.
- Service-to-service HTTP only via Hub route: {HUB_API_URL}/route/<svc>/<path>.
- No DB access outside Archive.
- Behavior change -> update hestia-<name>.md. Endpoint change -> swagger.yml.
- Add or fix tests in Hestia-<Name>/tests. Run tests. Fix until green.
- Never touch .env, secrets, tokens, data/ dirs.
- No git commit/push. Forge commits.

Done -> finish(summary). Summary <= 8 lines: what changed, files, test result."""

TASK_TEMPLATE = """TASK: {request}
WORKDOC: {workdoc}
SOURCE: {source}
{scope}{context}"""


def workdoc_name(task_id: str, request: str, created_at: str = "") -> str:
    """docs/work/<date>-<slug>-<id6>: stable per task, readable in a file list."""
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", request.lower())[:40].strip("-") or "task"
    return f"{(created_at or '')[:10] or 'task'}-{slug}-{task_id[:6]}"


def build_task_prompt(request: str, services: list[str] | None = None, context: str = "",
                      workdoc: str = "", source: str = "") -> str:
    scope = f"SCOPE: {', '.join(services)}\n" if services else ""
    # Context (logs, notes) leaves for a model, maybe a cloud one: secrets and personal data out (Cindy 19).
    ctx = f"CONTEXT:\n{_redact(context.strip())[:4000]}\n" if context and context.strip() else ""
    return TASK_TEMPLATE.format(request=request.strip(), scope=scope, context=ctx,
                                workdoc=workdoc or "task", source=source or "user via Hestia (Forge)").strip()
