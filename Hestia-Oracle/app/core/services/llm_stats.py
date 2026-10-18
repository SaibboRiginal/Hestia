"""Per-call LLM runtime stats: real prompt size, prompt-cache reuse, load time, speed.

Fed by every provider from what the server already returns (Ollama ``prompt_eval_count`` /
``load_duration``, OpenAI-compatible ``usage`` + llama-server ``timings``, Anthropic ``usage``).
Kept in memory as a short rolling window per agent label, plus running totals per
conversation (the chat stream binds its session id, see ``bind_session``); exposed by
``/api/chat/context``. Also daily totals per use case × provider × model (last ``_DAYS`` local days, in
memory since the start of Oracle), read by the WebUI page *Cervello* (``GET /api/ui/stats``).
"""
from __future__ import annotations

import contextvars
import logging
import threading
import time
from collections import OrderedDict, deque
from datetime import date, datetime, timedelta
from typing import Any, Iterator

logger = logging.getLogger("hestia_oracle.llm_stats")

_WINDOW = 50
_MAX_SESSIONS = 200
_DAYS = 31
_STARTED_AT = time.time()
_lock = threading.Lock()
_calls: dict[str, deque] = {}
_sessions: "OrderedDict[str, dict]" = OrderedDict()
_daily: dict[str, dict[tuple[str, str, str], dict]] = {}   # "YYYY-MM-DD" → (label, provider, model) → totals
_current_session: contextvars.ContextVar[str] = contextvars.ContextVar("llm_stats_session", default="")


def bind_session(session_id: str, stream: Iterator[str]) -> Iterator[str]:
    """Run each step of a chat stream with *session_id* bound, so every LLM call it makes is
    also counted for that conversation. Set around every ``next()``: the web server may resume
    the generator from a different thread/context each time."""
    while True:
        token = _current_session.set(session_id or "")
        try:
            item = next(stream)
        except StopIteration:
            return
        finally:
            _current_session.reset(token)
        yield item


def _add_to_session(row: dict) -> None:
    sid = _current_session.get()
    if not sid:
        return
    with _lock:
        tot = _sessions.pop(sid, None) or {
            "calls": 0, "input_tokens": 0, "cached_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
            "estimated": False}
        tot["calls"] += 1
        tot["input_tokens"] += row["prompt_tokens"]
        tot["cached_tokens"] += row["cached_tokens"]
        tot["output_tokens"] += row["output_tokens"]
        tot["cost_usd"] = round(tot["cost_usd"] + float(row.get("cost_usd") or 0), 6)
        tot["estimated"] = tot["estimated"] or row["estimated"]
        tot.update(last_prompt_tokens=row["prompt_tokens"], provider=row["provider"], model=row["model"],
                   last_at=row["at"])
        _sessions[sid] = tot
        while len(_sessions) > _MAX_SESSIONS:
            _sessions.popitem(last=False)


def _add_to_day(label: str, row: dict) -> None:
    day = datetime.fromtimestamp(row["at"]).date().isoformat()
    key = (label, row["provider"], row["model"])
    with _lock:
        per_day = _daily.setdefault(day, {})
        tot = per_day.setdefault(key, {"calls": 0, "input_tokens": 0, "cached_tokens": 0, "output_tokens": 0,
                                       "cost_usd": 0.0})
        tot["calls"] += 1
        tot["input_tokens"] += row["prompt_tokens"]
        tot["cached_tokens"] += row["cached_tokens"]
        tot["output_tokens"] += row["output_tokens"]
        tot["cost_usd"] = round(tot["cost_usd"] + float(row.get("cost_usd") or 0), 6)
        for old in sorted(_daily)[:-_DAYS]:
            del _daily[old]


def daily(days: int = 14, today: date | None = None) -> dict:
    """Totals per day (oldest first, empty days included) and today's split per use case/model."""
    days = max(1, min(int(days or 14), _DAYS))
    today = today or date.today()
    with _lock:
        snapshot = {d: {k: dict(v) for k, v in rows.items()} for d, rows in _daily.items()}
    zero = {"calls": 0, "input_tokens": 0, "cached_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    series = []
    for i in range(days - 1, -1, -1):
        day = (today - timedelta(days=i)).isoformat()
        tot = dict(zero)
        for row in snapshot.get(day, {}).values():
            for k in zero:
                tot[k] += row[k]
        tot["cost_usd"] = round(tot["cost_usd"], 6)
        series.append({"day": day, **tot})
    split = [{"use_case": label, "provider": provider, "model": model, **row}
             for (label, provider, model), row in snapshot.get(today.isoformat(), {}).items()]
    split.sort(key=lambda r: (-r["calls"], r["use_case"]))
    return {"days": series, "today": series[-1], "today_by_model": split, "since": _STARTED_AT}


def session_usage(session_id: str) -> dict:
    """Running totals of one conversation ({} before its first counted call)."""
    with _lock:
        return dict(_sessions.get(session_id or "") or {})


def _ms(ns: Any) -> int:
    try:
        return int(int(ns or 0) / 1_000_000)
    except (TypeError, ValueError):
        return 0


def record(label: str, provider: str, model: str, *, prompt_tokens: int, cached_tokens: int = 0,
           load_ms: int = 0, prompt_ms: int = 0, output_tokens: int = 0, output_ms: int = 0,
           estimated: bool = False, cost_usd: float = 0.0) -> dict:
    """Store one call and log ``event=llm_call_stats``. Returns the row."""
    prompt_tokens = max(0, int(prompt_tokens or 0))
    cached_tokens = max(0, min(int(cached_tokens or 0), prompt_tokens))
    row = {
        "at": time.time(), "provider": provider, "model": model,
        "prompt_tokens": prompt_tokens, "cached_tokens": cached_tokens,
        "load_ms": int(load_ms or 0), "prompt_ms": int(prompt_ms or 0),
        "output_tokens": int(output_tokens or 0), "output_ms": int(output_ms or 0),
        "estimated": bool(estimated), "cost_usd": float(cost_usd or 0),
    }
    label = label or "generic"
    with _lock:
        _calls.setdefault(label, deque(maxlen=_WINDOW)).append(row)
    _add_to_session(row)
    _add_to_day(label, row)
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


def record_anthropic(label: str, provider: str, model: str, usage: Any, cost_usd: float = 0.0) -> dict | None:
    """From an Anthropic ``usage`` (API object or Claude CLI JSON dict). ``input_tokens`` excludes
    cache reads/writes, so the prompt size is their sum."""
    if usage is None:
        return None
    get = usage.get if isinstance(usage, dict) else (lambda k, d=None: getattr(usage, k, d))
    fresh = int(get("input_tokens") or 0)
    read = int(get("cache_read_input_tokens") or 0)
    write = int(get("cache_creation_input_tokens") or 0)
    return record(label, provider, model, prompt_tokens=fresh + read + write, cached_tokens=read,
                  output_tokens=int(get("output_tokens") or 0), cost_usd=cost_usd)


def record_gemini(label: str, model: str, response: Any) -> dict | None:
    """From a google-genai response (``usage_metadata``)."""
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return None
    return record(label, "gemini", model, prompt_tokens=int(getattr(meta, "prompt_token_count", 0) or 0),
                  cached_tokens=int(getattr(meta, "cached_content_token_count", 0) or 0),
                  output_tokens=int(getattr(meta, "candidates_token_count", 0) or 0)
                  + int(getattr(meta, "thoughts_token_count", 0) or 0))


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
        _sessions.clear()
        _daily.clear()
