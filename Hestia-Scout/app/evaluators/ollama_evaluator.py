import requests
import json
from core.base_evaluator import BaseEvaluator


class OllamaEvaluator(BaseEvaluator):
    def __init__(self, system_prompt: str, model_name: str = "llama3", api_url: str = "http://localhost:11434/api/generate"):
        super().__init__(system_prompt)
        self.model_name = model_name
        self.api_url = api_url

    def evaluate(self, text_to_evaluate: str) -> dict:
        full_prompt = f"{self.system_prompt}\n\nDATA TO EVALUATE:\n{text_to_evaluate}\n\nRespond ONLY in valid JSON format with keys 'score' (0-100) and 'reasoning'."

        payload = {
            "model": self.model_name,
            "prompt": full_prompt,
            "stream": False,
            "format": "json"  # Forces Ollama to output valid JSON
        }

        try:
            response = requests.post(self.api_url, json=payload)
            if response.status_code == 200:
                result = response.json()
                ai_text = result.get("response", "{}")

                # Parse the AI's JSON string into a Python dictionary
                data = json.loads(ai_text)
                return {
                    "score": data.get("score", 0),
                    "reasoning": data.get("reasoning", "No reasoning provided."),
                    "raw_response": ai_text
                }
            else:
                return {"score": 0, "reasoning": f"API Error: {response.status_code}", "raw_response": ""}
        except Exception as e:
            return {"score": 0, "reasoning": f"Connection Error: {e}", "raw_response": ""}
