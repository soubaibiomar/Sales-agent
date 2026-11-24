-- =============================================================================
-- 017: Record the embedding model of every RAG chunk (inspection finding F-18)
-- =============================================================================
-- Retrieval only compares vectors produced by the same model. Pre-existing chunks have
-- no recorded model and are therefore excluded until re-indexed.
ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS embedding_model VARCHAR(100);
CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_embedding_model ON knowledge_chunks (tenant_id, embedding_model);
