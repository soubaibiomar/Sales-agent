"""
Unit & Security Tests for Manager Voice Copilot: Safe Business Queries,
High-Risk Spoken Rejection, Action Previews, and Step-Up MFA.
Step 07: Dual-Mode Customer & Manager Voice AI
(Controls 04, 05, 06, 09, 34, 40, 55, 65, 66, 67; SAI-02, SAI-07, SAI-08)
"""
import pytest
from contextlib import asynccontextmanager
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.backend.models.entities import Base, SalesOrder, Quote, InventoryItem, SupportTicket
from src.backend.voice.manager_copilot import ManagerVoiceCopilot
from src.backend.voice.security import VoiceSecurityError


@asynccontextmanager
async def get_test_voice_env():
    unique_id = uuid.uuid4().hex
    engine = create_async_engine(
        f"sqlite+aiosqlite:///file:memdb_mgr_{unique_id}?mode=memory&cache=shared&uri=true",
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
async def test_manager_copilot_safe_sales_and_approval_insights():
    async with get_test_voice_env() as session:
        tenant_id = "t_mgr_01"
        manager_id = "u_director_01"

        # Seed paid sales order
        so = SalesOrder(
            id="so_mgr_01",
            tenant_id=tenant_id,
            order_number="ORD-20261118-MGR",
            status="PAID",
            currency="MAD",
            subtotal_cents=2500000,
            tax_total_cents=500000,
            grand_total_cents=3000000,  # 30,000 MAD
            terms_hash="terms_mgr_01"
        )
        session.add(so)

        # Seed pending quote
        q = Quote(
            id="q_mgr_01",
            tenant_id=tenant_id,
            quote_number="QUO-20261118-001",
            status="PENDING_APPROVAL",
            version=1,
            currency="MAD",
            subtotal_cents=5000000,
            tax_total_cents=1000000,
            grand_total_cents=6000000,
            terms_hash="terms_q_01",
            valid_until=datetime.now(timezone.utc) + timedelta(days=30)
        )
        session.add(q)
        await session.flush()

        copilot = ManagerVoiceCopilot(session, tenant_id, manager_id)

        # 1. Query sales revenue
        res_sales = await copilot.process_manager_command("Donne-moi le chiffre d'affaires et les ventes")
        assert res_sales["requires_confirmation"] is False
        assert "30,000.00 MAD" in res_sales["insight_text"] or "30000" in res_sales["insight_text"]

        # 2. Query pending quotes
        res_quotes = await copilot.process_manager_command("Quels sont les devis en attente d'approbation ?")
        assert res_quotes["requires_confirmation"] is False
        assert "1 devis" in res_quotes["insight_text"]


@pytest.mark.asyncio
async def test_manager_copilot_high_risk_spoken_rejection_and_action_preview():
    async with get_test_voice_env() as session:
        tenant_id = "t_mgr_02"
        manager_id = "u_director_02"
        copilot = ManagerVoiceCopilot(session, tenant_id, manager_id)

        # INVARIANT: Spoken commands alone CANNOT execute high-risk operations!
        # High-risk request: approve purchase order
        res_action = await copilot.process_manager_command("Approuve le bon de commande fournisseur PO-99")
        assert res_action["requires_confirmation"] is True
        assert res_action["action_preview"] is not None
        assert res_action["action_preview"]["risk_level"] == "HIGH"
        assert res_action["action_preview"]["requires_step_up_mfa"] is True
        assert "seuil d'autorisation vocale" in res_action["insight_text"]

        action_token = res_action["action_preview"]["action_token"]

        # Attempt to confirm WITHOUT valid step-up MFA token fails closed
        with pytest.raises(VoiceSecurityError, match="Step-Up TOTP code required"):
            await copilot.action_guard.consume_action(action_token, tenant_id=tenant_id, user_id=manager_id, step_up_verified=False)

        # Confirmation with valid 6-digit TOTP token succeeds
        # A different user (even with a verified second factor) cannot consume the token
        with pytest.raises(VoiceSecurityError, match="not issued to this user"):
            await copilot.action_guard.consume_action(action_token, tenant_id=tenant_id, user_id="someone_else", step_up_verified=True)

        # Server-verified step-up (TOTP checked against the enrolled seed by the API layer) succeeds
        confirmed = await copilot.action_guard.consume_action(action_token, tenant_id=tenant_id, user_id=manager_id, step_up_verified=True)
        assert confirmed["action_type"] == "APPROVE_PURCHASE_ORDER"
        assert confirmed["user_id"] == manager_id
