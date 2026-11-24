"""
Cloud Model Provider slot for hybrid/cloud deployments.

Inspection finding F-16: this class previously returned canned text such as
"[Cloud gemini Output]: Processed ...", so a failing local model silently produced a
fabricated "FALLBACK" answer. No cloud SDK is integrated yet, so every call now raises
ModelUnavailableError; the Model Gateway then returns its honest "service unavailable /
human hand-off" message instead of invented content. Replace this class with a real
client (and a data-processing review, SAI-09) before enabling cloud fallback.
"""
from typing import Dict, Any, List, Optional, AsyncIterator

from src.ai.providers.base import BaseModelProvider
from src.ai.providers.ollama_provider import ModelUnavailableError


class CloudProvider(BaseModelProvider):
    def __init__(self, provider_name: str = "gemini"):
        self.provider_name = provider_name

    def _unavailable(self) -> ModelUnavailableError:
        return ModelUnavailableError(f"Cloud provider '{self.provider_name}' is not integrated/configured.")

    async def generate(self, prompt: str, system_prompt: Optional[str] = None, model: Optional[str] = None,
                       max_tokens: int = 1024, temperature: float = 0.2) -> Dict[str, Any]:
        raise self._unavailable()

    async def stream(self, prompt: str, system_prompt: Optional[str] = None, model: Optional[str] = None,
                     max_tokens: int = 1024, temperature: float = 0.2) -> AsyncIterator[str]:
        raise self._unavailable()
        yield  # pragma: no cover - makes this an async generator

    async def embed(self, texts: List[str], model: Optional[str] = None) -> List[List[float]]:
        raise self._unavailable()

    async def rerank(self, query: str, documents: List[str], top_k: int = 5,
                     model: Optional[str] = None) -> List[Dict[str, Any]]:
        raise self._unavailable()

    async def unload(self, model: str) -> bool:
        return True
