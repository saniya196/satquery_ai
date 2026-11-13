"""Provider-agnostic LLM interface + a Gemini REST client (httpx only, no extra SDK).

The LLM may (1) turn a question into a StructuredQuery and (2) phrase a result. It never computes.
"""
import os
from abc import ABC, abstractmethod
from typing import Optional

import httpx


class LLMError(Exception):
    """Any LLM/API failure. Callers must fall back to the rule-based path, never fabricate."""


class LLMClient(ABC):
    @abstractmethod
    def complete(self, system: str, user: str, json_mode: bool = False) -> str:
        """Return the model's text. Raise LLMError on any failure."""


class GeminiClient(LLMClient):
    BASE = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, api_key: str, model: Optional[str] = None, timeout: float = 20.0,
                 transport: Optional[httpx.BaseTransport] = None):
        if not api_key:
            raise LLMError("Missing API key.")
        self.api_key = api_key
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def complete(self, system: str, user: str, json_mode: bool = False) -> str:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0},
        }
        if json_mode:
            body["generationConfig"]["responseMimeType"] = "application/json"
        try:
            r = self._client.post(f"{self.BASE}/{self.model}:generateContent",
                                  headers={"x-goog-api-key": self.api_key}, json=body)
            r.raise_for_status()
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"Gemini request failed: {type(exc).__name__}") from exc  # never echo the key


_GEMINI_KEY_PLACEHOLDER = "replace-me-with-your-gemini-api-key"


def get_llm_client() -> Optional[LLMClient]:
    """None without a real configured key; the app then uses rules and template answers."""
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key or key.casefold() == _GEMINI_KEY_PLACEHOLDER:
        return None
    return GeminiClient(key)
