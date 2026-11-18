"""
Contract and API Route Tests for Workflows, Notifications, and Integrations.
Step 07: Durable Workflows, Notifications and Peripheral Integrations
(Controls 28, 31, 42-44, 57-59, 63-64; SAI-11; ADR-007)
"""
import pytest
import uuid
from httpx import AsyncClient, ASGITransport
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.backend.models.entities import Base, Tenant, Warehouse, Product, InventoryItem
from src.backend.main import app
from src.backend.core.database import get_db_session


@asynccontextmanager
async def override_workflow_api_dependencies():
    unique_id = uuid.uuid4().hex
    engine = create_async_engine(
        f"sqlite+aiosqlite:///file:memdb_wf_api_{unique_id}?mode=memory&cache=shared&uri=true",
        echo=False
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed initial test data
    tenant_id = "tenant-api-test"
    wh_id = "wh-api-test"
    sku = "SKU-TEST-01"

    async with session_factory() as session:
        tenant = Tenant(id=tenant_id, name="API Test Tenant", slug="api-tenant")
        wh = Warehouse(id=wh_id, tenant_id=tenant_id, name="Main Hub", code="WH-MAIN")
        prod = Product(id="prod-01", tenant_id=tenant_id, sku=sku, name="Test Item", base_price_cents=1000)
        item = InventoryItem(
            id="item-01",
            tenant_id=tenant_id,
            warehouse_id=wh_id,
            product_id="prod-01",
            sku=sku,
            on_hand_quantity=50,
            reserved_quantity=0,
            allocated_quantity=0
        )
        session.add_all([tenant, wh, prod, item])
        await session.commit()

    async def _get_test_db():
        async with session_factory() as session:
            yield session
            await session.commit()

    app.dependency_overrides[get_db_session] = _get_test_db
    yield
    app.dependency_overrides.clear()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.mark.asyncio
async def test_workflow_executions_api_lifecycle():
    async with override_workflow_api_dependencies():
        tenant_id = "tenant-api-test"
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = {"X-Tenant-Id": tenant_id}

            # 1. Trigger Workflow Execution
            resp_trigger = await client.post(
                "/api/v1/workflows/executions",
                headers=headers,
                json={
                    "workflow_type": "DAILY_RECONCILIATION",
                    "workflow_name": "Test API Daily Reconciliation",
                    "idempotency_key": "idemp-api-test-01",
                    "input_payload": {}
                }
            )
            assert resp_trigger.status_code == 201
            data = resp_trigger.json()
            assert data["workflow_type"] == "DAILY_RECONCILIATION"
            assert data["status"] == "COMPLETED"
            exec_id = data["id"]

            # 2. List Executions
            resp_list = await client.get("/api/v1/workflows/executions", headers=headers)
            assert resp_list.status_code == 200
            list_data = resp_list.json()
            assert len(list_data) >= 1

            # 3. Get Execution Detail
            resp_detail = await client.get(f"/api/v1/workflows/executions/{exec_id}", headers=headers)
            assert resp_detail.status_code == 200
            detail_data = resp_detail.json()
            assert detail_data["id"] == exec_id
            assert len(detail_data["step_logs"]) >= 1

            # 4. Trigger Crash Recovery
            resp_rec = await client.post("/api/v1/workflows/recovery/resume", headers=headers)
            assert resp_rec.status_code == 200
            assert "resumed_count" in resp_rec.json()


@pytest.mark.asyncio
async def test_notifications_api_lifecycle():
    async with override_workflow_api_dependencies():
        tenant_id = "tenant-api-test"
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = {"X-Tenant-Id": tenant_id}

            # 1. Send Transactional Notification
            resp_send = await client.post(
                "/api/v1/notifications/send",
                headers=headers,
                json={
                    "recipient": "+212612345678",
                    "channel": "WHATSAPP",
                    "message_class": "TRANSACTIONAL",
                    "template_name": "ORDER_CONFIRMED",
                    "variables": {"order_id": "ORD-99", "total": "500 MAD"}
                }
            )
            assert resp_send.status_code == 201
            notif_data = resp_send.json()
            assert notif_data["status"] == "DELIVERED"

            # 2. Get Notification History
            resp_history = await client.get("/api/v1/notifications/history", headers=headers)
            assert resp_history.status_code == 200
            hist = resp_history.json()
            assert len(hist) >= 1

            # 3. Record Inbound Opt-Out
            resp_optout = await client.post(
                "/api/v1/notifications/opt-out",
                headers=headers,
                json={
                    "recipient": "+212612345678",
                    "channel": "WHATSAPP",
                    "inbound_message_text": "Baraka safi ma bghitch"
                }
            )
            assert resp_optout.status_code == 200
            opt_data = resp_optout.json()
            assert opt_data["opted_out"] is True
            assert opt_data["matched_keyword"] == "baraka"


@pytest.mark.asyncio
async def test_integrations_and_n8n_barrier_api():
    async with override_workflow_api_dependencies():
        tenant_id = "tenant-api-test"
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = {"X-Tenant-Id": tenant_id}

            # 1. Get Integration Status & DLQ metrics
            resp_status = await client.get("/api/v1/integrations/status", headers=headers)
            assert resp_status.status_code == 200
            status_data = resp_status.json()
            assert "n8n_security_barrier" in status_data
            assert status_data["n8n_security_barrier"] == "ENFORCED"

            # 2. Test n8n Security Barrier: Commercial action blocked
            resp_barrier_block = await client.post(
                "/api/v1/integrations/n8n/verify-barrier",
                headers=headers,
                json={"action": "quotes:approve"}
            )
            assert resp_barrier_block.status_code == 200
            data_block = resp_barrier_block.json()
            assert data_block["allowed"] is False
            assert "Invariant 7" in data_block["detail"]

            # 3. Test n8n Security Barrier: Non-commercial action allowed
            resp_barrier_allow = await client.post(
                "/api/v1/integrations/n8n/verify-barrier",
                headers=headers,
                json={"action": "leads:enrich_summary"}
            )
            assert resp_barrier_allow.status_code == 200
            data_allow = resp_barrier_allow.json()
            assert data_allow["allowed"] is True
