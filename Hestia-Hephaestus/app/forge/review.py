"""Automatic review and team plan for Forge tasks (dossier docs/work/2026-10-24-tutto-brainstorm-cindy W3).

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

logger = logging.getLogger("hestia_hephaestus.forge.review")

REVIEW_USECASE = "forge.revisione"
PLAN_USECASE = "forge.piano"
BLOCKING = ("alta", "media")
MAX_PIECES = 4
_DIFF_CHARS = 40000

REVIEW_PROMPT = """Sei un revisore di codice indipendente. Non hai scritto tu questo codice.
Controlla SOLO con le prove qui sotto. Il riassunto di chi ha scritto il codice è un'autodichiarazione non verificata.
Cerca: bug, requisiti non soddisfatti, test mancanti per il comportamento nuovo, regole del repo violate
(nessun URL diretto tra servizi, niente nuove variabili env per valori regolabili, niente dati personali).
Rispondi SOLO JSON: {"verdict": "ok" | "problemi", "issues": [{"priority": "alta"|"media"|"bassa",
"file": "...", "problem": "...", "evidence": "riga o test che lo prova"}]}. Nessun problema = verdict ok, issues [].

## Richiesta
{request}

## Criteri di accettazione (SPEC)
{acceptance}

## Test (risultato vero)
{tests}

## Autodichiarazione non verificata di chi ha scritto il codice
{summary}

## Diff
{diff}
"""

PLAN_PROMPT = """Dividi questo lavoro di sviluppo in 2-4 pezzi da fare uno dopo l'altro nello stesso repository.
Ogni pezzo: titolo breve, cosa fare (istruzioni complete), difficoltà "semplice" o "difficile", servizi toccati.
Se il lavoro è piccolo rispondi con un solo pezzo. Rispondi SOLO JSON:
{"pieces": [{"title": "...", "request": "...", "difficulty": "semplice"|"difficile", "services": ["..."]}]}

Lavoro: {request}
Servizi: {services}
"""


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
        return "(nessuna SPEC trovata)"
    match = re.search(r"^#+\s*(acceptance|criteri)[^\n]*\n(.*?)(?=^#+\s|\Z)", text, re.I | re.M | re.S)
    return (match.group(2) if match else text)[:4000].strip() or "(vuota)"


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
        prompt = (REVIEW_PROMPT.replace("{request}", request[:3000]).replace("{acceptance}", acceptance[:4000])
                  .replace("{tests}", (tests or "(nessun test)")[-4000:]).replace("{summary}", summary[:2000])
                  .replace("{diff}", diff[:_DIFF_CHARS]))
        answer = self._generate(REVIEW_USECASE, prompt)
        data = parse_json(answer or "")
        if answer is None or data is None:
            return {"verdict": "non_disponibile", "issues": [], "blocking": 0}
        issues = []
        for i in data.get("issues") or []:
            if isinstance(i, dict) and str(i.get("problem") or "").strip():
                prio = str(i.get("priority") or "media").lower()
                issues.append({"priority": prio if prio in ("alta", "media", "bassa") else "media",
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
                               "difficulty": "semplice" if p.get("difficulty") == "semplice" else "difficile",
                               "services": [str(s) for s in p.get("services") or []][:10]})
        return pieces[:MAX_PIECES]


def fix_prompt(issues: list[dict]) -> str:
    lines = [f"- [{i['priority']}] {i['file']}: {i['problem']}" + (f" (prova: {i['evidence']})" if i['evidence'] else "")
             for i in issues]
    return ("Una revisione automatica indipendente ha trovato questi problemi nel lavoro di questo task. "
            "Correggi quelli veri; se uno è un falso allarme lascia il codice com'è e spiegalo nel riassunto finale. "
            "Poi rilancia i test.\n" + "\n".join(lines))


def card(review: dict) -> str:
    """Italian lines for the owner (no module names)."""
    verdict = review.get("verdict")
    if verdict == "non_disponibile":
        return "Revisione automatica: non disponibile ora."
    if verdict == "ok":
        return "Revisione automatica: nessun problema trovato."
    rounds = review.get("rounds") or 0
    head = f"Revisione automatica: {len(review['issues'])} punti" + (" (dopo un giro di correzioni)" if rounds else "")
    rows = [f"• {i['priority']} · {i['file'] or '-'}: {i['problem'][:160]}" for i in review["issues"][:5]]
    return "\n".join([head, *rows])
