"""
Integration Test Suite: Real PostgreSQL 16 Model Gateway & RAG Validation.
Executes against live PostgreSQL container (sales-ai-postgres) on 127.0.0.1:5432
under the unprivileged 'sales_app_user' account with FORCE ROW LEVEL SECURITY.

Verifies:
1. PostgreSQL 16 RLS tenant isolation across all 3 Step 08 tables:
   - knowledge_documents
   - knowledge_chunks
   - model_execution_logs
2. Cross-tenant leakage rejection (Tenant Beta sees 0 rows from Tenant Alpha).
3. Missing tenant context rejection (unscoped queries see 0 rows under FORCE RLS).
4. End-to-end live RAG document ingestion, chunking, and retrieval on real PostgreSQL 16.
(Controls 39-40, 49, 63, 65-67; SAI-06 to SAI-12; ADR-008)
Step 08: Model Gateway, RAG, Router, Protected Tools and Output Verification
"""
import sys
import uuid
import psycopg
import pytest
import warnings
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import text, select

if sys.platform == "win32":
    import asyncio
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from src.backend.models.entities import KnowledgeDocument, KnowledgeChunk, ModelExecutionLog
from src.ai.rag.service import KnowledgeService
from src.ai.rag.models import DocumentIngestRequest, RAGQueryRequest

PG_ASYNC_URL = "postgresql+psycopg://sales_app_user:sales_app_dev_password@127.0.0.1:5432/sales_ai_db"
PG_SYNC_CONN = "postgresql://sales_app_user:sales_app_dev_password@127.0.0.1:5432/sales_ai_db"

STEP08_TABLES = [
    "knowledge_documents",
    "knowledge_chunks",
    "model_execution_logs"
]


@pytest.fixture(scope="module")
def real_pg08_tenants():
    t_alpha = f"t_pg08_alpha_{uuid.uuid4().hex[:8]}"
    t_beta = f"t_pg08_beta_{uuid.uuid4().hex[:8]}"

    admin_conn_str = "postgresql://postgres:postgres_dev_password_change_in_prod@127.0.0.1:5432/sales_ai_db"
    with psycopg.connect(admin_conn_str) as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO tenants (id, name, slug) VALUES (%s, %s, %s)", (t_alpha, "PG08 Alpha", f"slug-{t_alpha}"))
            cur.execute("INSERT INTO tenants (id, name, slug) VALUES (%s, %s, %s)", (t_beta, "PG08 Beta", f"slug-{t_beta}"))
        conn.commit()

    yield t_alpha, t_beta

    with psycopg.connect(admin_conn_str) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM tenants WHERE id IN (%s, %s)", (t_alpha, t_beta))
        conn.commit()


@pytest.mark.asyncio
async def test_real_postgres_force_rls_active_step08():
    """Verify that FORCE ROW LEVEL SECURITY is enabled on all Step 08 tables."""
    admin_conn_str = "postgresql://postgres:postgres_dev_password_change_in_prod@127.0.0.1:5432/sales_ai_db"
    with psycopg.connect(admin_conn_str) as conn:
        with conn.cursor() as cur:
            for tbl in STEP08_TABLES:
                cur.execute("""
                    SELECT c.relrowsecurity, c.relforcerowsecurity
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public' AND c.relname = %s;
                """, (tbl,))
                row = cur.fetchone()
                assert row is not None, f"Table {tbl} not found in pg_class"
                rls_enabled, rls_forced = row
                assert rls_enabled is True, f"RLS not enabled on {tbl}"
                assert rls_forced is True, f"FORCE RLS not enabled on {tbl}"


@pytest.mark.asyncio
async def test_real_postgres_rls_tenant_isolation_step08(real_pg08_tenants):
    """
    Verify cross-tenant data isolation on real PostgreSQL:
    Data inserted under Tenant Alpha is invisible to Tenant Beta and unscoped connections.
    """
    t_alpha, t_beta = real_pg08_tenants

    # 1. Insert rows under Tenant Alpha
    with psycopg.connect(PG_SYNC_CONN) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.current_tenant_id', %s, false)", (t_alpha,))

            # Knowledge Document
            doc_id = str(uuid.uuid4())
            cur.execute("""
                INSERT INTO knowledge_documents (id, tenant_id, title, source_type, document_hash, acl_roles, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (doc_id, t_alpha, "Alpha Doc", "CATALOG", "hash123", ["public"], "INDEXED"))

            # Knowledge Chunk
            chunk_id = str(uuid.uuid4())
            cur.execute("""
                INSERT INTO knowledge_chunks (id, tenant_id, document_id, chunk_index, content, sanitized_content, embedding_vector)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (chunk_id, t_alpha, doc_id, 0, "Alpha chunk text", "Alpha chunk text", [0.1, 0.2]))

            # Model Execution Log
            log_id = str(uuid.uuid4())
            cur.execute("""
                INSERT INTO model_execution_logs (id, tenant_id, provider, model_name, prompt_tokens, completion_tokens, total_tokens)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (log_id, t_alpha, "ollama", "qwen3.5:4b", 10, 20, 30))

        conn.commit()

    # 2. Query as Tenant Alpha -> All 3 rows visible
    with psycopg.connect(PG_SYNC_CONN) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.current_tenant_id', %s, false)", (t_alpha,))
            cur.execute("SELECT count(*) FROM knowledge_documents WHERE tenant_id = %s", (t_alpha,))
            assert cur.fetchone()[0] == 1
            cur.execute("SELECT count(*) FROM knowledge_chunks WHERE tenant_id = %s", (t_alpha,))
            assert cur.fetchone()[0] == 1
            cur.execute("SELECT count(*) FROM model_execution_logs WHERE tenant_id = %s", (t_alpha,))
            assert cur.fetchone()[0] == 1

    # 3. Query as Tenant Beta -> Exactly 0 rows visible (Tenant boundary fail-closed)
    with psycopg.connect(PG_SYNC_CONN) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.current_tenant_id', %s, false)", (t_beta,))
            cur.execute("SELECT count(*) FROM knowledge_documents")
            assert cur.fetchone()[0] == 0
            cur.execute("SELECT count(*) FROM knowledge_chunks")
            assert cur.fetchone()[0] == 0
            cur.execute("SELECT count(*) FROM model_execution_logs")
            assert cur.fetchone()[0] == 0

    # 4. Query with empty tenant context -> Exactly 0 rows visible (FORCE RLS denies unscoped)
    with psycopg.connect(PG_SYNC_CONN) as conn:
        with conn.cursor() as cur:
            cur.execute("RESET app.current_tenant_id")
            cur.execute("SELECT count(*) FROM knowledge_documents")
            assert cur.fetchone()[0] == 0


@pytest.mark.asyncio
async def test_real_postgres_rag_service_live(real_pg08_tenants):
    """Verify KnowledgeService end-to-end ingestion and retrieval against live PostgreSQL 16."""
    t_alpha, t_beta = real_pg08_tenants

    engine = create_async_engine(PG_ASYNC_URL, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with session_factory() as session:
        # Set session-level tenant config
        await session.execute(text("SELECT set_config('app.current_tenant_id', :tid, false)"), {"tid": t_alpha})

        service = KnowledgeService(session)
        req = DocumentIngestRequest(
            title="Guide Solaire PostgreSQL Live",
            content="Gamme solaire certifiée pour le marché marocain avec onduleurs hybrides.",
            acl_roles=["public"]
        )
        ingested = await service.ingest_document(t_alpha, req)
        await session.commit()

        assert ingested.status == "INDEXED"
        assert ingested.chunk_count >= 1

        # Query back
        q_req = RAGQueryRequest(query="onduleurs hybrides marché marocain", user_roles=["customer"], min_score=0.01)
        results = await service.retrieve_context(t_alpha, q_req)

        assert len(results) >= 1
        assert "onduleurs hybrides" in results[0].content

    await engine.dispose()
