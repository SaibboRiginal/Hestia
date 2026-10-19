"""Usage rows: one per LLM call, pushed to Archive (dossier ``docs/work/2026-10-19-oracle-a-blocchi`` §E).

A chain step runs inside ``step(...)``: the provider's token counts (``llm_stats.record``) land in the step's
context, and when the step ends ``finish`` builds the row: time, module (prefix of the use case), client and
session (bound by the chat stream), use case, chain, step index, provider, model, tokens, context window,
duration, cost and outcome (ok / quota / error). A call made outside a chain (Claude Code runner, agent loop)
still gets a row from ``llm_stats.record`` with its agent label as use case.

Rows go to Archive (store ``llm-usage``) through Hub in small batches on one background worker, started by the
first row (push, no timer); a failed send is logged and dropped (usage is not worth retrying). Archive removes
rows older than ``oracle.usage.retention_days`` on each write. ``GET /api/llm/usage`` reads the sums back.
"""
from __future__ import annotations

import contextvars
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

logger = logging.getLogger("hestia_oracle.llm_usage")

STORE = "api/llm-usage-store"
_BATCH = 200
_MAX_PENDING = 5000
_ctx: contextvars.ContextVar[dict | None] = contextvars.ContextVar("llm_usage_step", default=None)
_client: contextvars.ContextVar[str] = contextvars.ContextVar("llm_usage_client", default="")
_lock = threading.Lock()
_pending: list[dict] = []
_scheduled = False
_executor: ThreadPoolExecutor | None = None


# ── context ──────────────────────────────────────────────────────────────────

def bind_client(client: str) -> contextvars.Token:
    return _client.set(str(client or ""))


def reset_client(token: contextvars.Token) -> None:
    _client.reset(token)


@contextmanager
def step(use_case: str, chain: str, index: int, provider: str, model: str) -> Iterator[dict]:
    """Run one chain step with its usage context bound (token counts collected into it)."""
    ctx = {"use_case": use_case, "chain": chain, "step": index, "provider": provider, "model": model,
           "stats": [], "t0": time.monotonic(), "elapsed": 0.0}
    token = _ctx.set(ctx)
    try:
        yield ctx
    finally:
        _ctx.reset(token)


def resume(ctx: dict):
    """Bind *ctx* again (stream steps: each ``next()`` may run in another context)."""
    return _ctx.set(ctx)


def suspend(token) -> None:
    _ctx.reset(token)


def on_stats(label: str, row: dict) -> None:
    """Called by ``llm_stats.record`` for every call: collected by the running step, else pushed as is."""
    ctx = _ctx.get()
    if ctx is not None:
        ctx["stats"].append(row)
        return
    use_case = _label_usecase(label)
    push(_row(use_case, "", 0, row.get("provider", ""), row.get("model", ""), [row],
              duration_ms=int(row.get("prompt_ms", 0)) + int(row.get("output_ms", 0)) + int(row.get("load_ms", 0)),
              outcome="ok"))


def finish(ctx: dict, outcome: str = "ok", detail: str = "") -> dict:
    """Build and push the row of a finished step."""
    duration = int((time.monotonic() - ctx["t0"]) * 1000)
    row = _row(ctx["use_case"], ctx["chain"], ctx["step"], ctx["provider"], ctx["model"], ctx["stats"],
               duration_ms=duration, outcome=outcome, detail=detail)
    push(row)
    return row


def _label_usecase(label: str) -> str:
    from core.services.llm_chains import SLOTS
    label = str(label or "").strip()
    return SLOTS.get(label, label if "." in label else f"oracle.{label or 'generale'}")


def _session() -> str:
    from core.services import llm_stats
    return llm_stats.current_session()


def _row(use_case: str, chain: str, index: int, provider: str, model: str, stats: list[dict], *,
         duration_ms: int, outcome: str, detail: str = "") -> dict:
    inp = sum(int(s.get("prompt_tokens") or 0) for s in stats)
    cached = sum(int(s.get("cached_tokens") or 0) for s in stats)
    out = sum(int(s.get("output_tokens") or 0) for s in stats)
    reported = sum(float(s.get("cost_usd") or 0) for s in stats)
    cost, kind = price(provider, model, inp, cached, out, reported) if stats else (0.0, "")
    return {"at": datetime.now(timezone.utc).isoformat(), "module": use_case.split(".", 1)[0] or "oracle",
            "use_case": use_case, "chain": chain or None, "step": int(index or 0), "provider": provider or None,
            "model": model or None, "client": _client.get() or None, "session_id": _session() or None,
            "input_tokens": inp, "cached_tokens": cached, "output_tokens": out,
            "context_window": _window(provider), "duration_ms": max(0, int(duration_ms)),
            "cost_usd": round(cost, 6), "cost_kind": kind or None, "outcome": outcome,
            "detail": (detail or "")[:300] or None}


def _window(provider: str) -> int:
    from core.services import llm_providers, oracle_settings
    try:
        if llm_providers.type_of(provider) == "ollama" or provider == "ollama":
            return int(oracle_settings.context_window())
    except Exception:
        pass
    return 0


def price(provider: str, model: str, inp: int, cached: int, out: int, reported: float = 0.0) -> tuple[float, str]:
    """(cost in $, kind): Claude subscription → its own equivalent cost, «abbonamento»; a cost the provider
    reported → «api»; a provider that costs nothing (local) → 0, «locale»; else ``oracle.pricing``."""
    from core.services import llm_gateway, llm_providers, oracle_settings
    ptype = llm_providers.type_of(provider)
    if ptype == "claude_cli":
        return reported, "abbonamento"
    if reported:
        return reported, "api"
    if not llm_gateway.billed(provider):
        return 0.0, "locale"
    table = oracle_settings.settings.get(oracle_settings.PRICING_KEY, {}) or {}
    rates = table.get(f"{provider}/{model}") or table.get(model) if isinstance(table, dict) else None
    if not isinstance(rates, dict):
        return 0.0, "sconosciuto"
    try:
        rate_in, rate_out = float(rates.get("in") or 0), float(rates.get("out") or 0)
        rate_cached = float(rates.get("cached", rate_in) or 0)
    except (TypeError, ValueError):
        return 0.0, "sconosciuto"
    fresh = max(0, inp - cached)
    return (fresh * rate_in + cached * rate_cached + out * rate_out) / 1_000_000, "api"


# ── push to Archive ──────────────────────────────────────────────────────────

def push(row: dict) -> None:
    global _scheduled, _executor
    with _lock:
        if len(_pending) >= _MAX_PENDING:
            del _pending[: len(_pending) - _MAX_PENDING + 1]
        _pending.append(row)
        if _scheduled:
            return
        _scheduled = True
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="llm-usage")
        executor = _executor
    executor.submit(_drain)


def _drain() -> None:
    global _scheduled
    while True:
        with _lock:
            batch = _pending[:_BATCH]
            del _pending[:_BATCH]
            if not batch:
                _scheduled = False
                return
        try:
            _send(batch)
        except Exception as exc:
            logger.warning("[🔄] event=llm_usage_push_failed rows=%d error=%s fallback=dropped", len(batch), exc)


def _retention() -> int:
    from core.services import oracle_settings
    try:
        return max(1, int(oracle_settings.settings.get(oracle_settings.USAGE_RETENTION, 90) or 90))
    except (TypeError, ValueError):
        return 90


def _hub():
    from core.services.hub_client import HubClient
    return HubClient(os.getenv("HUB_API_URL", "http://hestia_hub:19001/api"))


def _send(rows: list[dict]) -> None:
    ok, payload = _hub().route_to_service("archive", f"{STORE}/rows", "POST",
                                          body={"rows": rows, "retention_days": _retention()}, timeout=10)
    if not ok:
        raise RuntimeError(str(payload)[:200])


def flush() -> None:
    """Send what is pending now (tests, shutdown)."""
    _drain()


# ── read back ────────────────────────────────────────────────────────────────

def query(path: str, params: dict[str, Any]) -> Any:
    """GET from the Archive store (``summary`` or ``rows``)."""
    ok, payload = _hub().route_to_service("archive", f"{STORE}/{path}", "GET",
                                          query={k: v for k, v in params.items() if v not in (None, "")})
    if not ok:
        raise RuntimeError(str(payload)[:200] or "archive unreachable")
    return payload
