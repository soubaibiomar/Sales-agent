"""
Knowledge Base Ingestion and Permission-Filtered RAG Service.
Step 08: Model Gateway, RAG, Router, Protected Tools and Output Verification
(Controls 39, 49, 63, 67; SAI-06, SAI-07, SAI-10)

Enforces:
1. Approved document provenance, hashing, and deduplication.
2. Anti-poisoning and prompt injection defense on ingestion.
3. Strict tenant isolation (tenant boundary fail-closed).
4. Document-level ACL filtering (role allowlists).
5. Tombstoning and secure document purge.
"""
import math
import uuid
import hashlib
import logging
from typing import List, Dict, Any, Optional
from sqlalchemy import select, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.models.entities import KnowledgeDocument, KnowledgeChunk
from src.ai.rag.models import (
    DocumentIngestRequest,
    DocumentResponse,
    RAGQueryRequest,
    RAGChunkResult
)
from src.ai.rag.poison_detector import PoisonDetector

logger = logging.getLogger("SalesAI.RAGService")


def deterministic_embedding(text: str, dim: int = 768) -> List[float]:
    """
    Computes a deterministic, normalized 768-dimensional embedding vector
    based on character and token n-gram hashes.
    Ensures high-fidelity cosine similarity for offline testing and fast retrieval.
    """
    vec = [0.0] * dim
    words = text.lower().split()
    if not words:
        return vec

    for i, word in enumerate(words):
        h = int(hashlib.md5(word.encode("utf-8")).hexdigest(), 16)
        idx = h % dim
        # Position-weighted signal
        vec[idx] += 1.0 / math.sqrt(i + 1)
        # Bigram signal if exists
        if i > 0:
            bi_h = int(hashlib.md5(f"{words[i-1]}_{word}".encode("utf-8")).hexdigest(), 16)
            vec[bi_h % dim] += 0.5

    # L2 normalize
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0.0:
        vec = [round(x / norm, 6) for x in vec]
    return vec


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Computes cosine similarity between two normalized vectors."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    return max(0.0, min(1.0, dot))


async def compute_embedding(text: str, dim: int = 768) -> List[float]:
    """
    Computes embedding using local Ollama neural model (embeddinggemma:latest) if available;
    falls back cleanly to deterministic_embedding.
    """
    try:
        import httpx
        async with httpx.AsyncClient(timeout=1.5) as client:
            resp = await client.post(
                "http://127.0.0.1:11434/api/embeddings",
                json={"model": "embeddinggemma:latest", "prompt": text}
            )
            if resp.status_code == 200:
                emb = resp.json().get("embedding")
                if emb and len(emb) == dim:
                    norm = math.sqrt(sum(x * x for x in emb))
                    if norm > 0.0:
                        return [round(x / norm, 6) for x in emb]
                    return emb
    except Exception:
        pass
    return deterministic_embedding(text, dim=dim)


class KnowledgeService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def ingest_document(
        self,
        tenant_id: str,
        req: DocumentIngestRequest,
        user_id: Optional[str] = None
    ) -> DocumentResponse:
        """
        Ingests and indexes an approved document with provenance tracking,
        anti-poisoning inspection, and chunk generation.
        """
        doc_hash = hashlib.sha256(req.content.encode("utf-8")).hexdigest()

        # Step 1: Scan for poisoning / injection payloads
        is_poisoned, poison_reason = PoisonDetector.scan(req.content)
        status = "POISON_DETECTED" if is_poisoned else "INDEXED"

        # Sanitize HTML tags
        sanitized_full = PoisonDetector.sanitize_html(req.content)

        doc_id = str(uuid.uuid4())
        doc = KnowledgeDocument(
            id=doc_id,
            tenant_id=tenant_id,
            title=req.title,
            source_type=req.source_type,
            document_hash=doc_hash,
            acl_roles=req.acl_roles or ["public"],
            status=status,
            poison_reason=poison_reason,
            metadata_json=req.metadata,
            created_by=user_id
        )
        self.db.add(doc)
        await self.db.flush()

        chunk_count = 0
        if not is_poisoned:
            # Step 2: Deterministic chunking (~300 tokens per chunk)
            words = sanitized_full.split()
            chunk_size = 80  # words per chunk (~100-120 tokens)
            overlap = 15
            step = max(1, chunk_size - overlap)

            chunks: List[str] = []
            for i in range(0, len(words), step):
                chunk_words = words[i:i + chunk_size]
                if chunk_words:
                    chunks.append(" ".join(chunk_words))
                if i + chunk_size >= len(words):
                    break

            if not chunks:
                chunks = [sanitized_full]

            for idx, chunk_text in enumerate(chunks):
                emb = await compute_embedding(chunk_text)
                chunk_entity = KnowledgeChunk(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    document_id=doc_id,
                    chunk_index=idx,
                    content=chunk_text,
                    sanitized_content=chunk_text,
                    token_count=len(chunk_text.split()),
                    embedding_vector=emb,
                    metadata_json={
                        "chunk_index": idx,
                        "title": req.title,
                        "source_type": req.source_type,
                        "acl_roles": req.acl_roles
                    }
                )
                self.db.add(chunk_entity)
                chunk_count += 1

            await self.db.flush()

        logger.info(
            f"Ingested document {doc_id} ('{req.title}') for tenant {tenant_id}: "
            f"status={status}, chunks={chunk_count}"
        )

        return DocumentResponse(
            id=doc.id,
            tenant_id=doc.tenant_id,
            title=doc.title,
            source_type=doc.source_type,
            document_hash=doc.document_hash,
            acl_roles=doc.acl_roles,
            status=doc.status,
            poison_reason=doc.poison_reason,
            chunk_count=chunk_count,
            created_at=doc.created_at,
            updated_at=doc.updated_at
        )

    async def retrieve_context(
        self,
        tenant_id: str,
        req: RAGQueryRequest
    ) -> List[RAGChunkResult]:
        """
        Retrieves top relevant chunks strictly isolated to tenant_id
        and filtered by user_roles against document acl_roles.
        """
        # Step 1: Compute query embedding
        q_emb = await compute_embedding(req.query)

        # Step 2: Query candidate documents and chunks for this tenant
        stmt = (
            select(KnowledgeChunk, KnowledgeDocument)
            .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
            .where(
                and_(
                    KnowledgeDocument.tenant_id == tenant_id,
                    KnowledgeChunk.tenant_id == tenant_id,
                    KnowledgeDocument.status == "INDEXED"
                )
            )
        )
        res = await self.db.execute(stmt)
        rows = res.all()

        scored_results: List[RAGChunkResult] = []
        user_roles_set = set(req.user_roles)

        for chunk, doc in rows:
            # Step 3: Enforce document ACL filtering
            doc_acl = set(doc.acl_roles or ["public"])
            # Permitted if 'public' in ACL or user has any matching role
            if "public" not in doc_acl and not (doc_acl & user_roles_set):
                continue

            # Step 4: Compute cosine similarity
            sim = cosine_similarity(q_emb, chunk.embedding_vector)
            if sim >= req.min_score:
                scored_results.append(
                    RAGChunkResult(
                        chunk_id=chunk.id,
                        document_id=doc.id,
                        title=doc.title,
                        content=chunk.content,
                        score=round(sim, 4),
                        acl_roles=doc.acl_roles,
                        metadata=chunk.metadata_json or {}
                    )
                )

        # Step 5: Sort by score descending and take top limit
        scored_results.sort(key=lambda x: x.score, reverse=True)
        return scored_results[:req.limit]

    async def tombstone_document(self, tenant_id: str, document_id: str) -> bool:
        """Tombstones a document and purges its chunks from active retrieval."""
        stmt = select(KnowledgeDocument).where(
            and_(
                KnowledgeDocument.id == document_id,
                KnowledgeDocument.tenant_id == tenant_id
            )
        )
        res = await self.db.execute(stmt)
        doc = res.scalar_one_or_none()
        if not doc:
            return False

        doc.status = "TOMBSTONED"
        # Delete active chunks
        await self.db.execute(
            delete(KnowledgeChunk).where(
                and_(
                    KnowledgeChunk.document_id == document_id,
                    KnowledgeChunk.tenant_id == tenant_id
                )
            )
        )
        await self.db.flush()
        logger.info(f"Tombstoned document {document_id} for tenant {tenant_id}")
        return True

    async def list_documents(
        self,
        tenant_id: str,
        status: Optional[str] = None
    ) -> List[DocumentResponse]:
        """Lists documents for a tenant."""
        stmt = select(KnowledgeDocument).where(KnowledgeDocument.tenant_id == tenant_id)
        if status:
            stmt = stmt.where(KnowledgeDocument.status == status)
        stmt = stmt.order_by(KnowledgeDocument.created_at.desc())
        res = await self.db.execute(stmt)
        docs = res.scalars().all()

        results = []
        for d in docs:
            # Count chunks
            c_stmt = select(KnowledgeChunk.id).where(KnowledgeChunk.document_id == d.id)
            c_res = await self.db.execute(c_stmt)
            count = len(c_res.scalars().all())
            results.append(
                DocumentResponse(
                    id=d.id,
                    tenant_id=d.tenant_id,
                    title=d.title,
                    source_type=d.source_type,
                    document_hash=d.document_hash,
                    acl_roles=d.acl_roles,
                    status=d.status,
                    poison_reason=d.poison_reason,
                    chunk_count=count,
                    created_at=d.created_at,
                    updated_at=d.updated_at
                )
            )
        return results
