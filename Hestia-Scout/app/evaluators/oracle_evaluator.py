"""LLM extraction via Oracle (single owner of LLM provider access).

Replaces the direct Gemini client: Scout no longer holds an API key. Oracle's
``/api/llm/generate`` is called via Hub with an explicit provider/model, and
the free-tier quota hop (next model on 429/quota) is preserved.
"""
from __future__ import annotations

import logging
import os

import requests

from core import scout_settings
from core.base_evaluator import BaseEvaluator

logger = logging.getLogger("hestia_scout.evaluator")


class OracleEvaluator(BaseEvaluator):
    def __init__(self, system_prompt: str, hub_api_url: str | None = None):
        super().__init__(system_prompt)
        self.hub_api_url = (hub_api_url or os.getenv("HUB_API_URL", "http://hestia_hub:19001/api")).rstrip("/")
        self.provider = os.getenv("SCOUT_LLM_PROVIDER", "gemini").strip()
        self.models = [m.strip() for m in os.getenv(
            "SCOUT_LLM_MODELS", "gemini-2.5-flash,gemini-2.5-flash-lite").split(",") if m.strip()] or [""]

    @property
    def timeout(self) -> float:
        """Per-call timeout: central setting ``scout.llm.timeout`` (live)."""
        return float(scout_settings.get_int(scout_settings.LLM_TIMEOUT, 1))

    def evaluate(self, text_to_evaluate: str) -> dict:
        prompt = (f"{self.system_prompt}\n\nINPUT:\n{text_to_evaluate}\n\n"
                  "Output SOLO JSON valido. Niente testo fuori dal JSON.")
        last_error = ""
        timeout = self.timeout
        for model in self.models:
            try:
                resp = requests.post(
                    f"{self.hub_api_url}/route/oracle/api/llm/generate",
                    json={"method": "POST", "headers": {}, "query": {}, "timeout_seconds": timeout,
                          "body": {"prompt": prompt, "provider": self.provider, "model": model}},
                    timeout=timeout + 5)
                resp.raise_for_status()
                routed = resp.json() or {}
                status = int(routed.get("status_code", 500))
                payload = routed.get("payload") or {}
                if status >= 400:
                    last_error = f"oracle {status}: {str(payload)[:200]}"
                    if "429" in last_error or "quota" in last_error.lower():
                        logger.info("event=model_quota_exhausted_switching_model model=%s", model)
                        continue
                    return {"raw_response": "", "error": f"API Error: {last_error}"}
                text = str(payload.get("response") if isinstance(payload, dict) else payload or "")
                return {"raw_response": text, "model_used": model or "oracle-default", "error": None}
            except Exception as exc:
                last_error = str(exc)
                logger.warning("[🔄] event=oracle_extraction_call_failed model=%s error=%s", model, exc)
        return {"raw_response": "", "error": f"All models exhausted. Last error: {last_error}"}
