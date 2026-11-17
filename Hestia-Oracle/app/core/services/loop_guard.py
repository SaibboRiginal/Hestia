"""Loop guard for the agent loop (Cindy idea 1, dossier docs/work/2026-10-24-tutto-brainstorm-cindy).

Local models often call the same tool again and again and burn every turn. Before the turn cap, a deterministic
detector looks at the fingerprints (tool name + arguments) of the calls of this answer:

- **repetition**: the same call N times in a row (``oracle.agent.rounds.repeats``, default 4);
- **ping-pong**: A-B-A-B… inside the last ``oracle.agent.rounds.window`` calls (at least 3 rounds);
- **loop**: the same sequence of 3-4 calls repeated 3 times inside the window.

Real waits do not count: a repeated call made at least ``oracle.agent.rounds.wait_seconds`` after the previous
one («I'll check again shortly») resets the run. On a suspicion an optional light check (use case
``oracle.check_rounds``) decides «waiting» or «spinning», at most ``oracle.agent.rounds.checks``
times per answer; no checker, a failure or the limit = stop. Always on: the tunables only shape it.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Callable

logger = logging.getLogger("hestia_oracle.loop_guard")

GUARD_REPEAT = "oracle.agent.rounds.repeats"
GUARD_WINDOW = "oracle.agent.rounds.window"
GUARD_WAIT = "oracle.agent.rounds.wait_seconds"
GUARD_CHECKS = "oracle.agent.rounds.checks"
CHECK_USECASE = "oracle.check_rounds"

STOP_MESSAGE = ("[SYSTEM]: you are repeating the same calls with no progress. Call no more tools: "
                "answer now with what you have, and say what you could not get.")


def fingerprint(name: str, params: dict | None) -> str:
    try:
        args = json.dumps(params or {}, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        args = str(params)
    return f"{name}|{args}"


@dataclass
class LoopGuard:
    repeat: int = 4
    window: int = 12
    wait_seconds: float = 30.0
    max_checks: int = 3
    checker: Callable[[list[str]], str] | None = None
    calls: list[tuple[str, float]] = field(default_factory=list)
    checks: int = 0
    reason: str = ""

    @classmethod
    def from_settings(cls, checker: Callable[[list[str]], str] | None = None) -> "LoopGuard":
        from core.services import oracle_settings as s
        return cls(repeat=s.get_int(GUARD_REPEAT, 2), window=s.get_int(GUARD_WINDOW, 6),
                   wait_seconds=float(s.get_int(GUARD_WAIT, 0)), max_checks=s.get_int(GUARD_CHECKS, 0),
                   checker=checker)

    # ── detection ────────────────────────────────────────────────────────
    def _same_run(self) -> bool:
        if len(self.calls) < self.repeat:
            return False
        tail = self.calls[-self.repeat:]
        if len({fp for fp, _ in tail}) != 1:
            return False
        # a real wait between two of them («I'll check again shortly») is not a loop
        return all(b - a < self.wait_seconds for (_, a), (_, b) in zip(tail, tail[1:]))

    def _ping_pong(self) -> bool:
        tail = [fp for fp, _ in self.calls[-self.window:]]
        if len(tail) < 6:
            return False
        last = tail[-6:]
        a, b = last[-2], last[-1]
        return a != b and all(fp == (a if i % 2 == 0 else b) for i, fp in enumerate(last))

    def _rotation(self) -> bool:
        tail = [fp for fp, _ in self.calls[-max(self.window, 12):]]
        for size in (3, 4):
            if len(tail) < size * 3:
                continue
            seq = tail[-size:]
            if len(set(seq)) != size:
                continue
            if tail[-size * 3:] == seq * 3:
                return True
        return False

    def suspect(self) -> str:
        if self._same_run():
            return "repetition"
        if self._ping_pong():
            return "ping-pong"
        if self._rotation():
            return "loop"
        return ""

    # ── public ───────────────────────────────────────────────────────────
    def add(self, name: str, params: dict | None, at: float | None = None) -> bool:
        """Record one call; True = the loop must stop calling tools."""
        self.calls.append((fingerprint(name, params), time.time() if at is None else at))
        kind = self.suspect()
        if not kind:
            return False
        recent = [fp for fp, _ in self.calls[-self.window:]]
        if self.checker is not None and self.checks < self.max_checks:
            self.checks += 1
            try:
                verdict = str(self.checker(recent) or "").strip().lower()
            except Exception as exc:  # timeout / no model: stop is the safe side
                logger.warning("[🔄] event=agent_loop_guard_check_failed kind=%s error=%s fallback=stop", kind,
                               str(exc)[:160])
                verdict = "loop"
            if verdict.startswith("aspett") or verdict.startswith("wait"):
                logger.info("event=agent_loop_guard_waiting kind=%s checks=%d", kind, self.checks)
                # keep only the last call: a new run must build up again before the next suspicion
                self.calls = self.calls[-1:]
                return False
        self.reason = kind
        logger.warning("event=agent_loop_suspected kind=%s calls=%d checks=%d tool=%s", kind, len(self.calls),
                       self.checks, self.calls[-1][0].split("|", 1)[0])
        return True


def check_prompt(recent: list[str]) -> str:
    """Caveman prompt for the light check."""
    lines = "\n".join(f"- {fp[:200]}" for fp in recent[-12:])
    return ("Last tool calls of an agent:\n" + lines +
            "\nIs it WAITING for something that changes (e.g. a job status) or LOOPING for nothing? "
            "Reply only: wait | loop")


def llm_checker(recent: list[str]) -> str:
    from core.services import llm_chains
    return llm_chains.agent_for(CHECK_USECASE).ask(check_prompt(recent), thinking=False)
