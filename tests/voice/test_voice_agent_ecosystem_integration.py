"""
Customer Voice AI & Step 09 Agent Ecosystem Integration Tests.
Supervisor turn fencing, human takeover silencing, tool provenance,
and verified vs unverified customer caller routing.
Step 10: Complete Customer Voice AI & Manager Voice AI Copilot
(Controls 39, 40, 65, 67; Invariants 1, 2, 4, 6)
"""
import pytest
import uuid
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.backend.models.entities import Base, SalesOrder
from src.backend.voice.customer_agent import CustomerVoiceAgent
from src.ai.agents.base import AgentInput
from src.ai.tool_gateway import ServerSecurityContext


@asynccontextmanager
async def setup_voice_ecosystem_db():
    unique_id = uuid.uuid4().hex
    engine = create_async_engine(
        f"sqlite+aiosqlite:///file:memdb_voice_eco_{unique_id}?mode=memory&cache=shared&uri=true",
        echo=False
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.mark.asyncio
async def test_customer_voice_human_takeover_silencing():
    async with setup_voice_ecosystem_db() as session:
        tenant_id = "t_eco_01"
        agent = CustomerVoiceAgent(session, tenant_id)
        session_id = f"voice_conv_{uuid.uuid4().hex[:8]}"

        # 1. First turn: normal AI response
        res1 = await agent.process_turn(
            session_id=session_id,
            user_utterance="Bonjour, avez-vous des ordinateurs en stock ?",
            is_caller_verified=False
        )
        assert res1["handoff_triggered"] is False
        assert "Laptop" in res1["agent_response"] or "disponibles" in res1["agent_response"]

        # 2. Human escalation triggered by customer
        res_esc = await agent.process_turn(
            session_id=session_id,
            user_utterance="Je veux parler à un responsable humain s'il vous plaît",
            is_caller_verified=False
        )
        assert res_esc["handoff_triggered"] is True
        assert agent.supervisor.is_human_owned(session_id) is True

        # 3. Subsequent turn while human takeover is active:
        # INVARIANT: Human ownership suppresses autonomous AI turns!
        res_silenced = await agent.process_turn(
            session_id=session_id,
            user_utterance="Pouvez-vous me répondre ?",
            is_caller_verified=False
        )
        assert res_silenced["handoff_triggered"] is True
        assert "conseiller humain" in res_silenced["agent_response"]

        # 4. Release human takeover -> AI autonomy resumes
        agent.supervisor.release_human_takeover(session_id)
        assert agent.supervisor.is_human_owned(session_id) is False

        res_resumed = await agent.process_turn(
            session_id=session_id,
            user_utterance="Quel est le délai de livraison ?",
            is_caller_verified=False
        )
        assert res_resumed["handoff_triggered"] is False


@pytest.mark.asyncio
async def test_customer_voice_supervisor_turn_fencing_and_routing():
    async with setup_voice_ecosystem_db() as session:
        tenant_id = "t_eco_02"
        agent = CustomerVoiceAgent(session, tenant_id)
        session_id = f"voice_fence_{uuid.uuid4().hex[:8]}"

        # Turn advancing via supervisor
        inp1 = AgentInput(
            user_prompt="Bonjour, je souhaite un devis",
            channel="VOICE",
            conversation_id=session_id
        )
        sec_ctx = ServerSecurityContext(tenant_id=tenant_id, user_id="u_caller", role="CUSTOMER")

        out1 = await agent.supervisor.handle_turn(inp1, sec_ctx, expected_turn_version=0, db_session=session)
        assert out1.status in ("SUCCESS", "BOUNDED_REASONING")

        # Stale turn rejection: submitting with stale expected version 0 when current is 1
        out_stale = await agent.supervisor.handle_turn(inp1, sec_ctx, expected_turn_version=0, db_session=session)
        assert out_stale.status == "ERROR"
        assert "Stale turn rejected" in out_stale.response_text


@pytest.mark.asyncio
async def test_verified_customer_order_lookup_provenance():
    async with setup_voice_ecosystem_db() as session:
        tenant_id = "t_eco_03"
        order_num = "ORD-20261119-VERIF"

        # Seed paid sales order
        so = SalesOrder(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            order_number=order_num,
            status="PAID",
            currency="MAD",
            subtotal_cents=1500000,
            tax_total_cents=300000,
            grand_total_cents=1800000,
            terms_hash="terms_eco_01"
        )
        session.add(so)
        await session.flush()

        agent = CustomerVoiceAgent(session, tenant_id)
        session_id = f"voice_verif_{uuid.uuid4().hex[:8]}"

        # Query with verified caller
        res = await agent.process_turn(
            session_id=session_id,
            user_utterance=f"Quel est le statut de ma commande {order_num} ?",
            is_caller_verified=True,
            caller_id="+212600112233"
        )
        assert res.get("requires_verification") is not True
        assert "PAID" in res["agent_response"]
        assert len(res["executed_tools"]) > 0
        assert res["executed_tools"][0]["tool_name"] == "get_order_status"
