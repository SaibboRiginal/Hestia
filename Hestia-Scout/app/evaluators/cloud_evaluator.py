import logging

from google import genai
from google.genai import types
from core.base_evaluator import BaseEvaluator

logger = logging.getLogger("hestia_scout.evaluator")


class CloudEvaluator(BaseEvaluator):
    def __init__(self, system_prompt: str, api_key: str):
        super().__init__(system_prompt)
        self.client = genai.Client(api_key=api_key)

        # 🔄 THE QUOTA HACK: Our arsenal of free-tier models
        self.models_to_try = [
            "gemini-2.5-flash",
            "gemini-3-flash",
            "gemini-2.5-flash-lite"
        ]

    def evaluate(self, text_to_evaluate: str) -> dict:
        last_error = ""

        # Try each model in the list until one works
        for model_name in self.models_to_try:
            try:
                response = self.client.models.generate_content(
                    model=model_name,
                    contents=text_to_evaluate,
                    config=types.GenerateContentConfig(
                        system_instruction=self.system_prompt,
                        response_mime_type="application/json",
                    )
                )

                return {
                    "raw_response": response.text,
                    "model_used": model_name,
                    "error": None
                }

            except Exception as e:
                error_msg = str(e)
                # If it's a Quota/Rate Limit error (429), loop to the next model!
                if "429" in error_msg or "quota" in error_msg.lower():
                    logger.info(
                        "event=model_quota_exhausted_switching_model Model quota exhausted, switching | model=%s", model_name)
                    last_error = error_msg
                    continue
                else:
                    # If it's a different error (like a bad prompt), stop and return it
                    return {"raw_response": "", "error": f"API Error: {error_msg}"}

        # If we exhausted all models in the list
        return {
            "raw_response": "",
            "error": f"All models exhausted. Last error: {last_error}"
        }
