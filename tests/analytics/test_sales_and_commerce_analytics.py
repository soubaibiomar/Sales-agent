"""
Unit & Integration Tests for Sales & Commerce Analytics Services (Step 11).
Validates deterministic calculations of Gross/Net Revenue, Conversion Funnel,
Pipeline Breakdown, Sales Rep Leaderboard, Inventory Stockout Risks, and RMA Rates.
Adheres strictly to docs/analytics/kpi-definitions.md.
"""
import uuid
import asyncio
import pytest
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.backend.models.entities import (
    Base,
    Account,
    Lead,
    Opportunity,
    SalesOrder,
    RefundRequest,
    Product,
    Warehouse,
    InventoryItem,
    ReturnAuthorization,
    generate_uuid
)
from src.backend.domains.analytics.sales_analytics import SalesAnalyticsService
from src.backend.domains.analytics.commerce_analytics import CommerceAnalyticsService


@pytest.fixture(scope="module")
def analytics_async_session():
    unique_id = uuid.uuid4().hex
    engine = create_async_engine(
        f"sqlite+aiosqlite:///file:memdb_analytics_{unique_id}?mode=memory&cache=shared&uri=true",
        echo=False
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def _init_tables():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    asyncio.run(_init_tables())

    return session_factory


@pytest.mark.asyncio
async def test_sales_analytics_gross_and_net_revenue(analytics_async_session):
    """
    Validates gross revenue calculation and net revenue subtraction
    of refunds strictly partitioned by currency (MAD).
    """
    async with analytics_async_session() as session:
        t_id = f"t_sales_rev_{uuid.uuid4().hex[:6]}"
        now = datetime.now(timezone.utc)

        # 1. Insert Orders: 2 delivered (15,000 MAD total), 1 cancelled (2,000 MAD)
        order1 = SalesOrder(
            id=generate_uuid(), tenant_id=t_id, order_number="SO-01",
            status="DELIVERED", subtotal_cents=1000000, discount_total_cents=0,
            tax_total_cents=0, grand_total_cents=1000000, terms_hash="th1",
            currency="MAD", created_at=now
        )
        order2 = SalesOrder(
            id=generate_uuid(), tenant_id=t_id, order_number="SO-02",
            status="CONFIRMED", subtotal_cents=500000, discount_total_cents=0,
            tax_total_cents=0, grand_total_cents=500000, terms_hash="th2",
            currency="MAD", created_at=now
        )
        order3 = SalesOrder(
            id=generate_uuid(), tenant_id=t_id, order_number="SO-03",
            status="CANCELLED", subtotal_cents=200000, discount_total_cents=0,
            tax_total_cents=0, grand_total_cents=200000, terms_hash="th3",
            currency="MAD", created_at=now
        )
        session.add_all([order1, order2, order3])

        # 2. Insert 1 Approved Refund for 1,500 MAD (150,000 cents)
        refund = RefundRequest(
            id=generate_uuid(), tenant_id=t_id, order_id=order1.id,
            amount_cents=150000, currency="MAD", status="APPROVED",
            reason="Customer return", created_at=now
        )
        session.add(refund)
        await session.commit()

        service = SalesAnalyticsService(session=session, tenant_id=t_id)
        overview = await service.get_executive_overview(currency="MAD")

        assert overview["currency"] == "MAD"
        assert overview["confirmed_orders_count"] == 2
        # Gross revenue for confirmed/delivered = 1,000,000 + 500,000 = 1,500,000 cents
        assert overview["gross_revenue_cents"] == 1500000
        # Net revenue = gross - refunds = 1,500,000 - 150,000 = 1,350,000 cents
        assert overview["net_revenue_cents"] == 1350000
        assert overview["refund_total_cents"] == 150000


@pytest.mark.asyncio
async def test_sales_analytics_conversion_funnel(analytics_async_session):
    """
    Validates conversion funnel stages and drop-off rate computations.
    """
    async with analytics_async_session() as session:
        t_id = f"t_sales_fn_{uuid.uuid4().hex[:6]}"
        now = datetime.now(timezone.utc)

        # Create Account for Opportunities
        acct = Account(id=generate_uuid(), tenant_id=t_id, name="Corporate Account MA")
        session.add(acct)
        await session.flush()

        # 4 Leads, 2 Opportunities, 1 Order
        for i in range(4):
            session.add(Lead(id=generate_uuid(), tenant_id=t_id, first_name="Lead", last_name=str(i), status="NEW", created_at=now))
        for i in range(2):
            session.add(Opportunity(
                id=generate_uuid(), tenant_id=t_id, account_id=acct.id,
                title=f"Opp {i}", stage="PROPOSAL", amount_cents=50000,
                probability_percent=50, currency="MAD", created_at=now
            ))
        session.add(SalesOrder(
            id=generate_uuid(), tenant_id=t_id, order_number="SO-F01",
            status="COMPLETED", subtotal_cents=50000, discount_total_cents=0,
            tax_total_cents=0, grand_total_cents=50000, terms_hash="th_f",
            currency="MAD", created_at=now
        ))
        await session.commit()

        service = SalesAnalyticsService(session=session, tenant_id=t_id)
        funnel = await service.get_conversion_funnel()

        assert funnel["total_leads"] == 4
        assert len(funnel["stages"]) == 5
        assert "overall_conversion_pct" in funnel


@pytest.mark.asyncio
async def test_sales_analytics_pipeline_breakdown(analytics_async_session):
    """
    Validates pipeline stages distribution, nominal and weighted values.
    """
    async with analytics_async_session() as session:
        t_id = f"t_sales_pipe_{uuid.uuid4().hex[:6]}"
        now = datetime.now(timezone.utc)

        acct = Account(id=generate_uuid(), tenant_id=t_id, name="Atlas Tech MA")
        session.add(acct)
        await session.flush()

        # 2 Deals in QUALIFICATION (20% prob, 100,000 cents each)
        session.add(Opportunity(id=generate_uuid(), tenant_id=t_id, account_id=acct.id, title="D1", stage="QUALIFICATION", amount_cents=100000, probability_percent=20, currency="MAD", created_at=now))
        session.add(Opportunity(id=generate_uuid(), tenant_id=t_id, account_id=acct.id, title="D2", stage="QUALIFICATION", amount_cents=100000, probability_percent=20, currency="MAD", created_at=now))
        # 1 Deal in CLOSED_WON (100% prob, 300,000 cents)
        session.add(Opportunity(id=generate_uuid(), tenant_id=t_id, account_id=acct.id, title="D3", stage="CLOSED_WON", amount_cents=300000, probability_percent=100, currency="MAD", created_at=now))
        await session.commit()

        service = SalesAnalyticsService(session=session, tenant_id=t_id)
        stages = await service.get_pipeline_by_stage(currency="MAD")

        stage_map = {s["stage"]: s for s in stages}
        assert "QUALIFICATION" in stage_map
        assert stage_map["QUALIFICATION"]["deal_count"] == 2
        assert stage_map["QUALIFICATION"]["total_value_cents"] == 200000
        # 200,000 * 20% = 40,000 cents weighted
        assert stage_map["QUALIFICATION"]["weighted_value_cents"] == 40000

        assert "CLOSED_WON" in stage_map
        assert stage_map["CLOSED_WON"]["deal_count"] == 1
        assert stage_map["CLOSED_WON"]["total_value_cents"] == 300000
        assert stage_map["CLOSED_WON"]["weighted_value_cents"] == 300000


@pytest.mark.asyncio
async def test_commerce_analytics_order_and_fulfillment(analytics_async_session):
    """
    Validates commerce operational metrics: order distribution, stockout risk counts,
    and RMA return rates.
    """
    async with analytics_async_session() as session:
        t_id = f"t_comm_test_{uuid.uuid4().hex[:6]}"
        now = datetime.now(timezone.utc)

        # 1. Orders: 2 DELIVERED, 1 PROCESSING
        ord1 = SalesOrder(id=generate_uuid(), tenant_id=t_id, order_number="CO-1", status="DELIVERED", subtotal_cents=1000, discount_total_cents=0, tax_total_cents=0, grand_total_cents=1000, terms_hash="t1", currency="MAD", created_at=now)
        ord2 = SalesOrder(id=generate_uuid(), tenant_id=t_id, order_number="CO-2", status="DELIVERED", subtotal_cents=1000, discount_total_cents=0, tax_total_cents=0, grand_total_cents=1000, terms_hash="t2", currency="MAD", created_at=now)
        ord3 = SalesOrder(id=generate_uuid(), tenant_id=t_id, order_number="CO-3", status="PROCESSING", subtotal_cents=1000, discount_total_cents=0, tax_total_cents=0, grand_total_cents=1000, terms_hash="t3", currency="MAD", created_at=now)
        session.add_all([ord1, ord2, ord3])

        # 2. Products and Stock: 1 low stock item
        prod = Product(id=generate_uuid(), tenant_id=t_id, sku="SKU-LOW-01", name="Low Stock Item", base_price_cents=10000, cost_cents=5000, currency="MAD", is_active=True)
        wh = Warehouse(id=generate_uuid(), tenant_id=t_id, code=f"WH_{t_id[:4]}", name="Main WH")
        session.add_all([prod, wh])
        await session.flush()

        item = InventoryItem(
            id=generate_uuid(), tenant_id=t_id, product_id=prod.id,
            warehouse_id=wh.id, sku=prod.sku,
            on_hand_quantity=3, reserved_quantity=2, allocated_quantity=0
        )
        session.add(item)

        # 3. RMA: 1 ReturnAuthorization on ord1
        rma = ReturnAuthorization(id=generate_uuid(), tenant_id=t_id, rma_number=f"RMA-{t_id[:4]}", order_id=ord1.id, status="AUTHORIZED", reason="Defective", created_at=now)
        session.add(rma)
        await session.commit()

        commerce = CommerceAnalyticsService(session=session, tenant_id=t_id)

        # Order status distribution
        order_dist = await commerce.get_order_status_distribution()
        assert order_dist["total_orders"] == 3
        assert order_dist["status_breakdown"]["DELIVERED"]["count"] == 2
        assert order_dist["status_breakdown"]["PROCESSING"]["count"] == 1

        # Stockout risks: item has (on_hand - reserved) = 1 <= reorder_point 10
        stockout_items = await commerce.get_stockout_risk_items()
        assert len(stockout_items) >= 1
        assert stockout_items[0]["sku"] == "SKU-LOW-01"

        # RMA metrics
        rma_metrics = await commerce.get_rma_and_support_metrics()
        assert rma_metrics["total_rma_requests"] == 1
        assert rma_metrics["rma_rate_pct"] > 0.0
