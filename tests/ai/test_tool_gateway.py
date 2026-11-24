"""
Tool Gateway Unit & Security Tests.
Step 08: Model Gateway, RAG, Router, Protected Tools and Output Verification
(Controls 40, 63, 67; SAI-07, SAI-08; Invariants 2, 4)
"""
import pytest
import asyncio
from src.ai.tool_gateway import (
    ToolGateway,
    ServerSecurityContext,
    UnauthorizedToolError,
    TenantMismatchError,
    SchemaValidationError,
    DeadlineExceededError,
    DomainServiceRejectedError
)
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool
from src.backend.models.entities import Base, Tenant, Product


@asynccontextmanager
async def seeded_catalog_session():
    """Commercial-fact tools answer only from tenant-scoped domain data (no fixtures)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False},
                                 poolclass=StaticPool)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as s:
        s.add(Tenant(id="tenant-acme", name="Acme", slug="acme"))
        s.add(Product(id="p-solar", tenant_id="tenant-acme", sku="SKU-SOLAR-01", name="Kit Panneau Solaire 400W",
                      base_price_cents=100000, cost_cents=60000, currency="MAD", tax_rate_percent=20))
        await s.commit()
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_tool_role_allowlist_enforcement():
    """Validates that specialists can only call tools in their role allowlist."""
    gateway = ToolGateway()

    # Product specialist calling authorized tool
    ctx_prod = ServerSecurityContext(tenant_id="tenant-acme", role="product_specialist")
    async with seeded_catalog_session() as db:
        res_allowed = await gateway.execute_tool(
            tool_name="catalog.search",
            params={"query": "panneau"},
            context=ctx_prod,
            db_session=db
        )
    assert res_allowed["total_found"] == 1
    assert res_allowed["products"][0]["sku"] == "SKU-SOLAR-01"

    # Without authoritative data the tool fails closed instead of inventing products
    with pytest.raises(DomainServiceRejectedError):
        await gateway.execute_tool(tool_name="catalog.search", params={"query": "panneau"}, context=ctx_prod)

    # Product specialist calling unauthorized tool (support ticket)
    with pytest.raises(UnauthorizedToolError) as exc_info:
        await gateway.execute_tool(
            tool_name="support.create_ticket",
            params={"idempotency_key": "IDEM-12345", "subject": "Test", "description": "Details"},
            context=ctx_prod
        )
    assert exc_info.value.code == "UNAUTHORIZED_TOOL"


@pytest.mark.asyncio
async def test_server_issued_security_context_tenant_injection_defense():
    """Validates that injected tenant IDs in tool parameters are rejected with TenantMismatchError."""
    gateway = ToolGateway()
    ctx = ServerSecurityContext(tenant_id="tenant-legit", role="product_specialist")

    # Injected rogue tenant_id inside params
    with pytest.raises(TenantMismatchError) as exc_info:
        await gateway.execute_tool(
            tool_name="catalog.search",
            params={"query": "panneau", "tenant_id": "tenant-attacker"},
            context=ctx
        )
    assert exc_info.value.code == "TENANT_MISMATCH"


@pytest.mark.asyncio
async def test_tool_schema_validation_failure():
    """Validates that schema validation fails closed on invalid parameters."""
    gateway = ToolGateway()
    ctx = ServerSecurityContext(tenant_id="tenant-acme", role="support_specialist")

    # Missing idempotency_key for create_ticket
    with pytest.raises(SchemaValidationError):
        await gateway.execute_tool(
            tool_name="support.create_ticket",
            params={"subject": "Short"},  # Missing idempotency_key and description
            context=ctx
        )


@pytest.mark.asyncio
async def test_tool_deadline_timeout_enforcement():
    """Validates that slow tool handlers exceeding deadline raise DeadlineExceededError."""
    gateway = ToolGateway()
    ctx = ServerSecurityContext(tenant_id="tenant-acme", role="product_specialist")

    # Register slow mock handler
    async def slow_handler(inp, context, db):
        await asyncio.sleep(0.3)
        return {"done": True}

    gateway.register_handler("catalog.search", slow_handler)

    with pytest.raises(DeadlineExceededError) as exc_info:
        await gateway.execute_tool(
            tool_name="catalog.search",
            params={"query": "panneau"},
            context=ctx,
            timeout_seconds=0.05
        )
    assert exc_info.value.code == "DEADLINE_EXCEEDED"


@pytest.mark.asyncio
async def test_deterministic_pricing_tool():
    """Validates that pricing tool produces deterministic Moroccan VAT calculations."""
    gateway = ToolGateway()
    ctx = ServerSecurityContext(tenant_id="tenant-acme", role="pricing_specialist")

    async with seeded_catalog_session() as db:
        res = await gateway.execute_tool(
            tool_name="pricing.calculate_quote",
            params={"items": [{"sku": "SKU-SOLAR-01", "quantity": 1}]},
            context=ctx,
            db_session=db
        )
        # Unknown SKU is rejected, never priced from a fixture
        with pytest.raises(DomainServiceRejectedError):
            await gateway.execute_tool(tool_name="pricing.calculate_quote",
                                       params={"items": [{"sku": "SKU-UNKNOWN", "quantity": 1}]},
                                       context=ctx, db_session=db)

    assert res["currency"] == "MAD"
    assert res["subtotal_cents"] == 100000
    assert res["tax_cents"] == 20000  # 20% TVA in Morocco, computed by PricingService
    assert res["total_cents"] == 120000
    assert "PRICING_SERVICE" in res["applied_rules"]
