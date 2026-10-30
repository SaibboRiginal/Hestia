"""How a Hestia tool becomes one Hub-routed request — the single implementation (Hestia-MCP uses it).

A tool (MCP tool of a module, or an inline Hub command) declares ``service``, ``method``, ``path`` and optional
``query_template`` / ``body_template``. Templates may use ``$session_id``, ``$chat_id`` / ``$owner`` (the notify
target of the caller) and ``$arg.<name>``; paths may hold ``$name`` / ``{name}`` filled from the arguments.
Arguments not consumed by a template go to the query (GET/HEAD/DELETE) or to the JSON body (other methods).

Before 2026-10-18 Oracle, Telegram, the WebUI and Hestia-MCP each had their own copy of these rules
(docs/work/2026-10-18-moduli-core-e-mcp-esterno §B2).
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

TEMPLATE_VAR = re.compile(r"\$(session_id|chat_id|owner|arg\.[a-zA-Z0-9_]+)")
PATH_VAR = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)|\{([A-Za-z_][A-Za-z0-9_]*)\}")
QUERY_METHODS = {"GET", "HEAD", "DELETE"}
CONTEXT_VARS = {"session_id", "chat_id", "owner"}
# «Cosa mi metto» is a POST that only suggests: it showed «Fatto» in the chat (bench 2026-10-30).
_READ_WORDS = ("search", "list", "query", "status", "stats", "show", "suggest")


def _token(var: str, args: dict, ctx: dict) -> Any:
    if var == "session_id":
        return ctx.get("session_id") or ""
    if var in ("chat_id", "owner"):
        return ctx.get("notify_target") or ""
    if var.startswith("arg."):
        return args.get(var[4:].strip().lower(), args.get(var[4:].strip()))
    return args.get(var)


def resolve(obj: Any, args: dict, ctx: dict) -> Any:
    """Recursively resolve template variables; an exact ``$var`` keeps the argument's type.
    ``$arg.x`` that resolves to nothing drops its key (optional argument not given)."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            val = resolve(v, args, ctx)
            if isinstance(v, str) and v.strip().startswith("$arg.") and val in (None, ""):
                continue
            out[k] = val
        return out
    if isinstance(obj, list):
        return [resolve(v, args, ctx) for v in obj]
    if isinstance(obj, str):
        text = obj.strip()
        if text.startswith("$") and TEMPLATE_VAR.fullmatch(text):
            return _token(text[1:], args, ctx)

        def _sub(m: re.Match) -> str:
            val = _token(m.group(1), args, ctx)
            return "" if val is None else quote(str(val), safe="")
        return TEMPLATE_VAR.sub(_sub, obj)
    return obj


def template_vars(obj: Any, found: set[str] | None = None) -> set[str]:
    """Argument names a tool's templates/path expect (context variables excluded)."""
    found = set() if found is None else found
    if isinstance(obj, dict):
        for v in obj.values():
            template_vars(v, found)
    elif isinstance(obj, list):
        for v in obj:
            template_vars(v, found)
    elif isinstance(obj, str):
        for m in TEMPLATE_VAR.finditer(obj):
            name = m.group(1)
            found.add(name[4:] if name.startswith("arg.") else name)
        for m in PATH_VAR.finditer(TEMPLATE_VAR.sub("", obj)):
            found.add(m.group(1) or m.group(2))
    return found - CONTEXT_VARS


def _strip_nones(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_nones(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_strip_nones(v) for v in obj if v is not None]
    return obj


def build_request(tool: dict, args: dict | None, ctx: dict | None = None) -> dict:
    """``{service, method, path, query, body, headers}`` for Hub ``/route/<service>/<path>``.

    ``ctx`` = caller context: ``session_id``, ``notify_target`` (chat id / owner), ``client``, ``trace_id``,
    ``access`` (external AI access name → ``X-Hestia-Access``), ``origin`` (``X-Hestia-Origin``)."""
    args = {k: v for k, v in (args or {}).items() if v is not None}
    ctx = ctx or {}
    method = str(tool.get("method") or "GET").upper()
    query_t = tool.get("query_template") if isinstance(tool.get("query_template"), dict) else {}
    body_t = tool.get("body_template") if isinstance(tool.get("body_template"), dict) else {}
    query = resolve(query_t, args, ctx) if query_t else {}
    body = resolve(body_t, args, ctx) if body_t else None
    used = template_vars(query_t) | template_vars(body_t)

    path = resolve(str(tool.get("path") or "").strip(), args, ctx)
    consumed: set[str] = set()

    def _fill(m: re.Match) -> str:
        name = m.group(1) or m.group(2)
        if name in CONTEXT_VARS or name not in args:
            return m.group(0)
        consumed.add(name)
        return quote(str(args[name]), safe="")
    path = PATH_VAR.sub(_fill, str(path))

    rest = {k: v for k, v in args.items() if k not in consumed and k not in used}
    if method in QUERY_METHODS:
        if not query_t:
            query.update(rest)
    elif not body_t:
        body = {**(body or {}), **rest}
    headers = {}
    if ctx.get("session_id"):
        headers["X-Session-Id"] = str(ctx["session_id"])
    if ctx.get("trace_id"):
        headers["X-Trace-Id"] = str(ctx["trace_id"])
    if ctx.get("client"):
        headers["X-Hestia-Client"] = str(ctx["client"])
    if ctx.get("access"):   # an external AI's access name (Hestia-MCP external door): who asked, for the module
        headers["X-Hestia-Access"] = str(ctx["access"])
    if ctx.get("origin"):   # who started the turn (hestia_common.origin), never taken from the arguments
        headers["X-Hestia-Origin"] = str(ctx["origin"])
    return {"service": str(tool.get("service") or "").strip(), "method": method, "path": path.lstrip("/"),
            "query": {k: v for k, v in (query or {}).items() if v is not None},
            # A POST with no arguments still sends «{}»: a module whose endpoint takes a body model answered 422
            # «body: Field required» (bench 2026-10-30: «Case disponibili» with no query).
            "body": _strip_nones(body) if isinstance(body, dict) else body, "headers": headers}


def is_write(tool: dict) -> bool:
    """Same rule Oracle used: a non-GET tool whose name does not read like a lookup changes something."""
    name = str(tool.get("command") or tool.get("name") or "")
    return str(tool.get("method") or "GET").upper() in {"POST", "PUT", "PATCH", "DELETE"} and not any(
        w in name for w in _READ_WORDS)
