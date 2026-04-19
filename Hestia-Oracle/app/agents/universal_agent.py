import io
import os
import requests
from google import genai
from google.genai import types


class UniversalAgent:
    def __init__(self, role_prompt: str = "", provider: str = "gemini", model_name: str = "gemini-2.5-flash", thinking: bool = True):
        self.role_prompt = role_prompt
        self.provider = provider.lower()
        self.model_name = model_name
        self.thinking = thinking
        self.ollama_timeout_sec = int(os.getenv("OLLAMA_TIMEOUT_SEC", "120"))
        self.ollama_embed_timeout_sec = int(
            os.getenv("OLLAMA_EMBED_TIMEOUT_SEC", "60"))

        if self.provider == "gemini":
            api_key = os.getenv("GEMINI_API_KEY")
            self.client = genai.Client(api_key=api_key)

        elif self.provider == "ollama":
            self.ollama_url = os.getenv(
                "OLLAMA_URL", "http://host.docker.internal:11434/api/generate")

    def ask(self, user_message: str) -> str:
        if self.provider == "gemini":
            try:
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=user_message,
                    config=types.GenerateContentConfig(
                        system_instruction=self.role_prompt
                    )
                )
                return response.text.strip()
            except Exception as e:
                raise RuntimeError(f"API Error ({self.model_name}): {e}")

        elif self.provider == "ollama":
            payload = {
                "model": self.model_name,
                "prompt": f"{self.role_prompt}\n\nUser: {user_message}\nAnswer:",
                "stream": False,
            }
            if not self.thinking:
                payload["think"] = False
            try:
                response = requests.post(
                    self.ollama_url,
                    json=payload,
                    timeout=self.ollama_timeout_sec
                )
                response.raise_for_status()
                return response.json().get("response", "").strip()
            except Exception as e:
                raise RuntimeError(f"Ollama Error: {e}")

    def complete(self, prompt: str) -> str:
        """Alias for ask() — used by the /api/llm/generate endpoint."""
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
