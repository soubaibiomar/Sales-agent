"""
Pydantic Schemas for Knowledge Ingestion and RAG.
Step 08: Model Gateway, RAG, Router, Protected Tools and Output Verification
"""
from datetime import datetime
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field


class DocumentIngestRequest(BaseModel):
    title: str = Field(..., max_length=255)
    content: str = Field(..., min_length=1)
    source_type: str = Field(default="TEXT", max_length=50)  # TEXT, FILE, CATALOG, POLICY, FAQ
    acl_roles: List[str] = Field(default_factory=lambda: ["public"])
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DocumentResponse(BaseModel):
    id: str
    tenant_id: str
    title: str
    source_type: str
    document_hash: str
    acl_roles: List[str]
    status: str  # INDEXED, TOMBSTONED, POISON_DETECTED
    poison_reason: Optional[str] = None
    chunk_count: int = 0
    created_at: datetime
    updated_at: datetime


class RAGQueryRequest(BaseModel):
    query: str = Field(..., min_length=1)
    limit: int = Field(default=5, ge=1, le=20)
    user_roles: List[str] = Field(default_factory=lambda: ["customer"])
    min_score: float = Field(default=0.1, ge=0.0, le=1.0)


class RAGChunkResult(BaseModel):
    chunk_id: str
    document_id: str
    title: str
    content: str
    score: float
    acl_roles: List[str]
    metadata: Dict[str, Any]
