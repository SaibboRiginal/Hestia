"""Conversations: list, search, coloured tags, pinned (Cindy 26, dossier docs/work/2026-10-24-tutto-brainstorm-cindy W7).

Archive keeps the messages (``chat_history``) and what the owner sets on a conversation (``chat_session_meta``);
Oracle only passes through (WebUI history sidebar via ``/api/ui/chats*``, tools ``chat_tag`` / ``chat_list`` for
the assistant and Telegram). The session a tool means is the one written last when none is given: the tool runs
inside the turn of that conversation.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from hestia_common.display import display, item
from hestia_common.mcp_helpers import undo

logger = logging.getLogger(__name__)

Route = Callable[..., Any]   # MemoryService._route_archive(method, endpoint, body=None, query=None)


# Tool schemas, shared by the MCP tools (main.py: Telegram, Hestia-MCP) and the chat's own tool set (oracle_engine).
TAG_DESCRIPTION = ("Put coloured tags on this conversation (e.g. lavoro, salute, viaggio) so the owner finds it "
                   "later; also remove tags, give it a title or pin it. Without session_id: the conversation "
                   "you are in.")
TAG_PARAMETERS = {
    "type": "object",
    "properties": {
        "tags": {"type": "string", "description": "Tags to add, comma separated (max 6 per conversation)"},
        "remove": {"type": "string", "description": "Tags to remove, comma separated"},
        "title": {"type": "string", "description": "Short title of the conversation"},
        "pinned": {"type": "boolean", "description": "Pin it on top of the list"},
        "training_off": {"type": "boolean", "description": "true = never use this conversation to train Hestia "
                                                             "(its saved turns are dropped); false = use it again"},
        "color": {"type": "string", "enum": ["gray", "red", "orange", "yellow", "green", "teal", "blue",
                                          "purple", "pink"], "description": "Colour of new tags"},
        "session_id": {"type": "string", "description": "Conversation id (empty = this one)"},
    },
}
LIST_DESCRIPTION = "The owner's conversations, newest first, with their tags; filter by one tag and/or words."
LIST_PARAMETERS = {
    "type": "object",
    "properties": {
        "tag": {"type": "string", "description": "Only conversations with this tag"},
        "query": {"type": "string", "description": "Words in the title or messages"},
        "limit": {"type": "integer", "description": "Max conversations (default 10, max 30)"},
    },
}


class ChatSessionsError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def _need(out: Any) -> Any:
    if out is None:
        raise ChatSessionsError(502, "archivio non raggiungibile")
    return out


def list_chats(route: Route, q: str = "", tag: str = "", since: str = "", until: str = "", pinned: bool | None = None,
               limit: int = 30, offset: int = 0) -> dict:
    query = {"q": q, "tag": tag, "since": since, "until": until, "limit": max(1, min(int(limit), 100)),
             "offset": max(0, int(offset))}
    if pinned is not None:
        query["pinned"] = str(bool(pinned)).lower()
    return _need(route("GET", "/chat/sessions/list", query={k: v for k, v in query.items() if v not in ("", None)}))


def tags(route: Route) -> dict:
    return _need(route("GET", "/chat/sessions/tags"))


def messages(route: Route, session_id: str, limit: int = 200) -> dict:
    rows = _need(route("GET", f"/chat/history/{session_id}", query={"limit": max(1, min(int(limit), 500))}))
    return {"session_id": session_id, "items": [
        {"role": r.get("role"), "content": r.get("content"), "at": r.get("timestamp")} for r in rows or []]}


def set_meta(route: Route, session_id: str, body: dict) -> dict:
    if not str(session_id or "").strip():
        raise ChatSessionsError(422, "conversazione mancante")
    allowed = {k: body[k] for k in ("title", "tags", "add_tags", "remove_tags", "pinned", "training_off", "client")
               if k in body}
    return _need(route("PUT", f"/chat/sessions/{session_id}/meta", body=allowed))


def _current(route: Route) -> str:
    out = list_chats(route, limit=1)
    items = (out or {}).get("items") or []
    # pinned conversations sort first: take the one with the newest message instead
    if items and items[0].get("pinned"):
        everything = list_chats(route, limit=100).get("items") or []
        items = sorted(everything, key=lambda i: i.get("last_at") or "", reverse=True)
    return items[0]["session_id"] if items else ""


def _words(v: Any) -> list[str]:
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [w.strip() for w in str(v or "").replace(";", ",").split(",") if w.strip()]


# ── tools ──────────────────────────────────────────────────────────────────────

def tool_tag(route: Route, tags: Any = "", remove: Any = "", title: str = "", pinned: Any = None,
             session_id: str = "", color: str = "", replace: Any = None, training_off: Any = None) -> dict:
    """``chat_tag``: tags (and maybe a title / pinned) on this conversation; ``replace`` (list) sets the tags
    exactly (used by «Annulla»); returns ``undo`` back to the previous ones."""
    sid = str(session_id or "").strip() or _current(route)
    if not sid:
        raise ChatSessionsError(404, "nessuna conversazione da etichettare")
    body: dict[str, Any] = {"client": "assistant"}
    add = _words(tags)
    if add:
        body["add_tags"] = [{"name": t, "color": color} for t in add]
    if isinstance(replace, list):
        body["tags"] = replace
    if _words(remove):
        body["remove_tags"] = _words(remove)
    if str(title or "").strip():
        body["title"] = str(title).strip()
    if pinned not in (None, ""):
        body["pinned"] = str(pinned).lower() in ("1", "true", "sì", "si", "yes")
    if training_off not in (None, ""):
        body["training_off"] = str(training_off).lower() in ("1", "true", "sì", "si", "yes")
    out = set_meta(route, sid, body)
    names = ", ".join(t["name"] for t in out.get("tags") or []) or "nessuna"
    logger.info("event=chat_tagged session_id=%s tags=%d", sid, len(out.get("tags") or []))
    before = out.get("before") or {}
    text = f"Etichette della conversazione: {names}."
    if "training_off" in body:
        text += (" Non la userò per allenarmi." if body["training_off"] else " La userò di nuovo per allenarmi.")
    return {**out, "text": text,
            "undo": undo("chat_tag", session_id=sid, replace=before.get("tags") or [],
                         title=before.get("title") or "", pinned=bool(before.get("pinned")))}


def tool_list(route: Route, tag: str = "", query: str = "", limit: int = 10) -> dict:
    """``chat_list``: the conversations (newest first), filtered by tag and words, as a card."""
    out = list_chats(route, q=str(query or ""), tag=str(tag or ""), limit=max(1, min(int(limit or 10), 30)))
    items = out.get("items") or []
    sub = f"{out.get('total', len(items))} conversazioni" + (f" con «{tag}»" if tag else "")
    return {**out, "display": display(
        "Conversazioni", subtitle=sub, lines=[] if items else ["Nessuna conversazione."],
        items=[item(i["title"], [", ".join(t["name"] for t in i.get("tags") or []) or "senza etichette",
                                 str(i.get("last_at") or "")[:16].replace("T", " ")]) for i in items])}
