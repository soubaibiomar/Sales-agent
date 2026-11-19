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
    DeadlineExceededError
)


@pytest.mark.asyncio
async def test_tool_role_allowlist_enforcement():
    """Validates that specialists can only call tools in their role allowlist."""
    gateway = ToolGateway()

    # Product specialist calling authorized tool
    ctx_prod = ServerSecurityContext(tenant_id="tenant-acme", role="product_specialist")
    res_allowed = await gateway.execute_tool(
        tool_name="catalog.search",
        params={"query": "panneau"},
        context=ctx_prod
    )
    assert res_allowed["total_found"] >= 1

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

    res = await gateway.execute_tool(
        tool_name="pricing.calculate_quote",
        params={"items": [{"sku": "SKU-SOLAR-01", "quantity": 1}]},
        context=ctx
    )

    assert res["currency"] == "MAD"
    assert res["subtotal_cents"] == 100000
    assert res["tax_cents"] == 20000  # 20% TVA in Morocco
    assert res["total_cents"] == 120000
    assert "TVA_20_PERCENT" in res["applied_rules"]
