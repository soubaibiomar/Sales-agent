"""
Regression tests for remediation group B of the independent inspection
(F-11, F-14, F-16, F-19, F-28, F-31; F-34 lives in test_permission_catalog_coverage.py).
"""
import asyncio
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

from src.backend.models.entities import Base, Tenant, Warehouse, InventoryItem, StockReservation, OutboxEvent


# ---------------------------------------------------------------- F-16
@pytest.mark.asyncio
async def test_f16_provider_never_fabricates_output_when_model_is_down():
    from src.ai.providers.ollama_provider import OllamaProvider, ModelUnavailableError
    dead = OllamaProvider(base_url="http://127.0.0.1:9")  # nothing listens on the discard port
    with pytest.raises(ModelUnavailableError):
        await dead.generate("Bonjour", model="qwen3.5:4b", timeout=2)


@pytest.mark.asyncio
async def test_f16_gateway_degrades_to_honest_handoff():
    from src.ai.model_gateway import ModelGateway, ModelGatewayRequest
    from src.ai.providers.ollama_provider import OllamaProvider
    gw = ModelGateway(local_provider=OllamaProvider(base_url="http://127.0.0.1:9"))
    res = await gw.generate(ModelGatewayRequest(tenant_id="t", prompt="Prix du kit ?", max_latency_ms=2000))
    assert res.status == "UNAVAILABLE_HANDOFF"
    assert "Simulated" not in res.content and "[Cloud" not in res.content
    assert "conseiller humain" in res.content


@pytest.mark.asyncio
async def test_f16_cloud_slot_refuses_instead_of_inventing():
    from src.ai.providers.cloud_provider import CloudProvider
    from src.ai.providers.ollama_provider import ModelUnavailableError
    with pytest.raises(ModelUnavailableError):
        await CloudProvider().generate("x")


def test_f16_context_clamp_for_9b():
    from src.ai.providers.ollama_provider import effective_context_length
    assert effective_context_length("qwen3.5:9b-q4_K_M", 8192) == 4096
    assert effective_context_length("qwen3.5:4b", 8192) == 8192


# ---------------------------------------------------------------- F-14
def test_f14_quote_link_binding():
    from src.backend.core.signed_links import issue_link_token, verify_link_token, SignedLinkError
    tok = issue_link_token("quote_response", "tA", "q1", 3, ttl_seconds=60)
    claims = verify_link_token(tok, "quote_response", "q1")
    assert (claims.tenant_id, claims.version) == ("tA", 3)
    for bad in (lambda: verify_link_token(tok, "quote_response", "q2"),
                lambda: verify_link_token(tok, "other_purpose", "q1"),
                lambda: verify_link_token(tok[:-1] + ("0" if tok[-1] != "0" else "1"), "quote_response", "q1"),
                lambda: verify_link_token(issue_link_token("quote_response", "tA", "q1", 3, ttl_seconds=-1), "quote_response", "q1")):
        with pytest.raises(SignedLinkError):
            bad()


# ---------------------------------------------------------------- F-31
def test_f31_superiority_comes_from_holdout_not_in_sample_fit():
    from src.backend.domains.analytics.forecasting import ForecastingEngine
    history = [{"date": str(datetime(2026, 1, 1).date() + timedelta(days=i)), "gross_revenue_cents": 100000 + 1500 * i + (7000 if i % 7 == 0 else 0)}
               for i in range(60)]
    res = ForecastingEngine.generate_advisory_revenue_forecast(history, periods_ahead=7)
    hb = res["holdout_backtest"]
    assert hb["status"] == "OK" and hb["holdout_days"] == 14 and hb["training_days"] == 46
    assert res["is_superior_to_baseline"] == hb["beats_best_baseline"]
    short = ForecastingEngine.generate_advisory_revenue_forecast(history[:6], periods_ahead=3)
    assert short["holdout_backtest"]["status"] == "INSUFFICIENT_HISTORY"
    assert short["is_superior_to_baseline"] is None


# ---------------------------------------------------------------- F-19
class CapturingDispatcher:
    def __init__(self):
        self.sent = []

    async def __call__(self, event):
        self.sent.append(event.id)
        return True


async def _worker_env():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    async with factory() as s:
        s.add(Tenant(id="t_w", name="W", slug="w"))
        s.add(Warehouse(id="wh_w", tenant_id="t_w", code="WH", name="WH"))
        s.add(InventoryItem(id="ii_w", tenant_id="t_w", warehouse_id="wh_w", sku="SKU-W", on_hand_quantity=10, reserved_quantity=4))
        s.add(StockReservation(tenant_id="t_w", inventory_item_id="ii_w", sku="SKU-W", quantity=4, status="ACTIVE",
                               reserved_until=datetime.now(timezone.utc) - timedelta(minutes=5)))
        s.add(OutboxEvent(id="ev_w", tenant_id="t_w", event_type="ORDER_CONFIRMED", channel_type="WHATSAPP",
                          recipient_identifier="+212600000001", payload_json="{}", status="PENDING",
                          next_retry_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
        await s.commit()
    return engine, factory


@pytest.mark.asyncio
async def test_f19_worker_relays_outbox_and_expires_reservations():
    from src.backend.worker import PlatformWorker
    engine, factory = await _worker_env()
    try:
        disp = CapturingDispatcher()
        totals = await PlatformWorker(session_factory=factory, dispatcher=disp).run_cycle()
        assert totals["errors"] == 0 and totals["reservations_expired"] == 1
        assert disp.sent == ["ev_w"]
        async with factory() as s:
            assert (await s.get(InventoryItem, "ii_w")).reserved_quantity == 0
            assert (await s.get(OutboxEvent, "ev_w")).status == "DELIVERED"
        # Idempotent: a second cycle does nothing more
        again = await PlatformWorker(session_factory=factory, dispatcher=disp).run_cycle()
        assert again["reservations_expired"] == 0 and disp.sent == ["ev_w"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_f19_worker_never_marks_unsent_events_delivered():
    from src.backend.worker import PlatformWorker
    engine, factory = await _worker_env()
    try:
        await PlatformWorker(session_factory=factory).run_cycle()  # default dispatcher: no provider
        async with factory() as s:
            ev = await s.get(OutboxEvent, "ev_w")
            assert ev.status != "DELIVERED"
            assert "No outbound provider" in (ev.last_error or "")
    finally:
        await engine.dispose()


# ---------------------------------------------------------------- F-11 / F-28 (real PostgreSQL)
def _su_url():
    root = Path(__file__).resolve().parents[2]
    pw = re.search(r"POSTGRES_PASSWORD:-([^}]+)\}", (root / "infra/docker-compose.yml").read_text(encoding="utf-8")).group(1)
    return f"postgresql+psycopg://postgres:{pw}@127.0.0.1:5432/sales_ai_db"


def test_f11_f28_database_constraints():
    asyncio.run(_constraints_body(), loop_factory=asyncio.SelectorEventLoop)


async def _constraints_body():
    eng = create_async_engine(_su_url())
    try:
        async with eng.connect() as c:
            await c.execute(text("SELECT 1"))
    except Exception:
        await eng.dispose()
        pytest.skip("Local PostgreSQL not reachable")
    ta, tb = "t_c_" + uuid.uuid4().hex[:6], "t_c_" + uuid.uuid4().hex[:6]
    acc_b = str(uuid.uuid4())
    checks = {
        "cross_tenant_fk": f"INSERT INTO opportunities(id,tenant_id,account_id,title) VALUES ('{uuid.uuid4()}','{ta}','{acc_b}','x')",
        "negative_stock": f"INSERT INTO warehouses(id,tenant_id,code,name) VALUES ('w_{ta}','{ta}','W','W'); "
                          f"INSERT INTO inventory_items(id,tenant_id,warehouse_id,sku,on_hand_quantity) VALUES ('{uuid.uuid4()}','{ta}','w_{ta}','S',-1)",
        "zero_refund": f"INSERT INTO sales_orders(id,tenant_id,order_number,terms_hash) VALUES ('o_{ta}','{ta}','O1','h'); "
                       f"INSERT INTO refund_requests(id,tenant_id,order_id,amount_cents,reason) VALUES ('{uuid.uuid4()}','{ta}','o_{ta}',0,'r')",
    }
    try:
        async with eng.begin() as c:
            await c.execute(text("INSERT INTO tenants(id,name,slug) VALUES (:a,:a,:a),(:b,:b,:b)"), {"a": ta, "b": tb})
            await c.execute(text("INSERT INTO accounts(id,tenant_id,name) VALUES (:i,:t,'B')"), {"i": acc_b, "t": tb})
        for name, sql in checks.items():
            with pytest.raises(Exception, match="violates"):
                async with eng.begin() as c:
                    for stmt in sql.split("; "):
                        await c.execute(text(stmt))
    finally:
        async with eng.begin() as c:
            await c.execute(text("DELETE FROM accounts WHERE id=:i"), {"i": acc_b})
            await c.execute(text("DELETE FROM tenants WHERE id IN (:a,:b)"), {"a": ta, "b": tb})
        await eng.dispose()


# ---------------------------------------------------------------- F-08 + F-16 at agent level
class _FixedReplyProvider:
    def __init__(self, reply):
        self.reply = reply

    async def generate(self, prompt, system_prompt=None, model=None, max_tokens=1024, temperature=0.2, timeout=None, **kw):
        return {"content": self.reply, "model": model or "qwen3.5:4b", "metrics": {}}


@pytest.mark.asyncio
@pytest.mark.parametrize("reply,expected", [
    ("Le total pour 2 onduleurs est de 6000 MAD.", "REJECTED_GUARD"),     # model computed a price
    ("Votre commande est payée.", "REJECTED_GUARD"),                      # unverified payment claim
    ("Le prix unitaire vérifié est de 3000 MAD.", "SUCCESS"),              # matches verified evidence
])
async def test_agent_output_is_grounded_or_rejected(monkeypatch, reply, expected):
    from src.ai.model_gateway import model_gateway
    from src.ai.agents.base import AgentInput
    from src.ai.agents.interactive.quote import QuotePricingAgent
    from src.ai.tool_gateway import ServerSecurityContext
    monkeypatch.setattr(model_gateway, "local_provider", _FixedReplyProvider(reply))
    result = await QuotePricingAgent().execute(
        AgentInput(conversation_id="c", turn_id="t", user_prompt="Bonjour",
                   evidence={"verified_prices": {"INV-HYB-3K": 3000.0}}),
        ServerSecurityContext(tenant_id="t_grounding", user_id="u", role="quote_pricing")
    )
    assert result.status == expected
    if expected == "REJECTED_GUARD":
        assert "6000" not in result.response_text and "payée" not in result.response_text


@pytest.mark.asyncio
async def test_agent_records_handoff_when_model_unavailable(monkeypatch):
    from src.ai.model_gateway import model_gateway
    from src.ai.providers.ollama_provider import OllamaProvider
    from src.ai.agents.base import AgentInput
    from src.ai.agents.interactive.product import ProductKnowledgeAgent
    from src.ai.tool_gateway import ServerSecurityContext
    monkeypatch.setattr(model_gateway, "local_provider", OllamaProvider(base_url="http://127.0.0.1:9"))
    result = await ProductKnowledgeAgent().execute(
        AgentInput(conversation_id="c", turn_id="t", user_prompt="Bonjour"),
        ServerSecurityContext(tenant_id="t_handoff", user_id="u", role="product_knowledge")
    )
    assert result.status == "MODEL_UNAVAILABLE_HANDOFF"
    assert "conseiller humain" in result.response_text
