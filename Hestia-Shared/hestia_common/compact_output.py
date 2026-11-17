"""Shape an output before it goes back into a model: same facts, fewer tokens.

Every place where a tool result, a command or a test run re-enters a model's context uses this one function
(Oracle agent loop, Forge tools, module agents). No model and no dependency: deterministic and fast.

- JSON (a dict/list, or text that parses as JSON): empty fields go away; a list of objects with the same keys
  becomes a table (``{"columns": [...], "rows": [[...]]}``, the keys written once); written compact, no indent.
  Over the budget the longest lists keep fewer items: items with an error first, then the first ones in order, with
  ``"more": "showing 12 of 40"`` so the model never takes a part for the whole.
- Text and logs: repeated lines become one line with ``[×N]``; over the budget the head and the tail are kept
  (a pytest summary is at the end) plus the error lines of the middle.

``shape(value, max_chars)`` returns a ``Shaped`` with the text, whether something was left out (``cut``), and the
full text (``full``) so the caller can hand out the rest on request.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

_EMPTY = (None, "", [], {})
_ERROR_KEYS = ("error", "errors", "failed", "exception")
_ERROR_LINE = re.compile(r"error|fail|traceback|exception|assert|warning|denied|refused|timed? ?out", re.I)
_MIN_TABLE_ROWS = 3


@dataclass
class Shaped:
    text: str          # what the model reads
    cut: bool          # something was left out to fit the budget
    full: str          # the whole output (compact), for «the rest on request»
    total_items: int = 0   # items of the longest list (0 = not a list)


def shape(value: Any, max_chars: int) -> Shaped:
    """*value*: dict, list, JSON text or plain text. *max_chars* ≤ 0 = no budget (only the lossless shaping)."""
    data = _as_json(value)
    if data is not _NOT_JSON:
        return _shape_json(data, max_chars)
    return shape_text(str(value if value is not None else ""), max_chars)


# ── JSON ──────────────────────────────────────────────────────────────────────

_NOT_JSON = object()


def _as_json(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        s = value.strip()
        if s[:1] in "{[" and s[-1:] in "}]":
            try:
                return json.loads(s)
            except ValueError:
                return _NOT_JSON
    return _NOT_JSON


def _dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)


def prune(data: Any) -> Any:
    """Drop empty values (None, "", [], {}) at every depth; False and 0 are facts and stay."""
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            v = prune(v)
            if v not in _EMPTY:
                out[k] = v
        return out
    if isinstance(data, list):
        pruned = (prune(v) for v in data)
        return [v for v in pruned if v not in _EMPTY]
    return data


def _tabular_keys(items: list) -> list[str] | None:
    """Columns of a list of objects that share their keys (None when they do not, or the list is short)."""
    if len(items) < _MIN_TABLE_ROWS or not all(isinstance(i, dict) for i in items):
        return None
    columns: list[str] = []
    seen: set[str] = set()
    total = 0
    for item in items:
        total += len(item)
        for k in item:
            if k not in seen:
                seen.add(k)
                columns.append(k)
    avg = total / len(items)
    if not columns or len(columns) > max(avg * 1.5, avg + 2):   # too different: a table would be mostly nulls
        return None
    return columns


def tabulate(data: Any) -> Any:
    """Lists of same-shaped objects → ``{"columns", "rows"}`` (deep)."""
    if isinstance(data, dict):
        return {k: tabulate(v) for k, v in data.items()}
    if isinstance(data, list):
        items = [tabulate(v) for v in data]
        columns = _tabular_keys(items)
        if columns:
            return {"columns": columns, "rows": [[i.get(c) for c in columns] for i in items]}
        return items
    return data


def _is_error_item(item: Any) -> bool:
    if isinstance(item, dict):
        if item.get("ok") is False:
            return True
        return any(item.get(k) for k in _ERROR_KEYS)
    return False


def _lists(data: Any, path: tuple = ()) -> list[tuple[tuple, list]]:
    """Every list inside *data* with its path (rows of a table count as the list)."""
    found: list[tuple[tuple, list]] = []
    if isinstance(data, dict):
        if set(data) >= {"columns", "rows"} and isinstance(data.get("rows"), list):
            found.append((path + ("rows",), data["rows"]))
        for k, v in data.items():
            if k != "rows":
                found += _lists(v, path + (k,))
    elif isinstance(data, list):
        found.append((path, data))
        for i, v in enumerate(data):
            found += _lists(v, path + (i,))
    return found


def _get(data: Any, path: tuple) -> Any:
    for p in path:
        data = data[p]
    return data


def _set(data: Any, path: tuple, value: Any) -> None:
    _get(data, path[:-1])[path[-1]] = value


def _keep(items: list, n: int, columns: list | None) -> list:
    """*n* items of *items*: the error ones first (they are why the model asked), then the first in order."""
    if n >= len(items):
        return items
    errors = [i for i, it in enumerate(items) if _is_error_item(_row_as_item(it, columns))]
    chosen = (errors[:n] + [i for i in range(len(items)) if i not in errors])[:n]
    return [items[i] for i in sorted(chosen)]


def _row_as_item(row: Any, columns: list | None) -> Any:
    if columns and isinstance(row, list):
        return dict(zip(columns, row))
    return row


def _shape_json(data: Any, max_chars: int) -> Shaped:
    shaped = tabulate(prune(data))
    full = _dumps(shaped)
    if max_chars <= 0 or len(full) <= max_chars:
        biggest = max((len(lst) for _, lst in _lists(shaped)), default=0)
        return Shaped(full, False, full, biggest)
    box = {"v": json.loads(full)}   # a holder, so a top-level list is shortened in place like any other

    def out() -> str:
        return _dumps(box["v"])

    lists = sorted(_lists(box["v"], ("v",)), key=lambda pl: len(_dumps(pl[1])), reverse=True)
    total = len(lists[0][1]) if lists else 0
    for path, original in lists:
        if len(original) <= 1:
            continue
        parent = _get(box, path[:-1])
        columns = parent.get("columns") if isinstance(parent, dict) and path[-1] == "rows" else None
        lo, hi, best = 1, len(original) - 1, 1
        while lo <= hi:   # most items that still fit
            mid = (lo + hi) // 2
            _set(box, path, _keep(original, mid, columns))
            _mark(box, path, mid, len(original))
            if len(out()) <= max_chars:
                best, lo = mid, mid + 1
            else:
                hi = mid - 1
        _set(box, path, _keep(original, best, columns))
        _mark(box, path, best, len(original))
        if len(out()) <= max_chars:
            text = out()
            if path == ("v",):   # a top-level list has no object to hold «more»: say it after the list
                text += f"\n[showing {best} of {len(original)}]"
            return Shaped(text, True, full, total)
    text = out()   # no list left to shorten (one long text field): plain cut of the compact JSON
    return Shaped(_cut_note(text[:max_chars], len(full)), True, full, total)


def _mark(work: Any, path: tuple, shown: int, total: int) -> None:
    """Write «showing N of M» next to the shortened list (in its table, or in the object that holds it)."""
    note = f"showing {shown} of {total}"
    if path == ("v",):
        return   # top-level list: the note goes after it (no object to hold the key)
    holder = _get(work, path[:-1])
    if isinstance(holder, dict):
        key = "more" if path[-1] == "rows" else f"{path[-1]}_more"
        holder[key] = note


def _cut_note(text: str, total: int) -> str:
    return text + f"\n[…cut: {len(text)} of {total} chars shown]"


# ── Text ──────────────────────────────────────────────────────────────────────

def _squeeze_repeats(lines: list[str]) -> list[str]:
    out: list[str] = []
    prev, count = None, 0
    for line in lines + [None]:   # sentinel flushes the last run
        if line == prev:
            count += 1
            continue
        if prev is not None:
            out.append(prev if count == 1 else f"{prev}  [×{count}]")
        prev, count = line, 1
    return out


def shape_text(text: str, max_chars: int) -> Shaped:
    """Plain text or a log: repeated lines squeezed; over the budget head + error lines + tail."""
    lines = _squeeze_repeats(str(text or "").rstrip().splitlines())
    full = "\n".join(lines)
    if max_chars <= 0 or len(full) <= max_chars:
        return Shaped(full, False, full)
    budget = max(80, max_chars - 60)   # room for the omission note
    head_budget, tail_budget = int(budget * 0.3), int(budget * 0.5)
    head: list[str] = []
    used = 0
    for line in lines:
        if used + len(line) + 1 > head_budget:
            break
        head.append(line)
        used += len(line) + 1
    tail: list[str] = []
    used = 0
    for line in reversed(lines[len(head):]):
        if used + len(line) + 1 > tail_budget:
            break
        tail.insert(0, line)
        used += len(line) + 1
    middle = lines[len(head):len(lines) - len(tail)]
    errors: list[str] = []
    room = budget - sum(len(x) + 1 for x in head + tail)
    for line in middle:
        if _ERROR_LINE.search(line) and len(line) + 1 <= room:
            errors.append(line)
            room -= len(line) + 1
    if not head and not tail:   # one huge line
        return Shaped(_cut_note(full[:budget], len(full)), True, full)
    omitted = len(middle) - len(errors)
    note = [f"[…{omitted} lines omitted…]"] if omitted else []
    body = head + note + (errors + ["[…]"] if errors else []) + tail
    return Shaped("\n".join(body), True, full)
