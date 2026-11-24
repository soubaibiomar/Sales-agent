"""
Regression tests for remediation group D of the independent inspection
(F-15 speech engines, F-17 model-driven tools, F-18 RAG, F-27 VRAM residency).
"""
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

from src.backend.models.entities import Base, Tenant, SalesOrder, KnowledgeChunk


@asynccontextmanager
async def db_env():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    async with factory() as s:
        s.add(Tenant(id="t_d", name="D", slug="d"))
        s.add(SalesOrder(id="o_d", tenant_id="t_d", order_number="SO-778", terms_hash="h", grand_total_cents=250000,
                         currency="MAD", status="SHIPPED", payment_status="PAID"))
        await s.commit()
    try:
        yield factory
    finally:
        await engine.dispose()


class PlanningStub:
    """Deterministic stand-in for the LLM: proposes the given tool calls, then replies."""
    def __init__(self, calls, reply):
        self.calls, self.reply = calls, reply

    async def plan_tool_calls(self, prompt, tools, system_prompt=None, model=None, timeout=None, channel=None):
        self.tools_offered = [t["function"]["name"] for t in tools]
        return self.calls

    async def generate(self, prompt, system_prompt=None, model=None, max_tokens=1024, temperature=0.2, timeout=None, **kw):
        return {"content": self.reply, "model": "stub", "metrics": {}}


# ---------------------------------------------------------------- F-17
@pytest.mark.asyncio
async def test_f17_model_proposed_tool_call_is_executed_and_grounds_the_answer(monkeypatch):
    from src.ai.model_gateway import model_gateway
    from src.ai.agents.base import AgentInput
    from src.ai.agents.interactive.order import OrderPaymentAgent
    from src.ai.tool_gateway import ServerSecurityContext
    stub = PlanningStub([{"name": "orders.get_status", "arguments": {"order_id": "SO-778"}}],
                        "Votre commande SO-778 est payée et expédiée.")
    monkeypatch.setattr(model_gateway, "local_provider", stub)
    async with db_env() as factory:
        async with factory() as s:
            out = await OrderPaymentAgent().execute(
                AgentInput(conversation_id="c", turn_id="t", user_prompt="Statut de ma commande SO-778 ?"),
                ServerSecurityContext(tenant_id="t_d", user_id="u", role="customer"), db_session=s)
    assert "orders.get_status" in stub.tools_offered
    assert out.tools_called[0]["result"]["payment_status"] == "PAID"
    assert out.status == "SUCCESS"  # "payée" claim is backed by the tool's verified PAID status


@pytest.mark.asyncio
async def test_f17_disallowed_or_invented_tool_calls_give_no_evidence(monkeypatch):
    from src.ai.model_gateway import model_gateway
    from src.ai.agents.base import AgentInput
    from src.ai.agents.interactive.order import OrderPaymentAgent
    from src.ai.tool_gateway import ServerSecurityContext
    stub = PlanningStub([
        {"name": "negotiation.propose_discount", "arguments": {"discount_percent": 40}},  # not in role allowlist
        {"name": "orders.get_status", "arguments": {"order_id": "ORD-2026-99182"}},       # invented id
    ], "Votre commande est payée.")
    monkeypatch.setattr(model_gateway, "local_provider", stub)
    async with db_env() as factory:
        async with factory() as s:
            out = await OrderPaymentAgent().execute(
                AgentInput(conversation_id="c", turn_id="t", user_prompt="Ma commande ?"),
                ServerSecurityContext(tenant_id="t_d", user_id="u", role="customer"), db_session=s)
    assert out.tools_called[0]["rejected"] == "NOT_IN_ROLE_ALLOWLIST"
    assert out.tools_called[1]["result"] is None and "not found" in out.tools_called[1]["error"].lower()
    assert out.status == "REJECTED_GUARD"  # unbacked "payée" claim is blocked


def test_f17_no_hardcoded_tool_identifiers_left():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / "src/ai/agents/base.py").read_text(encoding="utf-8")
    for leftover in ("SKU-SOLAR-01", "ORD-2026-99182", "ACC-9921", "INV-00442"):
        assert leftover not in src


# ---------------------------------------------------------------- F-18
@pytest.mark.asyncio
async def test_f18_embedding_model_recorded_and_spaces_never_mixed(monkeypatch):
    from src.ai.rag.service import KnowledgeService
    from src.ai.rag.models import DocumentIngestRequest, RAGQueryRequest
    monkeypatch.setenv("RAG_EMBEDDING_BACKEND", "hashing")
    async with db_env() as factory:
        async with factory() as s:
            svc = KnowledgeService(s)
            await svc.ingest_document("t_d", DocumentIngestRequest(title="Garantie", content="La garantie des panneaux est de cinq ans.", acl_roles=["public"]))
            chunk = (await s.execute(select(KnowledgeChunk))).scalars().one()
            assert chunk.embedding_model == "hashing-bow-768-v1"
            assert await svc.retrieve_context("t_d", RAGQueryRequest(query="garantie panneaux", user_roles=["public"], min_score=0.0))
            # A query embedded with a different model never matches chunks from another space
            monkeypatch.setattr("src.ai.rag.service.compute_embedding",
                                lambda text, dim=768: _async_return(([0.1] * 768, "other-model")))
            assert await svc.retrieve_context("t_d", RAGQueryRequest(query="garantie", user_roles=["public"], min_score=0.0)) == []


async def _async_return(value):
    return value


@pytest.mark.asyncio
async def test_f18_no_silent_fallback_when_embedding_model_is_down(monkeypatch):
    from src.ai.rag.service import KnowledgeService, EmbeddingUnavailableError
    from src.ai.rag.models import DocumentIngestRequest, RAGQueryRequest
    monkeypatch.setenv("RAG_EMBEDDING_BACKEND", "ollama")
    monkeypatch.setattr("src.ai.rag.service.ai_config.ollama_base_url", "http://127.0.0.1:9")
    async with db_env() as factory:
        async with factory() as s:
            svc = KnowledgeService(s)
            doc = await svc.ingest_document("t_d", DocumentIngestRequest(title="T", content="texte de test", acl_roles=["public"]))
            assert doc.status == "PENDING_EMBEDDING" and doc.chunk_count == 0
            with pytest.raises(EmbeddingUnavailableError):
                await svc.retrieve_context("t_d", RAGQueryRequest(query="texte", user_roles=["public"]))


@pytest.mark.asyncio
async def test_f18_api_ignores_client_supplied_roles(monkeypatch):
    from httpx import AsyncClient, ASGITransport
    from src.backend.main import app
    from src.backend.core.database import get_db_session
    from src.backend.core.auth_middleware import get_security_context, SecurityContext
    monkeypatch.setenv("RAG_EMBEDDING_BACKEND", "hashing")
    async with db_env() as factory:
        async def _db():
            async with factory() as s:
                yield s
                await s.commit()

        async def _ctx():
            return SecurityContext(user_id="u", tenant_id="t_d", email="e", roles=["sales_rep"],
                                   permissions=["crm:read", "ai:rag"], mfa_verified=True, jti="j", correlation_id="c")
        app.dependency_overrides[get_db_session] = _db
        app.dependency_overrides[get_security_context] = _ctx
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
                r = await client.post("/api/v1/ai/rag/documents", json={"title": "Board", "content": "marge plancher confidentielle sept pour cent",
                                                                        "acl_roles": ["board_only"]})
                assert r.status_code == 200
                own = await client.post("/api/v1/ai/rag/query", json={"query": "marge plancher", "min_score": 0.0})
                forged = await client.post("/api/v1/ai/rag/query", json={"query": "marge plancher", "min_score": 0.0, "user_roles": ["board_only"]})
            assert own.status_code == forged.status_code == 200
            assert own.json() == [] and forged.json() == []
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------- F-27
def test_f27_eviction_uses_live_ollama_residency():
    from src.ai.model_lifecycle import ModelLifecycleManager
    mgr = ModelLifecycleManager()
    assert mgr.active_gpu_model is None  # this process never loaded anything ...
    with patch.object(mgr, "get_running_ollama_models", return_value=[{"name": "qwen3.5:4b"}]), \
         patch.object(mgr, "evict_gpu_model", return_value=True) as evict:
        chosen = mgr.prepare_for_inference("qwen3.5:9b-q4_K_M", is_complex_reasoning=True)
    assert chosen == "qwen3.5:9b-q4_K_M"
    evict.assert_called_once_with("qwen3.5:4b", verify=True)  # ... but another worker's 4B is evicted


def test_f27_embedding_model_is_not_evicted():
    from src.ai.model_lifecycle import ModelLifecycleManager
    mgr = ModelLifecycleManager()
    with patch.object(mgr, "get_running_ollama_models", return_value=[{"name": "embeddinggemma:latest"}]), \
         patch.object(mgr, "evict_gpu_model", return_value=True) as evict:
        mgr.prepare_for_inference("qwen3.5:4b")
    evict.assert_not_called()


# ---------------------------------------------------------------- F-15
def test_f15_missing_voice_fails_closed_without_fake_audio(monkeypatch, tmp_path):
    from src.backend.voice.multilingual_voice import MultilingualVoiceEngine
    from src.backend.voice.speech_engines import SpeechEngineUnavailableError, TextToSpeechEngine
    from src.backend.core.config import settings
    monkeypatch.setattr(settings, "piper_voices_dir", str(tmp_path))
    monkeypatch.setattr(TextToSpeechEngine, "_voices", {})
    with pytest.raises(SpeechEngineUnavailableError):
        MultilingualVoiceEngine.synthesize_speech("Bonjour", "fr-FR")


def test_f15_real_tts_produces_speech_not_a_tone():
    import numpy as np
    from src.backend.voice.multilingual_voice import MultilingualVoiceEngine
    chunk, meta = MultilingualVoiceEngine.synthesize_speech("Bonjour et bienvenue.", "fr-FR")
    pcm = np.frombuffer(chunk.pcm_bytes, dtype=np.int16).astype(np.float32)
    spectrum = np.abs(np.fft.rfft(pcm))
    top3_share = np.sort(spectrum)[-3:].sum() / spectrum.sum()
    assert meta["tts_engine"].startswith("Piper") and chunk.duration_ms > 500
    assert top3_share < 0.05  # the old placeholder was 3 pure sines (300/1200/2500 Hz)
