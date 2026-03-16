from abc import ABC, abstractmethod
from typing import Dict, Any


class BaseEvaluator(ABC):
    """The universal blueprint for Hestia's AI Brains."""

    def __init__(self, system_prompt: str):
        self.system_prompt = system_prompt

    @abstractmethod
    def evaluate(self, text_to_evaluate: str) -> Dict[str, Any]:
        """
        Must return a dictionary exactly like this:
        {
            "score": 85,
            "reasoning": "Great location, but lacks a garage.",
            "raw_response": "..."
        }
        """
        pass
