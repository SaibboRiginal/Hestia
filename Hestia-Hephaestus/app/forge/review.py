"""Automatic review and team plan for Forge tasks (dossier docs/work/2026-10-24-whole-brainstorm-cindy W3).

- **Reviewer** (Cindy 3): after Forge's own tests, a fresh model with no memory of the work and no tools (Oracle
  ``/api/llm/generate``, use case ``forge.revisione``) gets only labelled evidence: the request, the acceptance
  criteria of the dossier SPEC, the diff and the real test output. The engine's own story is marked «unverified
  self-declaration». It answers with prioritised issues; blocking ones (alta/media) go back to the engine for one
  automatic round of fixes. The owner still approves: the review only means less work for them.
- **Team plan** (Cindy 31): a large task (≥ ``hephaestus.forge.squadra.min_servizi`` services) is split by the
  model (use case ``forge.piano``) into up to 4 pieces run one after the other in the same worktree, each with the
  engine its difficulty asks for (semplice → the local chain, difficile → Claude), then the reviewer on the result.
Never blocking: when the model is not reachable the step is skipped with a ``[🔄]`` log.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import requests
from hestia_common.i18n import t as tr  # fixed texts in the owner's language

logger = logging.getLogger("hestia_hephaestus.forge.review")

REVIEW_USECASE = "forge.revisione"
PLAN_USECASE = "forge.piano"
BLOCKING = ("alta", "media")
MAX_PIECES = 4
_DIFF_CHARS = 40000

REVIEW_PROMPT = """You are an independent code reviewer. You did not write this code.
Check ONLY against the evidence below. The author's summary is an unverified self-declaration.
Look for: bugs, unmet requirements, missing tests for new behaviour, broken repo rules
(no direct service-to-service URL, no new env vars for tunables, no personal data).
Reply ONLY JSON: {"verdict": "ok" | "issues", "issues": [{"priority": "high"|"medium"|"low",
"file": "...", "problem": "...", "evidence": "line or test that proves it"}]}. No problem = verdict ok, issues [].
Write problem and evidence in {owner_language}.

## Request
{request}

## Acceptance criteria (SPEC)
{acceptance}

## Tests (real result)
{tests}

## Unverified self-declaration of the author
{summary}

## Diff
{diff}
"""

PLAN_PROMPT = """Split this development work into 2-4 pieces done one after the other in the same repository.
Each piece: short title, what to do (complete instructions), difficulty "easy" or "hard", services touched.
If the work is small reply with one piece. Reply ONLY JSON:
{"pieces": [{"title": "...", "request": "...", "difficulty": "easy"|"hard", "services": ["..."]}]}

Work: {request}
Services: {services}
"""

# Model answers in English; stored values stay the ones the rest of Forge (and its cards) already use.
_PRIORITY = {"high": "alta", "medium": "media", "low": "bassa", "alta": "alta", "media": "media", "bassa": "bassa"}
_HARD = ("hard", "difficile")


def _owner_language() -> str:
    try:
        from hestia_common import identity, i18n
        from .forge_settings import settings as hs
        return identity.LANGUAGES[i18n.language(hs.get)]
    except Exception:  # noqa: BLE001
        return "the owner's language"


def parse_json(text: str) -> dict | None:
    """The first JSON object in a model answer (fenced or bare)."""
    if not text:
        return None
    match = re.search(r"\{.*\}", str(text), re.S)
    if not match:
        return None
    try:
        out = json.loads(match.group(0))
    except ValueError:
        return None
    return out if isinstance(out, dict) else None


def acceptance_from_workdoc(worktree: Path, workdoc: str) -> str:
    """Acceptance criteria section of the task dossier SPEC, if the engine wrote it."""
    spec = Path(worktree) / "docs" / "work" / str(workdoc or "") / "SPEC.md"
    try:
        text = spec.read_text(encoding="utf-8")
    except OSError:
        return "(no SPEC found)"
    match = re.search(r"^#+\s*(acceptance|criteri)[^\n]*\n(.*?)(?=^#+\s|\Z)", text, re.I | re.M | re.S)
    return (match.group(2) if match else text)[:4000].strip() or "(empty)"


class ForgeReviewer:
    def __init__(self, hub_api_url: str, timeout: int = 300):
        self.hub = hub_api_url.rstrip("/")
        self.timeout = timeout

    def _generate(self, use_case: str, prompt: str) -> str | None:
        try:
            resp = requests.post(f"{self.hub}/route/oracle/api/llm/generate",
                                 json={"method": "POST", "headers": {}, "query": {},
                                       "body": {"prompt": prompt, "use_case": use_case},
                                       "timeout_seconds": self.timeout},
                                 timeout=self.timeout + 5)
            routed = resp.json() if resp.content else {}
            if resp.status_code != 200 or int(routed.get("status_code", 500)) >= 400:
                raise RuntimeError(f"status {routed.get('status_code', resp.status_code)}")
            payload = routed.get("payload")
            return str(payload.get("response") or payload.get("text") or "") if isinstance(payload, dict) \
                else str(payload or "")
        except Exception as exc:  # noqa: BLE001
            logger.warning("[🔄] event=forge_review_model_failed use_case=%s error=%s fallback=skip", use_case, exc)
            return None

    # ── review ──────────────────────────────────────────────────────────────
    def review(self, *, request: str, acceptance: str, diff: str, tests: str, summary: str) -> dict[str, Any]:
        prompt = (REVIEW_PROMPT.replace("{owner_language}", _owner_language()).replace("{request}", request[:3000]).replace("{acceptance}", acceptance[:4000])
                  .replace("{tests}", (tests or "(no tests)")[-4000:]).replace("{summary}", summary[:2000])
                  .replace("{diff}", diff[:_DIFF_CHARS]))
        answer = self._generate(REVIEW_USECASE, prompt)
        data = parse_json(answer or "")
        if answer is None or data is None:
            return {"verdict": "non_disponibile", "issues": [], "blocking": 0}
        issues = []
        for i in data.get("issues") or []:
            if isinstance(i, dict) and str(i.get("problem") or "").strip():
                prio = _PRIORITY.get(str(i.get("priority") or "medium").lower(), "media")
                issues.append({"priority": prio,
                               "file": str(i.get("file") or "")[:200], "problem": str(i["problem"])[:600],
                               "evidence": str(i.get("evidence") or "")[:400]})
        blocking = sum(1 for i in issues if i["priority"] in BLOCKING)
        verdict = "problemi" if issues else "ok"
        logger.info("event=forge_review_done verdict=%s issues=%d blocking=%d", verdict, len(issues), blocking)
        return {"verdict": verdict, "issues": issues, "blocking": blocking}

    # ── plan ────────────────────────────────────────────────────────────────
    def plan(self, request: str, services: list[str]) -> list[dict]:
        answer = self._generate(PLAN_USECASE, PLAN_PROMPT.replace("{request}", request[:4000])
                                .replace("{services}", ", ".join(services) or "-"))
        data = parse_json(answer or "") or {}
        pieces = []
        for p in data.get("pieces") or []:
            if isinstance(p, dict) and str(p.get("request") or "").strip():
                pieces.append({"title": str(p.get("title") or p["request"])[:120],
                               "request": str(p["request"])[:4000],
                               "difficulty": "difficile" if str(p.get("difficulty") or "hard").lower() in _HARD else "semplice",
                               "services": [str(s) for s in p.get("services") or []][:10]})
        return pieces[:MAX_PIECES]


def fix_prompt(issues: list[dict]) -> str:
    lines = [f"- [{i['priority']}] {i['file']}: {i['problem']}" + (f" (evidence: {i['evidence']})" if i['evidence'] else "")
             for i in issues]
    return ("An independent automatic review found these issues in this task's work. "
            "Fix the real ones; if one is a false alarm leave the code as it is and say why in the final summary. "
            "Then run the tests again.\n" + "\n".join(lines))


def card(review: dict) -> str:
    """Italian lines for the owner (no module names)."""
    verdict = review.get("verdict")
    if verdict == "non_disponibile":
        return tr("Automatic review: not available now.")
    if verdict == "ok":
        return tr("Automatic review: no problem found.")
    rounds = review.get("rounds") or 0
    head = tr("Automatic review: {0} points", len(review['issues'])) + (tr(" (after a round of fixes)") if rounds else "")
    rows = [f"• {i['priority']} · {i['file'] or '-'}: {i['problem'][:160]}" for i in review["issues"][:5]]
    return "\n".join([head, *rows])
