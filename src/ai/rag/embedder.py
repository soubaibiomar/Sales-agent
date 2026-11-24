"""
CPU Text Embedder for Secure RAG Pipeline (Step 11).
Runs strictly on host CPU to protect GPU VRAM for the resident LLM.
(Invariant 9: Hardware envelope & VRAM mutual exclusion)
"""
from typing import List
from src.ai.rag.service import deterministic_embedding, cosine_similarity


class CPUTextEmbedder:
    """Lexical hashing embedder for offline evaluation only (NOT the production semantic model, F-18)."""

    def __init__(self, dimension: int = 768):
        self.dimension = dimension

    def embed_text(self, text: str) -> List[float]:
        return deterministic_embedding(text, dim=self.dimension)

    @staticmethod
    def cosine_similarity(v1: List[float], v2: List[float]) -> float:
        return cosine_similarity(v1, v2)
