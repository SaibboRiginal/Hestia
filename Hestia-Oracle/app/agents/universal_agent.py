import os
import requests
from google import genai
from google.genai import types


class UniversalAgent:
    def __init__(self, role_prompt: str = "", provider: str = "gemini", model_name: str = "gemini-2.5-flash"):
        self.role_prompt = role_prompt
        self.provider = provider.lower()
        self.model_name = model_name
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
                "stream": False
            }
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

    def embed(self, text: str) -> list[float]:
        if self.provider == "gemini":
            try:
                # La sintassi corretta e ufficiale del SDK
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
