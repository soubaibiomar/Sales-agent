"""
Ollama Local Model Provider implementation.
Handles local offline execution for Qwen3.5 4B and 9B with VRAM eviction,
cross-process model lifecycle synchronization, and context cap enforcement.

Inspection finding F-16 remediation:
  * Never fabricates output. Any transport error, timeout or empty answer raises
    ModelUnavailableError; the Model Gateway then fails over or hands off honestly.
  * Non-blocking I/O (httpx.AsyncClient) instead of urllib inside `async def`, so a
    15-30 s cold start no longer stalls the whole event loop.
  * Timeouts are sized from measured cold starts on the target laptop
    (4B ~15 s, 9B ~28 s; see evidence/claude-inspection/benchmarks).
  * `think: false` and only the `response` field is returned, so model reasoning text
    never reaches customers.
"""
import json
import logging
from typing import Dict, Any, List, Optional, AsyncIterator

import httpx

from src.ai.providers.base import BaseModelProvider
from src.ai.config import ai_config
from src.ai.resource_monitor import InferenceTracker
from src.ai.model_lifecycle import lifecycle_manager, VoiceModelSafetyError  # noqa: F401 (re-exported)

logger = logging.getLogger("SalesAI.OllamaProvider")

MAX_9B_CONTEXT_TOKENS = 4096
# Measured cold-load times on the reference laptop are 15 s (4B) and 28 s (9B) when RAM
# is free, but up to ~70-90+ s for 9B under memory pressure (16 GB host, ~0.4 GB free
# during the full test run). 9B is only used for background reasoning, so it gets a
# longer budget; interactive 4B turns keep 60 s.
DEFAULT_GENERATION_TIMEOUT_S = 60.0
COLD_START_TIMEOUT_S = 180.0


class ModelUnavailableError(RuntimeError):
    """The local model could not produce an answer (down, timed out, empty, malformed)."""


def effective_context_length(model: str, requested: Optional[int]) -> int:
    """Context window actually sent to Ollama; 9B is clamped to the hardware cap."""
    num_ctx = requested or 4096
    if "9b" in model.lower() and num_ctx > MAX_9B_CONTEXT_TOKENS:
        logger.warning(
            f"Requested context length {num_ctx} exceeds 9B hardware cap ({MAX_9B_CONTEXT_TOKENS}). Clamping."
        )
        num_ctx = MAX_9B_CONTEXT_TOKENS
    return num_ctx


class OllamaProvider(BaseModelProvider):
    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or ai_config.ollama_base_url).rstrip("/")

    def _payload(self, model: str, prompt: str, system_prompt: Optional[str], max_tokens: int,
                 temperature: float, num_ctx: int, stream: bool) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": stream,
            "think": False,
            "options": {"num_predict": max_tokens, "temperature": temperature, "num_ctx": num_ctx},
        }
        if system_prompt:
            payload["system"] = system_prompt
        return payload

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        channel: Optional[str] = None,
        context_length: Optional[int] = None,
        timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        target_model = model or ai_config.primary_llm
        is_reasoning = "9b" in target_model.lower()
        actual_model = lifecycle_manager.prepare_for_inference(
            target_model, is_complex_reasoning=is_reasoning, channel=channel
        )
        num_ctx = effective_context_length(actual_model, context_length)
        tracker = InferenceTracker(actual_model)
        limit = float(timeout) if timeout else (COLD_START_TIMEOUT_S if is_reasoning else DEFAULT_GENERATION_TIMEOUT_S)

        try:
            with lifecycle_manager.generation_lease(actual_model):
                async with httpx.AsyncClient(timeout=httpx.Timeout(limit, connect=5.0)) as client:
                    resp = await client.post(
                        f"{self.base_url}/api/generate",
                        json=self._payload(actual_model, prompt, system_prompt, max_tokens, temperature, num_ctx, False),
                    )
                    resp.raise_for_status()
                    data = resp.json()
            content = (data.get("response") or "").strip()
            if not content:
                raise ModelUnavailableError(f"Model {actual_model} returned an empty response.")
            tracker.record_first_token()
            tracker.record_tokens(data.get("eval_count") or len(content.split()))
            return {"content": content, "model": actual_model, "metrics": tracker.finish(), "num_ctx": num_ctx}
        except ModelUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001 - every failure is reported, never masked
            tracker.finish()
            raise ModelUnavailableError(f"Ollama generation failed for {actual_model}: {type(exc).__name__}: {exc}") from exc
        finally:
            if is_reasoning:
                try:
                    lifecycle_manager.evict_gpu_model(actual_model)
                except Exception as evict_err:  # noqa: BLE001
                    logger.warning(f"Post-reasoning eviction of {actual_model} failed: {evict_err}")

    async def stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        channel: Optional[str] = None,
        timeout: Optional[float] = None
    ) -> AsyncIterator[str]:
        """Streams real response tokens from Ollama while holding a generation lease."""
        target_model = model or ai_config.primary_llm
        actual_model = lifecycle_manager.prepare_for_inference(target_model, channel=channel)
        num_ctx = effective_context_length(actual_model, None)
        limit = float(timeout) if timeout else DEFAULT_GENERATION_TIMEOUT_S
        produced = False
        with lifecycle_manager.generation_lease(actual_model):
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(limit, connect=5.0)) as client:
                    async with client.stream(
                        "POST", f"{self.base_url}/api/generate",
                        json=self._payload(actual_model, prompt, system_prompt, max_tokens, temperature, num_ctx, True),
                    ) as resp:
                        resp.raise_for_status()
                        async for line in resp.aiter_lines():
                            if not line:
                                continue
                            chunk = json.loads(line)
                            token = chunk.get("response") or ""
                            if token:
                                produced = True
                                yield token
                            if chunk.get("done"):
                                break
            except Exception as exc:  # noqa: BLE001
                raise ModelUnavailableError(f"Ollama stream failed for {actual_model}: {exc}") from exc
            if not produced:
                raise ModelUnavailableError(f"Model {actual_model} streamed no tokens.")

    async def embed(self, texts: List[str], model: Optional[str] = None) -> List[List[float]]:
        """Real embeddings from Ollama's /api/embed (no synthetic vectors)."""
        target_model = model or "embeddinggemma:latest"
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
                resp = await client.post(f"{self.base_url}/api/embed", json={"model": target_model, "input": texts})
                resp.raise_for_status()
                vectors = resp.json().get("embeddings") or []
        except Exception as exc:  # noqa: BLE001
            raise ModelUnavailableError(f"Embedding with {target_model} failed: {exc}") from exc
        if len(vectors) != len(texts):
            raise ModelUnavailableError(f"Embedding model {target_model} returned {len(vectors)} vectors for {len(texts)} texts.")
        return vectors

    async def rerank(self, query: str, documents: List[str], top_k: int = 5,
                     model: Optional[str] = None) -> List[Dict[str, Any]]:
        # No reranker model is installed; refuse instead of returning made-up scores.
        raise ModelUnavailableError("No reranker model is configured for the Ollama provider.")

    async def warm_up(self, model: Optional[str] = None, keep_alive: str = "30m") -> bool:
        """Loads the primary model ahead of the first customer turn (cold start ~15 s measured)."""
        target_model = model or ai_config.primary_llm
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(COLD_START_TIMEOUT_S, connect=5.0)) as client:
                resp = await client.post(f"{self.base_url}/api/generate",
                                         json={"model": target_model, "prompt": "", "keep_alive": keep_alive})
                resp.raise_for_status()
            lifecycle_manager.active_gpu_model = target_model
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Warm-up of {target_model} failed: {exc}")
            return False

    async def unload(self, model: str) -> bool:
        return lifecycle_manager.evict_gpu_model(model)
