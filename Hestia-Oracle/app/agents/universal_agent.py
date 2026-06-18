import io
import os
import time
import logging
import requests
import json
from google import genai
from google.genai import types

# Retry configuration — overridable via env
_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "3"))
_RETRY_BASE_DELAY = float(os.getenv("LLM_RETRY_BASE_DELAY_SEC", "1.0"))

logger = logging.getLogger(f"hestia_oracle.{__name__}")


class UniversalAgent:
    def __init__(self, role_prompt: str = "", provider: str = "gemini", model_name: str = "gemini-2.5-flash", thinking: bool = True):
        self.role_prompt = role_prompt
        self.provider = provider.lower()
        self.model_name = model_name
        self.thinking = thinking
        self.ollama_timeout_sec = int(os.getenv("OLLAMA_TIMEOUT_SEC", "120"))
        self.ollama_embed_timeout_sec = int(
            os.getenv("OLLAMA_EMBED_TIMEOUT_SEC", "60"))
        self.ollama_tool_call_mode = os.getenv(
            "OLLAMA_TOOL_CALL_MODE", "auto").strip().lower()

        if self.provider == "gemini":
            api_key = (os.getenv("GEMINI_API_KEY") or "").strip()
            if not api_key:
                logger.warning(
                    "event=gemini_api_key_missing_model_auto_fallback GEMINI_API_KEY missing for model '%s'; auto-fallback to Ollama.",
                    self.model_name,
                )
                self.provider = "ollama"
                # Preserve explicit model when it already targets local Ollama.
                if "gemini" in (self.model_name or "").lower() or "models/" in (self.model_name or "").lower():
                    self.model_name = "qwen2.5:7b"
                self._init_ollama_defaults()
            else:
                self.client = genai.Client(api_key=api_key)

        elif self.provider == "ollama":
            self._init_ollama_defaults()

    def _init_ollama_defaults(self) -> None:
        self.ollama_url = os.getenv(
            "OLLAMA_URL", "http://host.docker.internal:11434/api/generate")

    # ─────────────────────────────────────────────────────────────────
    #  Internal retry helper
    # ─────────────────────────────────────────────────────────────────

    def _with_retry(self, fn, *args, **kwargs):
        """Call fn(*args, **kwargs) with exponential backoff on failure.

        Raises the last exception if all attempts are exhausted.
        """
        last_exc = None
        for attempt in range(_MAX_RETRIES):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    delay = _RETRY_BASE_DELAY * (2 ** attempt)
                    time.sleep(delay)
        raise last_exc

    # ─────────────────────────────────────────────────────────────────
    #  Core ask
    # ─────────────────────────────────────────────────────────────────

    def ask(self, user_message: str) -> str:
        return self._with_retry(self._ask_once, user_message)

    def ask_with_tools(self, user_message: str, tools: list[dict]) -> dict:
        """Ask model with native tool-calling when provider/model supports it.

        Returns:
          {"tool_call": {"name": str, "params": dict}, "text": str}
          or
          {"tool_call": None, "text": str}
        """
        return self._with_retry(self._ask_with_tools_once, user_message, tools)

    def _ask_with_tools_once(self, user_message: str, tools: list[dict]) -> dict:
        if not tools:
            return {"tool_call": None, "text": self._ask_once(user_message)}

        if self.provider == "gemini":
            return self._ask_with_tools_gemini(user_message, tools)

        if self.provider == "ollama":
            if self.ollama_tool_call_mode in {"native", "auto"}:
                try:
                    return self._ask_with_tools_ollama_native(user_message, tools)
                except Exception as exc:
                    if self.ollama_tool_call_mode == "native":
                        raise
                    logger.trace(
                        "event=ollama_native_tool_call_fallback Ollama native tool calling unavailable, falling back to prompt mode: %s", exc)
            # prompt fallback for models without native tool calling
            return {
                "tool_call": None,
                "text": self._ask_once(user_message),
            }

        return {"tool_call": None, "text": self._ask_once(user_message)}

    def _ask_once(self, user_message: str) -> str:
        if self.provider == "gemini":
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=user_message,
                config=types.GenerateContentConfig(
                    system_instruction=self.role_prompt
                )
            )
            return response.text.strip()

        elif self.provider == "ollama":
            payload = {
                "model": self.model_name,
                "prompt": f"{self.role_prompt}\n\nUser: {user_message}\nAnswer:",
                "stream": False,
            }
            if not self.thinking:
                payload["think"] = False
            response = requests.post(
                self.ollama_url,
                json=payload,
                timeout=self.ollama_timeout_sec
            )
            response.raise_for_status()
            return response.json().get("response", "").strip()

        raise RuntimeError(f"Unknown provider: {self.provider}")

    def _ask_with_tools_gemini(self, user_message: str, tools: list[dict]) -> dict:
        declarations: list[types.FunctionDeclaration] = []
        for tool in tools:
            declarations.append(
                types.FunctionDeclaration(
                    name=str(tool.get("name", "")).strip(),
                    description=str(tool.get("description", "")).strip(),
                    parameters=tool.get("parameters") or {
                        "type": "object", "properties": {}},
                )
            )

        response = self.client.models.generate_content(
            model=self.model_name,
            contents=user_message,
            config=types.GenerateContentConfig(
                system_instruction=self.role_prompt,
                tools=[types.Tool(function_declarations=declarations)],
            ),
        )

        # Native function call path
        fn_calls = getattr(response, "function_calls", None) or []
        if fn_calls:
            call = fn_calls[0]
            return {
                "tool_call": {
                    "name": str(getattr(call, "name", "") or ""),
                    "params": dict(getattr(call, "args", {}) or {}),
                },
                "text": "",
            }

        # Candidate parts fallback path
        try:
            candidates = getattr(response, "candidates", None) or []
            if candidates:
                parts = getattr(candidates[0].content, "parts", None) or []
                for part in parts:
                    fn = getattr(part, "function_call", None)
                    if fn:
                        return {
                            "tool_call": {
                                "name": str(getattr(fn, "name", "") or ""),
                                "params": dict(getattr(fn, "args", {}) or {}),
                            },
                            "text": "",
                        }
        except Exception:
            pass

        return {"tool_call": None, "text": (response.text or "").strip()}

    def _ask_with_tools_ollama_native(self, user_message: str, tools: list[dict]) -> dict:
        chat_url = self.ollama_url.replace("/api/generate", "/api/chat")
        ollama_tools = [
            {
                "type": "function",
                "function": {
                    "name": str(t.get("name", "")).strip(),
                    "description": str(t.get("description", "")).strip(),
                    "parameters": t.get("parameters") or {"type": "object", "properties": {}},
                },
            }
            for t in tools
        ]
        # Use a dedicated tool-calling system prompt — the general Hestia persona
        # is too chatty and dilutes tool-use instructions when 40+ tools are
        # available.  The full agent-loop preamble (with tool manifest) is
        # already inside *user_message*.
        _TOOL_CALLING_SYSTEM = (
            "You are Hestia's tool-calling engine. "
            "When the user asks for something you can do with a tool, call it immediately. "
            "If no tool matches the request, respond in plain text. "
            "Never respond with just 'Ciao' or a greeting when the user asked a substantive question — "
            "use a tool or give a real answer."
        )
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": _TOOL_CALLING_SYSTEM},
                {"role": "user", "content": user_message},
            ],
            "tools": ollama_tools,
            "stream": False,
            "think": False,  # Gemma 4: thinking tokens (<unused50>) break tool-call parsing
        }

        logger.trace(
            "event=ollama_native_tool_call_request model=%s tool_count=%d "
            "prompt_len=%d system_len=%d",
            self.model_name, len(ollama_tools), len(user_message),
            len(_TOOL_CALLING_SYSTEM))

        t_req = time.time()
        response = requests.post(
            chat_url,
            json=payload,
            timeout=self.ollama_timeout_sec,
        )
        response.raise_for_status()
        data = response.json() or {}
        elapsed_ms = int((time.time() - t_req) * 1000)

        message = data.get("message") if isinstance(
            data.get("message"), dict) else {}

        tool_calls = message.get("tool_calls") if isinstance(
            message.get("tool_calls"), list) else []
        content_text = str(message.get("content", "") or "").strip()

        logger.trace(
            "event=ollama_native_tool_call_response elapsed_ms=%d "
            "tool_calls_count=%d content_len=%d content_preview=%s",
            elapsed_ms, len(tool_calls), len(content_text),
            json.dumps(content_text[:150], ensure_ascii=False))

        if tool_calls:
            first = tool_calls[0] if isinstance(tool_calls[0], dict) else {}
            fn = first.get("function") if isinstance(
                first.get("function"), dict) else {}
            args = fn.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            result = {
                "tool_call": {
                    "name": str(fn.get("name", "") or ""),
                    "params": dict(args or {}),
                },
                "text": "",
            }
            logger.info(
                "event=ollama_native_tool_call_selected tool=%s params=%s elapsed_ms=%d",
                result["tool_call"]["name"],
                json.dumps(result["tool_call"]["params"], ensure_ascii=False)[:200],
                elapsed_ms)
            return result

        logger.info(
            "event=ollama_native_no_tool_call content=%s elapsed_ms=%d",
            json.dumps(content_text[:120], ensure_ascii=False), elapsed_ms)
        return {
            "tool_call": None,
            "text": content_text,
        }

    # ─────────────────────────────────────────────────────────────────
    #  Token-level streaming
    # ─────────────────────────────────────────────────────────────────

    def ask_stream(self, user_message: str):
        """Yield incremental token strings as they arrive from the provider.

        Falls back to a single chunk if the provider does not support streaming.
        """
        if self.provider == "gemini":
            yield from self._ask_stream_gemini(user_message)
        elif self.provider == "ollama":
            yield from self._ask_stream_ollama(user_message)
        else:
            yield self.ask(user_message)

    def _ask_stream_gemini(self, user_message: str):
        try:
            for chunk in self.client.models.generate_content_stream(
                model=self.model_name,
                contents=user_message,
                config=types.GenerateContentConfig(
                    system_instruction=self.role_prompt
                ),
            ):
                if chunk.text:
                    yield chunk.text
        except Exception as exc:
            raise RuntimeError(
                f"Gemini stream error ({self.model_name}): {exc}") from exc

    def _ask_stream_ollama(self, user_message: str):
        import json as _json
        payload = {
            "model": self.model_name,
            "prompt": f"{self.role_prompt}\n\nUser: {user_message}\nAnswer:",
            "stream": True,
        }
        if not self.thinking:
            payload["think"] = False
        try:
            with requests.post(
                self.ollama_url,
                json=payload,
                timeout=self.ollama_timeout_sec,
                stream=True,
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    try:
                        data = _json.loads(line)
                    except ValueError:
                        continue
                    token = data.get("response", "")
                    if token:
                        yield token
                    if data.get("done"):
                        break
        except Exception as exc:
            raise RuntimeError(f"Ollama stream error: {exc}") from exc

    # ─────────────────────────────────────────────────────────────────
    #  Backward-compat alias
    # ─────────────────────────────────────────────────────────────────

    def complete(self, prompt: str) -> str:
        """Alias for ask() — kept for backward compatibility."""
        return self.ask(prompt)

    def ask_with_attachment(
        self,
        file_bytes: bytes,
        mime_type: str,
        user_message: str,
    ) -> str:
        """Reason over an attached document or image together with the user message.

        Supports any MIME type that the underlying provider can handle:
        - Gemini: all image types + application/pdf (native support).
        - Ollama: image/* via base64 in the images field; PDFs are
          pre-converted to text with pypdf before the call.

        Raises ``RuntimeError`` on provider error.
        """
        if self.provider == "gemini":
            return self._ask_with_attachment_gemini(file_bytes, mime_type, user_message)
        elif self.provider == "ollama":
            return self._ask_with_attachment_ollama(file_bytes, mime_type, user_message)
        return self.ask(user_message)

    # ─────────────────────────────────────────────────────────────────
    #  Attachment helpers
    # ─────────────────────────────────────────────────────────────────

    def _ask_with_attachment_gemini(
        self, file_bytes: bytes, mime_type: str, user_message: str
    ) -> str:
        try:
            file_part = types.Part.from_bytes(
                data=file_bytes, mime_type=mime_type)
            contents = [file_part, user_message]
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=self.role_prompt
                ),
            )
            return response.text.strip()
        except Exception as exc:
            raise RuntimeError(
                f"Gemini attachment error ({self.model_name}): {exc}") from exc

    def _ask_with_attachment_ollama(
        self, file_bytes: bytes, mime_type: str, user_message: str
    ) -> str:
        if mime_type == "application/pdf":
            extracted_text = _extract_pdf_text(file_bytes)
            augmented_message = (
                f"[Attached document content]\n{extracted_text}\n\n"
                f"[User instruction]\n{user_message}"
            )
            return self.ask(augmented_message)

        if mime_type.startswith("image/"):
            import base64
            image_b64 = base64.b64encode(file_bytes).decode("utf-8")
            payload = {
                "model": self.model_name,
                "prompt": f"{self.role_prompt}\n\nUser: {user_message}\nAnswer:",
                "images": [image_b64],
                "stream": False,
            }
            try:
                response = requests.post(
                    self.ollama_url,
                    json=payload,
                    timeout=self.ollama_timeout_sec,
                )
                response.raise_for_status()
                return response.json().get("response", "").strip()
            except Exception as exc:
                raise RuntimeError(f"Ollama vision error: {exc}") from exc

        # Fallback: treat as plain text
        return self.ask(user_message)

    def embed(self, text: str) -> list[float]:
        if self.provider == "gemini":
            try:
                response = self.client.models.embed_content(
                    model=self.model_name,
                    contents=text,
                    config=types.EmbedContentConfig(
                        task_type="RETRIEVAL_QUERY"
                    )
                )
                return response.embeddings[0].values
            except Exception as e:
                raise RuntimeError(f"Gemini Embedding Error: {e}")

        elif self.provider == "ollama":
            embed_url = self.ollama_url.replace(
                "/api/generate", "/api/embeddings").replace("/api/chat", "/api/embeddings")
            try:
                response = requests.post(embed_url, json={
                    "model": self.model_name,
                    "prompt": text
                }, timeout=self.ollama_embed_timeout_sec)
                response.raise_for_status()
                return response.json().get("embedding", [])
            except Exception as e:
                raise RuntimeError(f"Ollama Embedding Error: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────
#  Module-level helpers
# ─────────────────────────────────────────────────────────────────────

def _extract_pdf_text(file_bytes: bytes) -> str:
    """Extract plain text from a PDF using pypdf.

    Returns an empty string if the PDF is scanned / unreadable.
    """
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(file_bytes))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages).strip()
    except Exception:
        return ""
