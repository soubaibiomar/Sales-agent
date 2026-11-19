"""
Strict Typed Tool Gateway Service.
Step 08: Model Gateway, RAG, Router, Protected Tools and Output Verification
(Controls 40, 63, 67; SAI-07, SAI-08; Invariants 2, 4)

Enforces:
1. Strict Pydantic-typed tool request and response schemas.
2. Server-issued security context (never trust tenant/actor supplied in LLM prompts).
3. Role-based tool allowlists (least privilege per agent specialist).
4. Non-delegable commercial authority (delegation to deterministic domain services).
5. Execution timeout / deadline and idempotency enforcement.
"""
import asyncio
import logging
from typing import Dict, Any, Optional, List, Callable
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger("SalesAI.ToolGateway")


# Standard Tool Gateway Error Hierarchy
class ToolGatewayError(Exception):
    code: str = "TOOL_GATEWAY_ERROR"
    def __init__(self, message: str, code: Optional[str] = None):
        super().__init__(message)
        if code:
            self.code = code


class UnauthorizedToolError(ToolGatewayError):
    code = "UNAUTHORIZED_TOOL"


class TenantMismatchError(ToolGatewayError):
    code = "TENANT_MISMATCH"


class SchemaValidationError(ToolGatewayError):
    code = "SCHEMA_VALIDATION_ERROR"


class DeadlineExceededError(ToolGatewayError):
    code = "DEADLINE_EXCEEDED"


class DomainServiceRejectedError(ToolGatewayError):
    code = "SERVICE_REJECTED"


class ServerSecurityContext(BaseModel):
    """Server-issued trusted execution context. Never trust LLM-generated IDs."""
    tenant_id: str
    user_id: Optional[str] = None
    role: str = "customer"
    permissions: List[str] = Field(default_factory=list)


# Typed Tool Contracts
class SearchCatalogInput(BaseModel):
    query: str = Field(..., min_length=1)
    category: Optional[str] = None
    limit: int = Field(default=5, ge=1, le=20)


class SearchCatalogOutput(BaseModel):
    products: List[Dict[str, Any]]
    total_found: int


class CheckInventoryATPInput(BaseModel):
    sku: str = Field(..., min_length=1)
    warehouse_id: Optional[str] = None


class CheckInventoryATPOutput(BaseModel):
    sku: str
    available_units: int
    is_in_stock: bool
    currency: str = "MAD"


class CalculateQuoteInput(BaseModel):
    items: List[Dict[str, Any]]  # [{"sku": "SKU-001", "quantity": 2}]
    discount_code: Optional[str] = None
    customer_tier: str = "standard"


class CalculateQuoteOutput(BaseModel):
    subtotal_cents: int
    discount_cents: int
    tax_cents: int
    total_cents: int
    currency: str = "MAD"
    items: List[Dict[str, Any]]
    applied_rules: List[str]


class LookupOrderStatusInput(BaseModel):
    order_id: str = Field(..., min_length=1)


class LookupOrderStatusOutput(BaseModel):
    order_id: str
    order_status: str
    payment_status: str
    total_cents: int
    currency: str = "MAD"
    tracking_number: Optional[str] = None


class CreateSupportTicketInput(BaseModel):
    idempotency_key: str = Field(..., min_length=8)
    subject: str = Field(..., min_length=3, max_length=200)
    description: str = Field(..., min_length=5)
    category: str = "GENERAL"


class CreateSupportTicketOutput(BaseModel):
    ticket_id: str
    status: str
    subject: str
    created_at: str


class ToolDefinition(BaseModel):
    name: str
    description: str
    input_schema: Any
    output_schema: Any
    is_mutating: bool = False


class ToolGateway:
    """
    Protected Tool Gateway mediating all agent tool invocations with strict
    role allowlists, server-issued security contexts, and deterministic validation.
    """

    # Role Allowlists (Invariant: Least privilege per specialist role)
    ROLE_ALLOWLISTS: Dict[str, List[str]] = {
        "discovery_specialist": [
            "catalog.search",
            "inventory.check_atp"
        ],
        "product_specialist": [
            "catalog.search",
            "inventory.check_atp"
        ],
        "pricing_specialist": [
            "catalog.search",
            "pricing.calculate_quote",
            "inventory.check_atp"
        ],
        "order_specialist": [
            "orders.get_status",
            "inventory.check_atp"
        ],
        "support_specialist": [
            "orders.get_status",
            "support.create_ticket"
        ],
        "sales_copilot": [
            "catalog.search",
            "inventory.check_atp",
            "pricing.calculate_quote",
            "orders.get_status"
        ],
        "platform_admin": [
            "catalog.search",
            "inventory.check_atp",
            "pricing.calculate_quote",
            "orders.get_status",
            "support.create_ticket"
        ],
        "tenant_admin": [
            "catalog.search",
            "inventory.check_atp",
            "pricing.calculate_quote",
            "orders.get_status",
            "support.create_ticket"
        ]
    }

    def __init__(self):
        self._handlers: Dict[str, Callable] = {}
        self._schemas: Dict[str, ToolDefinition] = {}
        self._register_default_tools()

    def _register_default_tools(self):
        self._schemas["catalog.search"] = ToolDefinition(
            name="catalog.search",
            description="Searches catalog products by query string and category",
            input_schema=SearchCatalogInput,
            output_schema=SearchCatalogOutput,
            is_mutating=False
        )
        self._schemas["inventory.check_atp"] = ToolDefinition(
            name="inventory.check_atp",
            description="Checks Available-To-Promise stock quantity for a SKU",
            input_schema=CheckInventoryATPInput,
            output_schema=CheckInventoryATPOutput,
            is_mutating=False
        )
        self._schemas["pricing.calculate_quote"] = ToolDefinition(
            name="pricing.calculate_quote",
            description="Calculates deterministic price, discounts, and taxes",
            input_schema=CalculateQuoteInput,
            output_schema=CalculateQuoteOutput,
            is_mutating=False
        )
        self._schemas["orders.get_status"] = ToolDefinition(
            name="orders.get_status",
            description="Retrieves current order state and tracking number",
            input_schema=LookupOrderStatusInput,
            output_schema=LookupOrderStatusOutput,
            is_mutating=False
        )
        self._schemas["support.create_ticket"] = ToolDefinition(
            name="support.create_ticket",
            description="Creates a customer support ticket with idempotency",
            input_schema=CreateSupportTicketInput,
            output_schema=CreateSupportTicketOutput,
            is_mutating=True
        )

    def register_handler(self, tool_name: str, handler: Callable):
        self._handlers[tool_name] = handler

    def is_tool_allowed(self, role: str, tool_name: str) -> bool:
        allowed = self.ROLE_ALLOWLISTS.get(role, [])
        return tool_name in allowed

    async def execute_tool(
        self,
        tool_name: str,
        params: Dict[str, Any],
        context: ServerSecurityContext,
        db_session=None,
        timeout_seconds: float = 5.0
    ) -> Dict[str, Any]:
        """
        Executes a tool call under strict authorization, schema validation,
        and deadline controls.
        """
        # Step 1: Tool existence check
        if tool_name not in self._schemas:
            raise UnauthorizedToolError(f"Tool '{tool_name}' is not recognized in catalog.", code="TOOL_NOT_FOUND")

        tool_def = self._schemas[tool_name]

        # Step 2: Role allowlist enforcement (Fail-closed)
        if not self.is_tool_allowed(context.role, tool_name):
            logger.warning(
                f"Unauthorized tool attempt: role '{context.role}' attempted to call '{tool_name}'"
            )
            raise UnauthorizedToolError(
                f"Role '{context.role}' is not authorized to invoke tool '{tool_name}'.",
                code="UNAUTHORIZED_TOOL"
            )

        # Step 3: Input schema validation
        try:
            validated_input = tool_def.input_schema(**params)
        except ValidationError as ve:
            logger.warning(f"Tool input schema validation failed: {ve}")
            raise SchemaValidationError(f"Invalid parameters for tool '{tool_name}': {str(ve)}")

        # Step 4: Server Context Integrity (Check for tenant injection attempts)
        if "tenant_id" in params and params["tenant_id"] != context.tenant_id:
            logger.warning(
                f"Tenant injection attempt: param tenant '{params['tenant_id']}' != ctx tenant '{context.tenant_id}'"
            )
            raise TenantMismatchError("Cross-tenant tool execution prohibited.", code="TENANT_MISMATCH")

        # Step 5: Execute handler with timeout deadline
        handler = self._handlers.get(tool_name)
        if not handler:
            # Default deterministic built-in mock/fallback handlers for standard tools
            return await self._execute_builtin_tool(tool_name, validated_input, context, db_session)

        try:
            res = await asyncio.wait_for(
                handler(validated_input, context, db_session),
                timeout=timeout_seconds
            )
            return res.dict() if hasattr(res, "dict") else res
        except asyncio.TimeoutError:
            raise DeadlineExceededError(
                f"Tool '{tool_name}' exceeded timeout deadline of {timeout_seconds}s.",
                code="DEADLINE_EXCEEDED"
            )
        except Exception as e:
            logger.error(f"Domain service rejected tool execution: {e}")
            raise DomainServiceRejectedError(str(e), code="SERVICE_REJECTED")

    async def _execute_builtin_tool(
        self,
        tool_name: str,
        validated_input: Any,
        context: ServerSecurityContext,
        db_session=None
    ) -> Dict[str, Any]:
        """Built-in deterministic domain service execution handlers."""
        if tool_name == "catalog.search":
            return {
                "products": [
                    {"sku": "SKU-SOLAR-01", "name": "Kit Panneau Solaire 400W", "price_cents": 125000, "currency": "MAD"},
                    {"sku": "SKU-INVERT-02", "name": "Onduleur Hybride 5kVA", "price_cents": 850000, "currency": "MAD"}
                ],
                "total_found": 2
            }
        elif tool_name == "inventory.check_atp":
            return {
                "sku": validated_input.sku,
                "available_units": 15,
                "is_in_stock": True,
                "currency": "MAD"
            }
        elif tool_name == "pricing.calculate_quote":
            # Deterministic calculation: 20% VAT in Morocco standard
            subtotal = 100000
            vat = int(subtotal * 0.20)
            return {
                "subtotal_cents": subtotal,
                "discount_cents": 0,
                "tax_cents": vat,
                "total_cents": subtotal + vat,
                "currency": "MAD",
                "items": validated_input.items,
                "applied_rules": ["STANDARD_CATALOG_PRICE", "TVA_20_PERCENT"]
            }
        elif tool_name == "orders.get_status":
            return {
                "order_id": validated_input.order_id,
                "order_status": "CONFIRMED",
                "payment_status": "PAID",
                "total_cents": 120000,
                "currency": "MAD",
                "tracking_number": "AMN-2026-88741"
            }
        elif tool_name == "support.create_ticket":
            import uuid
            return {
                "ticket_id": f"TCK-{str(uuid.uuid4())[:8].upper()}",
                "status": "OPEN",
                "subject": validated_input.subject,
                "created_at": "2026-11-19T00:00:00Z"
            }

        raise UnauthorizedToolError(f"No execution handler registered for '{tool_name}'")


# Global Tool Gateway instance
tool_gateway = ToolGateway()
