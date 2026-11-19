"""
Expanded Query Tests for Manager Voice Copilot across 12 Commerce Domains.
Telemetry queries for pipeline valuation, logistics shipments, supplier POs,
agent execution logs, durable workflows, and high-risk mutation guards.
Step 10: Complete Customer Voice AI & Manager Voice AI Copilot
(Controls 04, 05, 06, 09, 34, 40, 55, 65, 66, 67; SAI-02, SAI-07, SAI-08)
"""
import pytest
import uuid
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.backend.models.entities import (
    Base,
    SalesOrder,
    Quote,
    InventoryItem,
    SupportTicket,
    PurchaseOrder,
    Shipment,
    AgentExecutionLog,
    WorkflowExecution
)
from src.backend.voice.manager_copilot import ManagerVoiceCopilot
from src.backend.voice.security import VoiceSecurityError


@asynccontextmanager
async def setup_manager_db():
    unique_id = uuid.uuid4().hex
    engine = create_async_engine(
        f"sqlite+aiosqlite:///file:memdb_mgr_exp_{unique_id}?mode=memory&cache=shared&uri=true",
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
async def test_manager_pipeline_and_shipments_telemetry():
    async with setup_manager_db() as session:
        tenant_id = "t_mgr_exp_01"
        manager_id = "u_mgr_director"

        # 1. Seed active quotes for pipeline valuation
        q1 = Quote(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            quote_number="QUO-PIPE-01",
            status="SUBMITTED",
            version=1,
            currency="MAD",
            subtotal_cents=10000000,
            tax_total_cents=2000000,
            grand_total_cents=12000000,  # 120,000 MAD
            terms_hash="th1",
            valid_until=datetime.now(timezone.utc) + timedelta(days=15)
        )
        q2 = Quote(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            quote_number="QUO-PIPE-02",
            status="DRAFT",
            version=1,
            currency="MAD",
            subtotal_cents=5000000,
            tax_total_cents=1000000,
            grand_total_cents=6000000,  # 60,000 MAD
            terms_hash="th2",
            valid_until=datetime.now(timezone.utc) + timedelta(days=15)
        )
        session.add_all([q1, q2])

        # 2. Seed pending shipments
        s1 = Shipment(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            shipment_number="SHP-20261119-01",
            order_id="ord_01",
            warehouse_id="wh_01",
            carrier_code="AMANA",
            status="IN_TRANSIT"
        )
        s2 = Shipment(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            shipment_number="SHP-20261119-02",
            order_id="ord_02",
            warehouse_id="wh_01",
            carrier_code="DHL",
            status="READY_FOR_PICKUP"
        )
        session.add_all([s1, s2])

        await session.flush()

        copilot = ManagerVoiceCopilot(session, tenant_id, manager_id)

        # Query Pipeline Value
        res_pipe = await copilot.process_manager_command("Donne-moi la valeur du pipeline commercial")
        assert res_pipe["requires_confirmation"] is False
        assert "180,000.00 MAD" in res_pipe["insight_text"] or "180000" in res_pipe["insight_text"]
        assert "2 devis" in res_pipe["insight_text"]

        # Query Shipments Telemetry
        res_ship = await copilot.process_manager_command("Combien de commandes restent à expédier et livrer ?")
        assert res_ship["requires_confirmation"] is False
        assert "2 expéditions" in res_ship["insight_text"]


@pytest.mark.asyncio
async def test_manager_agent_health_and_po_telemetry():
    async with setup_manager_db() as session:
        tenant_id = "t_mgr_exp_02"
        manager_id = "u_mgr_director"

        # 1. Seed Purchase Order
        po = PurchaseOrder(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            po_number="PO-SUPPLIER-01",
            supplier_id="sup_01",
            warehouse_id="wh_01",
            status="SUBMITTED",
            currency="MAD",
            subtotal_cents=8000000,
            tax_cents=1600000,
            grand_total_cents=9600000
        )
        session.add(po)

        # 2. Seed Failed Agent Execution Log
        agent_log = AgentExecutionLog(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            conversation_id="conv_err_01",
            agent_role="pricing_optimization_analyst",
            execution_class="BOUNDED_REASONING",
            turn_id=1,
            trace_id="trc_err_01",
            model_name="qwen3.5:4b",
            status="ERROR",
            error_details="Market volatility timeout"
        )
        session.add(agent_log)

        # 3. Seed Workflow Execution
        wf = WorkflowExecution(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            workflow_type="ORDER_FULFILLMENT",
            correlation_id=f"corr_{uuid.uuid4().hex[:8]}",
            idempotency_key=f"idem_{uuid.uuid4().hex[:8]}",
            status="RUNNING",
            payload_json={"order_id": "ord_wf_01"}
        )
        session.add(wf)

        await session.flush()

        copilot = ManagerVoiceCopilot(session, tenant_id, manager_id)

        # Query Supplier PO status
        res_po = await copilot.process_manager_command("Quel est l'état des commandes fournisseurs ?")
        assert res_po["requires_confirmation"] is False
        assert "1 bons de commande" in res_po["insight_text"]

        # Query Failed Agents
        res_agents = await copilot.process_manager_command("Quels agents ont échoué aujourd'hui ?")
        assert res_agents["requires_confirmation"] is False
        assert "1 exécutions d'agents" in res_agents["insight_text"]

        # Query Durable Workflows
        res_wf = await copilot.process_manager_command("Quel est l'état des workflows en cours ?")
        assert res_wf["requires_confirmation"] is False
        assert "1 sagas et flux" in res_wf["insight_text"]


@pytest.mark.asyncio
async def test_manager_high_risk_order_cancellation_and_bulk_mutation_guard():
    async with setup_manager_db() as session:
        tenant_id = "t_mgr_exp_03"
        manager_id = "u_mgr_director"
        copilot = ManagerVoiceCopilot(session, tenant_id, manager_id)

        # 1. Order cancellation spoken command
        res_cancel = await copilot.process_manager_command("Annule la commande ORD-998877 immédiatement")
        assert res_cancel["requires_confirmation"] is True
        assert res_cancel["action_preview"]["action_type"] == "CANCEL_ORDER"
        assert res_cancel["action_preview"]["requires_step_up_mfa"] is True

        # 2. Bulk data mutation spoken command
        res_bulk = await copilot.process_manager_command("Supprime les devis périmés de la base")
        assert res_bulk["requires_confirmation"] is True
        assert res_bulk["action_preview"]["action_type"] == "BULK_DATA_MUTATION"
