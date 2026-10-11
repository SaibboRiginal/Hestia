"""Per-call LLM runtime stats: real prompt size, prompt-cache reuse, load time, speed.

Fed by every provider from what the server already returns (Ollama ``prompt_eval_count`` /
``load_duration``, OpenAI-compatible ``usage`` + llama-server ``timings``, Anthropic ``usage``).
Kept in memory as a short rolling window per agent label; exposed by ``/api/chat/context``.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any

logger = logging.getLogger("hestia_oracle.llm_stats")

_WINDOW = 50
_lock = threading.Lock()
_calls: dict[str, deque] = {}


def _ms(ns: Any) -> int:
    try:
        return int(int(ns or 0) / 1_000_000)
    except (TypeError, ValueError):
        return 0


def record(label: str, provider: str, model: str, *, prompt_tokens: int, cached_tokens: int = 0,
           load_ms: int = 0, prompt_ms: int = 0, output_tokens: int = 0, output_ms: int = 0,
           estimated: bool = False) -> dict:
    """Store one call and log ``event=llm_call_stats``. Returns the row."""
    prompt_tokens = max(0, int(prompt_tokens or 0))
    cached_tokens = max(0, min(int(cached_tokens or 0), prompt_tokens))
    row = {
        "at": time.time(), "provider": provider, "model": model,
        "prompt_tokens": prompt_tokens, "cached_tokens": cached_tokens,
        "load_ms": int(load_ms or 0), "prompt_ms": int(prompt_ms or 0),
        "output_tokens": int(output_tokens or 0), "output_ms": int(output_ms or 0),
        "estimated": bool(estimated),
    }
    label = label or "generic"
    with _lock:
        _calls.setdefault(label, deque(maxlen=_WINDOW)).append(row)
    cache_pct = round(100 * cached_tokens / prompt_tokens, 1) if prompt_tokens else 0.0
    tok_s = round(row["output_tokens"] / (row["output_ms"] / 1000), 1) if row["output_ms"] else 0.0
    logger.info(
        "event=llm_call_stats agent=%s provider=%s model=%s prompt_tokens=%d cached_tokens=%d "
        "cache_hit_pct=%.1f estimated=%s load_ms=%d prompt_ms=%d output_tokens=%d tok_per_s=%.1f",
        label, provider, model, prompt_tokens, cached_tokens, cache_pct, row["estimated"],
        row["load_ms"], row["prompt_ms"], row["output_tokens"], tok_s)
    return row


def record_ollama(label: str, model: str, data: dict, prompt_chars: int) -> dict | None:
    """From an Ollama final response. ``prompt_eval_count`` counts only the tokens Ollama had to
    evaluate (a reused KV prefix is skipped), so the full prompt size is estimated from its length."""
    if not isinstance(data, dict) or "prompt_eval_count" not in data and "eval_count" not in data:
        return None
    evaluated = int(data.get("prompt_eval_count") or 0)
    from core.agent_loop import TokenCounter  # lazy: agent_loop imports prompt_config only

    total = max(evaluated, TokenCounter(model).estimate("x" * max(0, prompt_chars)))
    return record(label, "ollama", model, prompt_tokens=total, cached_tokens=total - evaluated,
                  load_ms=_ms(data.get("load_duration")), prompt_ms=_ms(data.get("prompt_eval_duration")),
                  output_tokens=int(data.get("eval_count") or 0), output_ms=_ms(data.get("eval_duration")),
                  estimated=True)


def record_openai(label: str, model: str, data: dict) -> dict | None:
    """From an OpenAI-compatible response: ``usage`` (+ ``prompt_tokens_details.cached_tokens``)
    and, on llama-server, ``timings`` (``cache_n``, ``prompt_n``, ``prompt_ms``, ``predicted_*``)."""
    if not isinstance(data, dict):
        return None
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    timings = data.get("timings") if isinstance(data.get("timings"), dict) else {}
    if not usage and not timings:
        return None
    details = usage.get("prompt_tokens_details") if isinstance(usage.get("prompt_tokens_details"), dict) else {}
    cached = int(details.get("cached_tokens") or timings.get("cache_n") or 0)
    prompt = int(usage.get("prompt_tokens") or 0)
    if timings.get("prompt_n") is not None:
        prompt = max(prompt, int(timings.get("prompt_n") or 0) + int(timings.get("cache_n") or 0))
    return record(label, "openai", model, prompt_tokens=prompt, cached_tokens=cached,
                  prompt_ms=int(float(timings.get("prompt_ms") or 0)),
                  output_tokens=int(usage.get("completion_tokens") or timings.get("predicted_n") or 0),
                  output_ms=int(float(timings.get("predicted_ms") or 0)))


def summary() -> dict[str, dict]:
    """Averages over the last calls of each agent label."""
    out: dict[str, dict] = {}
    with _lock:
        snapshot = {k: list(v) for k, v in _calls.items()}
    for label, rows in snapshot.items():
        if not rows:
            continue
        n = len(rows)
        prompt = sum(r["prompt_tokens"] for r in rows)
        cached = sum(r["cached_tokens"] for r in rows)
        timed = [r for r in rows if r["output_ms"]]  # speed only where the server reports timing
        out_tok = sum(r["output_tokens"] for r in timed)
        out_ms = sum(r["output_ms"] for r in timed)
        last = rows[-1]
        out[label] = {
            "calls": n,
            "provider": last["provider"],
            "model": last["model"],
            "avg_prompt_tokens": round(prompt / n),
            "max_prompt_tokens": max(r["prompt_tokens"] for r in rows),
            "cache_hit_pct": round(100 * cached / prompt, 1) if prompt else 0.0,
            "cache_estimated": any(r["estimated"] for r in rows),
            "avg_load_ms": round(sum(r["load_ms"] for r in rows) / n),
            "avg_prompt_ms": round(sum(r["prompt_ms"] for r in rows) / n),
            "tokens_per_second": round(out_tok / (out_ms / 1000), 1) if out_ms else 0.0,
            "last_at": last["at"],
        }
    return out


def reset() -> None:
    with _lock:
        _calls.clear()
