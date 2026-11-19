"""
RAG Package initialization.
"""
from src.ai.rag.models import (
    DocumentIngestRequest,
    DocumentResponse,
    RAGQueryRequest,
    RAGChunkResult
)
from src.ai.rag.poison_detector import PoisonDetector
from src.ai.rag.service import KnowledgeService, deterministic_embedding, cosine_similarity

__all__ = [
    "DocumentIngestRequest",
    "DocumentResponse",
    "RAGQueryRequest",
    "RAGChunkResult",
    "PoisonDetector",
    "KnowledgeService",
    "deterministic_embedding",
    "cosine_similarity"
]
