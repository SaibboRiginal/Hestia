"""LLM extraction via Oracle (single owner of LLM provider access).

Scout holds no API key and no model choice: it calls Oracle's ``/api/llm/generate`` via Hub
with ``use_case: scout.annunci`` (declared in Scout's Hub registration, ``LLM_USECASES``). The chain of models
(and the skip of models out of quota) is Oracle's: Oracle → Cervello → Modelli.
"""
from __future__ import annotations

import logging
import os

import requests

from core import scout_settings
from core.base_evaluator import BaseEvaluator

logger = logging.getLogger("hestia_scout.evaluator")


class OracleEvaluator(BaseEvaluator):
    USE_CASE = "scout.annunci"   # declared in main.LLM_USECASES; chain chosen in Oracle → Modelli

    def __init__(self, system_prompt: str, hub_api_url: str | None = None):
        super().__init__(system_prompt)
        self.hub_api_url = (hub_api_url or os.getenv("HUB_API_URL", "http://hestia_hub:19001/api")).rstrip("/")

    @property
    def timeout(self) -> float:
        """Per-call timeout: central setting ``scout.llm.timeout`` (live)."""
        return float(scout_settings.get_int(scout_settings.LLM_TIMEOUT, 1))

    def evaluate(self, text_to_evaluate: str) -> dict:
        prompt = (f"{self.system_prompt}\n\nINPUT:\n{text_to_evaluate}\n\n"
                  "Output SOLO JSON valido. Niente testo fuori dal JSON.")
        timeout = self.timeout
        try:
            resp = requests.post(
                f"{self.hub_api_url}/route/oracle/api/llm/generate",
                json={"method": "POST", "headers": {}, "query": {}, "timeout_seconds": timeout,
                      "body": {"prompt": prompt, "use_case": self.USE_CASE}},
                timeout=timeout + 5)
            resp.raise_for_status()
            routed = resp.json() or {}
            status = int(routed.get("status_code", 500))
            payload = routed.get("payload") or {}
            if status >= 400:
                return {"raw_response": "", "error": f"API Error: oracle {status}: {str(payload)[:200]}"}
            text = str(payload.get("response") if isinstance(payload, dict) else payload or "")
            model = payload.get("model") if isinstance(payload, dict) else ""
            return {"raw_response": text, "model_used": model or "oracle-default", "error": None}
        except Exception as exc:
            logger.warning("[🔄] event=oracle_extraction_call_failed use_case=%s error=%s", self.USE_CASE, exc)
            return {"raw_response": "", "error": f"Oracle call failed: {exc}"}
