#!/usr/bin/env python3
"""Deterministic stand-in for Ollama, used only by the cloud test bench (no GPU, no model download).

Speaks the Ollama API Oracle uses (/api/chat, /api/generate, /api/tags, /api/show, /api/ps,
/api/embed, /api/embeddings) and the OpenAI-compatible /v1 endpoints. Every answer is a fixed
"[LLM finto]" text that echoes the last user message, so flows that need no real reasoning run end
to end and the report can say plainly that the brain was fake. Stdlib only.

Scripted tools: a user message with `#tool <name> {json args}` (one or more) makes the fake answer with that
tool call (native `tool_calls` when tools are offered, else a `<tool_call>` block), one per turn, until the
prompt shows the tool's result (`[TOOL]: [<name>] →`); then it answers with the last result. This lets the
bench drive chat → Oracle → Hestia-MCP → module flows without a real model.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.getenv("FAKE_LLM_PORT", "11434"))
EMBED_DIM = int(os.getenv("ORACLE_EMBED_DIM", "768"))
MODELS = ["gemma4:e4b", "qwen2.5-coder:14b", "nomic-embed-text", "fake:latest"]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _vector(text: str) -> list[float]:
    """Unit vector derived from the text hash: same text, same vector."""
    out, seed = [], hashlib.sha256(text.encode("utf-8")).digest()
    while len(out) < EMBED_DIM:
        seed = hashlib.sha256(seed).digest()
        out.extend((b - 127.5) / 127.5 for b in seed)
    out = out[:EMBED_DIM]
    norm = math.sqrt(sum(v * v for v in out)) or 1.0
    return [v / norm for v in out]


def _last_user(messages: list) -> str:
    for msg in reversed(messages or []):
        if msg.get("role") == "user":
            content = msg.get("content")
            if isinstance(content, list):  # OpenAI parts
                content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
            return str(content or "")
    return ""


_DIRECTIVE = re.compile(r"#tool\s+([a-z0-9_]+)\s*(\{.*?\})?(?=\s*(?:#tool|$|\n))", re.DOTALL)


def _current_turn(text: str) -> str:
    """The prompt from the last «USER:» line on: directives in the conversation history are already done."""
    cut = (text or "").rfind("USER: ")
    return text[cut:] if cut >= 0 else (text or "")


def _pending_tool(text: str) -> dict | None:
    """First scripted `#tool name {args}` of this turn whose result is not yet in the prompt."""
    text = _current_turn(text)
    for name, raw in _DIRECTIVE.findall(text):
        if f"[TOOL]: [{name}] →" in text:
            continue
        try:
            args = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            args = {}
        return {"name": name, "arguments": args}
    return None


def _scripted_answer(text: str) -> str | None:
    """After scripted tools ran: answer with the last tool result, so the reply shows what the module said."""
    text = _current_turn(text)
    if not _DIRECTIVE.search(text):
        return None
    results = re.findall(r"\[TOOL\]: (\[[a-z0-9_]+\] → .*?)(?=\n\[[A-Z]+\]:|\nNow provide|\nAnswer:|\Z)", text, re.DOTALL)
    last = " ".join(results[-1].split())[:600] if results else "nessun risultato"
    return f"[LLM finto] Strumenti eseguiti. Ultimo risultato: {last}"


def _answer(user_text: str, wants_json: bool) -> str:
    if wants_json:
        return "{}"
    snippet = " ".join(user_text.split())[:160]
    return f"[LLM finto] Ho ricevuto: «{snippet}». Questo è il banco di prova: nessun modello reale."


def _wants_json(body: dict, text: str) -> bool:
    return body.get("format") == "json" or (body.get("response_format") or {}).get("type") == "json_object" \
        or "json" in text[-400:].lower()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # one line per request, logfmt-ish
        print(f"event=fake_llm_request path={self.path} status={args[1] if len(args) > 1 else '-'}", flush=True)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return {}

    def _send(self, payload, status: int = 200, ctype: str = "application/json") -> None:
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path in ("/", "/health"):
            return self._send(b"Ollama is running", ctype="text/plain")
        if path == "/api/tags":
            return self._send({"models": [{"name": m, "model": m, "size": 1, "modified_at": _now(),
                                           "details": {"family": "fake", "parameter_size": "0B"}} for m in MODELS]})
        if path == "/api/ps":
            return self._send({"models": []})
        if path == "/api/version":
            return self._send({"version": "0.0.0-fake"})
        if path == "/v1/models":
            return self._send({"object": "list", "data": [{"id": m, "object": "model"} for m in MODELS]})
        return self._send({"error": "not found"}, 404)

    def do_POST(self):  # noqa: N802
        path, body = self.path.split("?")[0], self._body()
        model = body.get("model") or MODELS[0]
        if path == "/api/show":
            return self._send({"capabilities": ["completion", "tools", "vision", "thinking"],
                               "model_info": {"general.context_length": 32768}, "details": {"family": "fake"}})
        if path == "/api/embeddings":
            return self._send({"embedding": _vector(str(body.get("prompt", "")))})
        if path in ("/api/embed", "/v1/embeddings"):
            raw = body.get("input", "")
            items = raw if isinstance(raw, list) else [raw]
            vectors = [_vector(str(t)) for t in items]
            if path == "/api/embed":
                return self._send({"model": model, "embeddings": vectors})
            return self._send({"object": "list", "data": [{"object": "embedding", "index": i, "embedding": v}
                                                          for i, v in enumerate(vectors)]})
        if path == "/api/generate":
            prompt = str(body.get("prompt", ""))
            pending = _pending_tool(prompt)
            if pending:
                block = json.dumps({"name": pending["name"], "params": pending["arguments"]})
                return self._ollama(model, {"response": f"<tool_call>{block}</tool_call>"}, body.get("stream", True),
                                    key="response")
            scripted = _scripted_answer(prompt)
            if scripted:
                return self._ollama(model, {"response": scripted}, body.get("stream", True), key="response")
            text = _answer(str(body.get("prompt", "")), _wants_json(body, str(body.get("prompt", ""))))
            return self._ollama(model, {"response": text}, body.get("stream", True), key="response")
        if path == "/api/chat":
            user = _last_user(body.get("messages"))
            pending = _pending_tool(user)
            if pending:
                if body.get("tools"):
                    msg = {"role": "assistant", "content": "", "tool_calls": [{"function": pending}]}
                else:
                    block = json.dumps({"name": pending["name"], "params": pending["arguments"]})
                    msg = {"role": "assistant", "content": f"<tool_call>{block}</tool_call>"}
                return self._ollama(model, {"message": msg}, body.get("stream", True), key="message")
            scripted = _scripted_answer(user)
            if scripted:
                return self._ollama(model, {"message": {"role": "assistant", "content": scripted}},
                                    body.get("stream", True), key="message")
            text = _answer(user, _wants_json(body, json.dumps(body.get("messages") or [])[-600:]))
            return self._ollama(model, {"message": {"role": "assistant", "content": text}},
                                body.get("stream", True), key="message")
        if path == "/v1/chat/completions":
            user = _last_user(body.get("messages"))
            text = _answer(user, _wants_json(body, json.dumps(body.get("messages") or [])[-600:]))
            if body.get("stream"):
                return self._openai_stream(model, text)
            return self._send({"id": "fake", "object": "chat.completion", "created": int(time.time()), "model": model,
                               "choices": [{"index": 0, "finish_reason": "stop",
                                            "message": {"role": "assistant", "content": text}}],
                               "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
        return self._send({"error": "not found"}, 404)

    def _ollama(self, model: str, part: dict, stream: bool, key: str) -> None:
        final = {"model": model, "created_at": _now(), "done": True, "done_reason": "stop",
                 "total_duration": 1, "prompt_eval_count": 1, "eval_count": 1}
        if not stream:
            return self._send({**final, **part})
        if key == "message":
            empty = {"message": {"role": "assistant", "content": ""}}
        else:
            empty = {"response": ""}
        lines = [{"model": model, "created_at": _now(), "done": False, **part}, {**final, **empty}]
        data = b"".join(json.dumps(line).encode("utf-8") + b"\n" for line in lines)
        self._send(data, ctype="application/x-ndjson")

    def _openai_stream(self, model: str, text: str) -> None:
        chunks = [{"choices": [{"index": 0, "delta": {"role": "assistant", "content": text}}]},
                  {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}]
        data = b"".join(b"data: " + json.dumps({"id": "fake", "object": "chat.completion.chunk", "model": model,
                                                 **c}).encode("utf-8") + b"\n\n" for c in chunks) + b"data: [DONE]\n\n"
        self._send(data, ctype="text/event-stream")


if __name__ == "__main__":
    print(f"event=fake_llm_start port={PORT} embed_dim={EMBED_DIM}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
