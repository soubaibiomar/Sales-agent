"""
Base Model Provider Abstraction Interface.
Decouples application domain services and agents from specific LLM runtimes (Ollama, vLLM, Gemini, OpenAI).
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, AsyncIterator

class BaseModelProvider(ABC):
    """Abstract contract for text generation, embeddings, and reranking."""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.2
    ) -> Dict[str, Any]:
        """
        Executes a single generation turn.
        Returns dictionary with 'content', 'model', and 'metrics'.
        """
        pass

    @abstractmethod
    async def stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.2
    ) -> AsyncIterator[str]:
        """Streams response tokens incrementally for voice or chat UI."""
        pass

    @abstractmethod
    async def embed(
        self,
        texts: List[str],
        model: Optional[str] = None
    ) -> List[List[float]]:
        """Generates dense vector embeddings for semantic search / RAG."""
        pass

    @abstractmethod
    async def rerank(
        self,
        query: str,
        documents: List[str],
        top_k: int = 5,
        model: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Scores and reorders candidate documents by semantic relevance."""
        pass

    @abstractmethod
    async def unload(self, model: str) -> bool:
        """Evicts model from memory."""
        pass
