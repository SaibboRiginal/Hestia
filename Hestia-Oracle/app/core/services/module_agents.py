"""Module agents — operating mode ``agents`` (dossier ``docs/work/2026-11-06-moduli-come-agenti``).

Each module that offers tools gets a specialist agent INSIDE Oracle: its ``when_to_use`` (what it is for), its
``manual`` (its rules) and only its own tools. The main brain no longer holds ~265 tools: it sees one tool
``agent_<module>(task)`` per module and hands out jobs. Every agent reasons with the chain of its own use case
``agent.<module>`` (Models page; no chain of its own = «General use»), through the LLM bus like every local call.

- **Writes** stay in the agent (the module owns its data) with every gate of the turn: the tools were already
  wrapped by the origin gate and ``TurnGuards(owner's message)`` before grouping, so a job text written by the main
  brain can never turn the owner's question into a write.
- **Depth 1**: an agent never calls another agent; if it needs another module it says so and the main brain asks.
- **Turn board**: an agent that finishes posts one line; agents read the board at every step, so with one local
  worker (calls queue on the bus) a later agent sees what an earlier one found.
- **Direct answer**: an agent's ``answer`` is the reply when it was the turn's only call (``ToolDefinition.direct``).
- Frames ``{"type": "agent", ...}`` (``stream_emitter.emit_agent``): ``start`` · ``tool`` · ``end``.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from core.agent_loop import ToolDefinition

logger = logging.getLogger("hestia_oracle.module_agents")

TOOL_PREFIX = "agent_"
USECASE_PREFIX = "agent."
# Cross-cutting tools the main brain keeps itself (reminders and routines are asked in any conversation).
MAIN_TOOLS = frozenset({"agenda_assistente_aggiungi", "routine_create", "ask_user"})
# Replaced by the agents: the manual lives in each agent's prompt.
DROPPED_TOOLS = frozenset({"module_manual"})
_SUMMARY_CHARS = 240


@dataclass
class AgentSpec:
    module: str
    when: str
    manual: str = ""
    title: str = ""
    tools: list[ToolDefinition] = field(default_factory=list)

    @property
    def tool_name(self) -> str:
        return f"{TOOL_PREFIX}{self.module}"

    @property
    def use_case(self) -> str:
        return f"{USECASE_PREFIX}{self.module}"

    @property
    def label(self) -> str:
        return self.title or self.module.capitalize()


class TurnBoard:
    """One line per finished agent job of this turn (thread-safe)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._lines: list[str] = []

    def post(self, module: str, text: str) -> None:
        line = " ".join(str(text or "").split())[:_SUMMARY_CHARS]
        if line:
            with self._lock:
                self._lines.append(f"- {module}: {line}")

    def text(self) -> str:
        with self._lock:
            return "\n".join(self._lines)


def group(tools: list[ToolDefinition], guides: dict[str, dict]) -> tuple[list[ToolDefinition], list[AgentSpec]]:
    """Split the turn's tools: Oracle's own + cross-cutting ones stay with the main brain, every module tool goes to
    its module's agent. A module with tools and no ``when_to_use`` still gets an agent (described by its name)."""
    main: list[ToolDefinition] = []
    by_module: dict[str, list[ToolDefinition]] = {}
    for t in tools:
        if t.name in DROPPED_TOOLS:
            continue
        svc = str(getattr(t, "service", "") or "").strip().lower()
        if not svc or svc == "oracle" or t.name in MAIN_TOOLS:
            main.append(t)
        else:
            by_module.setdefault(svc, []).append(t)
    specs = []
    for module in sorted(by_module):
        g = guides.get(module) or {}
        specs.append(AgentSpec(module=module, when=str(g.get("when") or f"tools of the {module} module"),
                               manual=str(g.get("manual") or ""), title=str(g.get("title") or ""),
                               tools=by_module[module]))
    return main, specs


def history_tail(history_text: str, messages: int) -> str:
    """Last *messages* lines of the conversation text (one message per line in ``ContextBuilder``)."""
    if messages <= 0 or not history_text:
        return ""
    lines = [ln for ln in str(history_text).splitlines() if ln.strip()]
    return "\n".join(lines[-messages:])


def instructions(spec: AgentSpec, *, owner_message: str, origin_line: str = "", datetime_context: str = "") -> str:
    """Fixed part of an agent's prompt (caveman: paid every step). The board is added live at every step."""
    parts = [f"YOU ARE THE {spec.module.upper()} AGENT of the assistant. Job area: {spec.when}.",
             "Use only your tools. Do the job, then answer in 1-4 short sentences in the owner's language, "
             "as the assistant speaking to the owner: first line = result or blocker; no preamble, no recap of "
             "your steps. Never claim an action no tool confirmed. "
             "Write only when the owner asked or told something to record. "
             "Job outside your area or needing another module: say which, do not guess."]
    if spec.manual:
        parts.append(f"RULES OF YOUR MODULE:\n{spec.manual}")
    parts.append(f"OWNER'S OWN WORDS: {owner_message}")
    if origin_line:
        parts.append(origin_line)
    if datetime_context:
        parts.append(f"CURRENT_DATETIME_CONTEXT:\n{datetime_context}")
    return "\n\n".join(parts)


def main_instructions() -> str:
    """Line for the main brain: how to use the agents."""
    return ("MODULE AGENTS: each agent_<module>(task) tool is a specialist with its own tools. Small talk or what "
            "you know: answer yourself, no tool. Owner's data or actions: give the job to the right agent, task = "
            "full self-contained request with every detail the owner gave. Several areas: call several agents "
            "in the same step. Never invent what an agent did.")


@dataclass
class AgentRun:
    """What the engine needs to run one agent job."""
    run_loop: Callable[..., tuple[str, list[str], list[dict]]]   # core.agent_loop.run_agent_loop
    chain_for: Callable[[str], object]                            # use case → ChainAgent
    emit: Callable[[str], None]                                   # NDJSON line sink (live stream)
    emit_frame: Callable[..., str]                                # stream_emitter.emit_agent
    owner_message: str
    history_text: str
    preference_facts: list[str]
    board: TurnBoard
    nested_log: list[dict]
    think: object = False
    steps: int = 8
    history_messages: int = 6
    max_agents: int = 4
    origin_line: str = ""
    datetime_context: str = ""
    guard_checker: Callable | None = None
    _count: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _next_id(self) -> int | None:
        with self._lock:
            if self._count >= self.max_agents:
                return None
            self._count += 1
            return self._count

    def tool_for(self, spec: AgentSpec) -> ToolDefinition:
        return ToolDefinition(
            name=spec.tool_name,
            description=f"Agent: {spec.when}"[:200],
            parameters={"type": "object", "properties": {
                "task": {"type": "string", "description": "Full self-contained job for this agent"}},
                "required": ["task"]},
            handler=lambda task="", **_kw: self.run(spec, str(task or "")),
            title=spec.label, direct=True)

    def run(self, spec: AgentSpec, task: str) -> tuple[bool, dict | str]:
        n = self._next_id()
        if n is None:
            return False, f"LIMIT: at most {self.max_agents} agents per answer. Answer with what you have."
        agent_id = f"a{n}"
        chain = self.chain_for(spec.use_case)
        model, provider = getattr(chain, "model_name", ""), getattr(chain, "provider", "")
        t0 = time.perf_counter()
        logger.info("event=agent_start agent_id=%s module=%s tools=%d model=%s provider=%s task_len=%d",
                    agent_id, spec.module, len(spec.tools), model, provider, len(task))
        self.emit(self.emit_frame("start", agent_id=agent_id, module=spec.module, label=spec.label, task=task,
                                  model=model, provider=provider))

        def _on_thinking(line: str) -> None:
            try:
                frame = json.loads(line)
            except (TypeError, ValueError):
                return
            if frame.get("action") == "tool_result":
                meta = frame.get("metadata") or {}
                self.emit(self.emit_frame("tool", agent_id=agent_id, module=spec.module, label=spec.label,
                                          tool=str(frame.get("tool") or ""), ok=bool(meta.get("ok")),
                                          ms=int(meta.get("duration_ms") or 0)))

        board = self.board
        try:
            answer, _tokens, log = self.run_loop(
                user_message=task,
                history_text=history_tail(self.history_text, self.history_messages),
                preference_facts=self.preference_facts,
                tools=list(spec.tools),
                ask_fn=lambda p: chain.ask(p, thinking=self.think),
                ask_tools_fn=lambda p, tm: chain.ask_with_tools(p, tm, thinking=self.think),
                stream_fn=None,
                client_instructions=instructions(spec, owner_message=self.owner_message,
                                                 origin_line=self.origin_line,
                                                 datetime_context=self.datetime_context),
                max_turns=self.steps,
                on_thinking=_on_thinking,
                guard_checker=self.guard_checker,
                live_notes=lambda: (f"TURN BOARD (other agents' results):\n{board.text()}" if board.text() else ""),
            )
        except Exception as exc:
            ms = int((time.perf_counter() - t0) * 1000)
            logger.warning("[🔄] event=agent_failed agent_id=%s module=%s ms=%d error=%s",
                           agent_id, spec.module, ms, str(exc)[:200])
            self.emit(self.emit_frame("end", agent_id=agent_id, module=spec.module, label=spec.label, ok=False,
                                      summary="", ms=ms))
            return False, f"The {spec.module} agent failed: {str(exc)[:200]}"
        ms = int((time.perf_counter() - t0) * 1000)
        for entry in log:
            entry.setdefault("agent", spec.module)
        with self._lock:
            self.nested_log.extend(log)
        answer = str(answer or "").strip()
        board.post(spec.module, answer)
        ask = next((e.get("ask") for e in log if e.get("ask")), None)
        logger.info("event=agent_done agent_id=%s module=%s ms=%d tools=%d answer_len=%d asked=%s",
                    agent_id, spec.module, ms, len(log), len(answer), bool(ask))
        self.emit(self.emit_frame("end", agent_id=agent_id, module=spec.module, label=spec.label, ok=True,
                                  summary=answer[:_SUMMARY_CHARS], ms=ms, tools=len(log)))
        out: dict = {"answer": answer}
        if ask:
            out["ask"] = ask   # the turn stops on the agent's question like on the main brain's
        return True, out
