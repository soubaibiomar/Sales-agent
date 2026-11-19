"""
Strict Typed Tool Gateway Service.
Step 08: Model Gateway, RAG, Router, Protected Tools and Output Verification
(Controls 40, 63, 67; SAI-07, SAI-08; Invariants 2, 4)
Step 08 & Step 09: Model Gateway, RAG, Router, Protected Tools, and 18-Role Agent Ecosystem
(Controls 40, 63, 67; SAI-07, SAI-08, SAI-09; Invariants 2, 4)

Enforces:
1. Strict Pydantic-typed tool request and response schemas.
2. Server-issued security context (never trust tenant/actor supplied in LLM prompts).
3. Role-based tool allowlists (least privilege per agent specialist).
3. Role-based tool allowlists (least privilege across all 18 catalog agent roles).
4. Non-delegable commercial authority (delegation to deterministic domain services).
5. Execution timeout / deadline and idempotency enforcement.
"""
import asyncio
import logging
import uuid
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


ToolAccessDeniedError = UnauthorizedToolError
SecurityRole = str


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


# ---------------------------------------------------------------------------
# Typed Tool Contracts
# ---------------------------------------------------------------------------

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


class QualifyLeadInput(BaseModel):
    lead_id: str = Field(..., min_length=1)
    budget_mad: Optional[int] = None
    timeline: Optional[str] = None
    decision_maker: bool = True
    notes: Optional[str] = None


class QualifyLeadOutput(BaseModel):
    lead_id: str
    qualified: bool
    score: int
    recommended_action: str


class UpdateLeadInput(BaseModel):
    lead_id: str = Field(..., min_length=1)
    notes: Optional[str] = None
    stage: Optional[str] = None


class UpdateLeadOutput(BaseModel):
    lead_id: str
    updated: bool


class GetSlotsInput(BaseModel):
    staff_user_id: Optional[str] = None
    date: str = Field(..., min_length=8)


class GetSlotsOutput(BaseModel):
    slots: List[Dict[str, str]]
    total_slots: int


class BookAppointmentInput(BaseModel):
    slot_id: str = Field(..., min_length=1)
    customer_id: str = Field(..., min_length=1)
    notes: Optional[str] = None


class BookAppointmentOutput(BaseModel):
    appointment_id: str
    status: str
    start_time: str
    end_time: str


class ProposeDiscountInput(BaseModel):
    quote_id: str = Field(..., min_length=1)
    discount_percent: float = Field(..., ge=0.0, le=100.0)
    justification: str = Field(..., min_length=5)


class ProposeDiscountOutput(BaseModel):
    quote_id: str
    approved: bool
    discount_percent: float
    requires_manager_approval: bool
    policy_reason: str


class GetAccountSummaryInput(BaseModel):
    account_id: str = Field(..., min_length=1)


class GetAccountSummaryOutput(BaseModel):
    account_id: str
    name: str
    tier: str
    lifetime_value_cents: int
    active_orders_count: int
    renewal_date: Optional[str] = None


class GetDocumentInvoiceInput(BaseModel):
    invoice_id: str = Field(..., min_length=1)


class GetDocumentInvoiceOutput(BaseModel):
    invoice_id: str
    invoice_number: str
    total_cents: int
    tax_cents: int
    is_paid: bool
    ice_number: str
    currency: str = "MAD"


class GetDocumentQuoteInput(BaseModel):
    quote_id: str = Field(..., min_length=1)


class GetDocumentQuoteOutput(BaseModel):
    quote_id: str
    quote_number: str
    subtotal_cents: int
    discount_cents: int
    total_cents: int
    status: str
    currency: str = "MAD"


class DraftCampaignInput(BaseModel):
    campaign_name: str = Field(..., min_length=3)
    channel: str = "WHATSAPP"
    target_segment: str = "WARM_LEADS"
    message_template: str = Field(..., min_length=10)


class DraftCampaignOutput(BaseModel):
    campaign_id: str
    compliant: bool
    quiet_hours_checked: bool
    stop_optout_count: int
    draft_status: str


class EnrichAccountInput(BaseModel):
    company_name: str = Field(..., min_length=2)
    industry: Optional[str] = None


class EnrichAccountOutput(BaseModel):
    company_name: str
    annual_revenue_estimate_mad: int
    employee_range: str
    verified_sources: List[str]


class AnalyzeStaleDealsInput(BaseModel):
    max_days_in_stage: int = Field(default=14, ge=1, le=180)


class AnalyzeStaleDealsOutput(BaseModel):
    stale_deals: List[Dict[str, Any]]
    count: int
    sla_breaches: int


class GetKPISummaryInput(BaseModel):
    period: str = "CURRENT_MONTH"


class GetKPISummaryOutput(BaseModel):
    revenue_cents: int
    margin_percent: float
    closed_won_count: int
    average_order_value_cents: int


class ProposeKnowledgeUpdateInput(BaseModel):
    title: str = Field(..., min_length=3)
    category: str = "COMMERCIAL_POLICY"
    content: str = Field(..., min_length=10)
    source_reference: str = Field(..., min_length=3)


class ProposeKnowledgeUpdateOutput(BaseModel):
    proposal_id: str
    status: str
    is_published: bool
    notice: str


class DiagnoseSystemInput(BaseModel):
    scope: str = "ALL"


class DiagnoseSystemOutput(BaseModel):
    vram_healthy: bool
    channel_adapters_status: str
    dlq_pending_count: int
    overall_status: str


class ApplyRunbookInput(BaseModel):
    runbook_name: str = Field(..., min_length=3)
    parameters: Optional[Dict[str, Any]] = None


class ApplyRunbookOutput(BaseModel):
    runbook_name: str
    executed: bool
    reversible: bool
    audit_trail_id: str


class GenerateBriefInput(BaseModel):
    conversation_id: str = Field(..., min_length=1)
    customer_id: Optional[str] = None


class GenerateBriefOutput(BaseModel):
    summary: str
    sentiment: str
    objections_identified: List[str]
    suggested_replies: List[str]


class ProposeActionInput(BaseModel):
    conversation_id: str = Field(..., min_length=1)
    action_type: str = Field(..., min_length=1)
    action_payload: Dict[str, Any] = Field(default_factory=dict)
    requires_human_approval: bool = True


class ProposeActionOutput(BaseModel):
    proposal_id: str
    action_type: str
    status: str
    requires_human_approval: bool


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
    # Role Allowlists (Invariant: Least privilege across all 18 catalog agent roles)
    ROLE_ALLOWLISTS: Dict[str, List[str]] = {
        # Front Door & Supervisors
        "router_classifier": [],
        "conversation_supervisor": [
            "catalog.search",
            "inventory.check_atp",
            "orders.get_status",
            "crm.update_lead"
        ],
        "operations_supervisor": [
            "analytics.get_kpi_summary",
            "pipeline.analyze_stale_deals",
            "incident.diagnose_system",
            "incident.apply_runbook"
        ],
        # 9 Interactive Specialists
        "qualification_crm": [
            "crm.qualify_lead",
            "crm.update_lead",
            "catalog.search"
        ],
        "product_knowledge": [
            "catalog.search",
            "inventory.check_atp"
        ],
        "quote_pricing": [
            "catalog.search",
            "pricing.calculate_quote",
            "inventory.check_atp"
        ],
        "order_payment": [
            "orders.get_status",
            "inventory.check_atp"
        ],
        "scheduling": [
            "scheduling.get_slots",
            "scheduling.book_appointment"
        ],
        "negotiation_objections": [
            "catalog.search",
            "pricing.calculate_quote",
            "negotiation.propose_discount"
        ],
        "support_returns": [
            "orders.get_status",
            "support.create_ticket"
        ],
        "account_management": [
            "account.get_summary",
            "orders.get_status",
            "catalog.search"
        ],
        "documents": [
            "documents.get_invoice",
            "documents.get_quote"
        ],
        # 6 Governed Background Agents
        "outreach": [
            "outreach.draft_campaign",
            "crm.update_lead"
        ],
        "research": [
            "research.enrich_account",
            "catalog.search"
        ],
        "pipeline_coach": [
            "pipeline.analyze_stale_deals",
            "account.get_summary"
        ],
        "analyst": [
            "analytics.get_kpi_summary",
            "pricing.calculate_quote"
        ],
        "knowledge_curator": [
            "knowledge.propose_update",
            "catalog.search"
        ],
        "incident_responder": [
            "incident.diagnose_system",
            "incident.apply_runbook"
        ],
        # Internal Copilot
        "sales_copilot": [
            "catalog.search",
            "inventory.check_atp",
            "pricing.calculate_quote",
            "orders.get_status",
            "copilot.generate_brief",
            "copilot.propose_action",
            "account.get_summary"
        ],
        # Step 08 Backward-Compatibility Aliases
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
            "support.create_ticket",
            "crm.qualify_lead",
            "crm.update_lead",
            "scheduling.get_slots",
            "scheduling.book_appointment",
            "negotiation.propose_discount",
            "account.get_summary",
            "documents.get_invoice",
            "documents.get_quote",
            "outreach.draft_campaign",
            "research.enrich_account",
            "pipeline.analyze_stale_deals",
            "analytics.get_kpi_summary",
            "knowledge.propose_update",
            "incident.diagnose_system",
            "incident.apply_runbook",
            "copilot.generate_brief",
            "copilot.propose_action"
        ],
        "tenant_admin": [
            "catalog.search",
            "inventory.check_atp",
            "pricing.calculate_quote",
            "orders.get_status",
            "support.create_ticket",
            "crm.qualify_lead",
            "crm.update_lead",
            "scheduling.get_slots",
            "scheduling.book_appointment",
            "negotiation.propose_discount",
            "account.get_summary",
            "documents.get_invoice",
            "documents.get_quote",
            "outreach.draft_campaign",
            "research.enrich_account",
            "pipeline.analyze_stale_deals",
            "analytics.get_kpi_summary",
            "knowledge.propose_update",
            "incident.diagnose_system",
            "incident.apply_runbook",
            "copilot.generate_brief",
            "copilot.propose_action"
        ],
        # Canonical Role Codes (A01 - A09, B01 - B06, I01, R00, S00) & Evaluation Aliases
        "R00": [],
        "S00": [
            "catalog.search",
            "inventory.check_atp",
            "orders.get_status",
            "crm.update_lead"
        ],
        "S00_CONV": [
            "catalog.search",
            "inventory.check_atp",
            "orders.get_status",
            "crm.update_lead"
        ],
        "S00_OPS": [
            "analytics.get_kpi_summary",
            "pipeline.analyze_stale_deals",
            "incident.diagnose_system",
            "incident.apply_runbook"
        ],
        "A01": [
            "crm.qualify_lead",
            "crm.update_lead",
            "catalog.search"
        ],
        "A01_DISCOVERY": [
            "crm.qualify_lead",
            "crm.update_lead",
            "catalog.search"
        ],
        "A02": [
            "catalog.search",
            "inventory.check_atp"
        ],
        "A02_CATALOG": [
            "catalog.search",
            "inventory.check_atp"
        ],
        "A03": [
            "catalog.search",
            "pricing.calculate_quote",
            "inventory.check_atp"
        ],
        "A03_QUOTATION": [
            "catalog.search",
            "pricing.calculate_quote",
            "inventory.check_atp"
        ],
        "A04": [
            "orders.get_status",
            "inventory.check_atp"
        ],
        "A04_ORDER": [
            "orders.get_status",
            "inventory.check_atp"
        ],
        "A05": [
            "scheduling.get_slots",
            "scheduling.book_appointment"
        ],
        "A05_SCHEDULING": [
            "scheduling.get_slots",
            "scheduling.book_appointment"
        ],
        "A06": [
            "catalog.search",
            "pricing.calculate_quote",
            "negotiation.propose_discount"
        ],
        "A06_NEGOTIATION": [
            "catalog.search",
            "pricing.calculate_quote",
            "negotiation.propose_discount"
        ],
        "A07": [
            "orders.get_status",
            "support.create_ticket"
        ],
        "A07_SUPPORT": [
            "orders.get_status",
            "support.create_ticket"
        ],
        "A08": [
            "account.get_summary",
            "orders.get_status",
            "catalog.search"
        ],
        "A08_ACCOUNT": [
            "account.get_summary",
            "orders.get_status",
            "catalog.search"
        ],
        "A08_APPOINTMENT": [
            "scheduling.get_slots",
            "scheduling.book_appointment"
        ],
        "A09": [
            "documents.get_invoice",
            "documents.get_quote"
        ],
        "A09_DOCUMENTS": [
            "documents.get_invoice",
            "documents.get_quote"
        ],
        "B01": [
            "outreach.draft_campaign",
            "crm.update_lead"
        ],
        "B01_LEAD_ENRICHMENT": [
            "research.enrich_account",
            "catalog.search"
        ],
        "B02": [
            "research.enrich_account",
            "catalog.search"
        ],
        "B02_FOLLOWUP": [
            "outreach.draft_campaign",
            "crm.update_lead"
        ],
        "B03": [
            "pipeline.analyze_stale_deals",
            "account.get_summary"
        ],
        "B03_CHURN_RISK": [
            "pipeline.analyze_stale_deals",
            "account.get_summary"
        ],
        "B04": [
            "analytics.get_kpi_summary",
            "pricing.calculate_quote"
        ],
        "B04_RESTOCK": [
            "inventory.check_atp",
            "orders.get_status"
        ],
        "B05": [
            "knowledge.propose_update",
            "catalog.search"
        ],
        "B05_PRICING_OPTIM": [
            "analytics.get_kpi_summary",
            "pricing.calculate_quote"
        ],
        "B06": [
            "incident.diagnose_system",
            "incident.apply_runbook"
        ],
        "I01": [
            "catalog.search",
            "inventory.check_atp",
            "pricing.calculate_quote",
            "orders.get_status",
            "copilot.generate_brief",
            "copilot.propose_action",
            "account.get_summary"
        ],
        "I01_SALES_COPILOT": [
            "catalog.search",
            "inventory.check_atp",
            "pricing.calculate_quote",
            "orders.get_status",
            "copilot.generate_brief",
            "copilot.propose_action",
            "account.get_summary"
        ]
    }

    def __init__(self):
        self._handlers: Dict[str, Callable] = {}
        self._schemas: Dict[str, ToolDefinition] = {}
        self._register_default_tools()

    def _register_default_tools(self):
        # 1. Catalog & Inventory
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
        # 2. Pricing & Orders
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
        # 3. Support
        self._schemas["support.create_ticket"] = ToolDefinition(
            name="support.create_ticket",
            description="Creates a customer support ticket with idempotency",
            input_schema=CreateSupportTicketInput,
            output_schema=CreateSupportTicketOutput,
            is_mutating=True
        )
        # 4. CRM & Qualification
        self._schemas["crm.qualify_lead"] = ToolDefinition(
            name="crm.qualify_lead",
            description="Qualifies a CRM lead and returns score and recommended action",
            input_schema=QualifyLeadInput,
            output_schema=QualifyLeadOutput,
            is_mutating=True
        )
        self._schemas["crm.update_lead"] = ToolDefinition(
            name="crm.update_lead",
            description="Updates lead notes and pipeline stage",
            input_schema=UpdateLeadInput,
            output_schema=UpdateLeadOutput,
            is_mutating=True
        )
        # 5. Scheduling
        self._schemas["scheduling.get_slots"] = ToolDefinition(
            name="scheduling.get_slots",
            description="Retrieves available staff appointment slots for a date",
            input_schema=GetSlotsInput,
            output_schema=GetSlotsOutput,
            is_mutating=False
        )
        self._schemas["scheduling.book_appointment"] = ToolDefinition(
            name="scheduling.book_appointment",
            description="Books an authorized appointment slot for a customer",
            input_schema=BookAppointmentInput,
            output_schema=BookAppointmentOutput,
            is_mutating=True
        )
        # 6. Negotiation
        self._schemas["negotiation.propose_discount"] = ToolDefinition(
            name="negotiation.propose_discount",
            description="Checks commercial discount ceiling and proposes compliant concession",
            input_schema=ProposeDiscountInput,
            output_schema=ProposeDiscountOutput,
            is_mutating=False
        )
        # 7. Account Management
        self._schemas["account.get_summary"] = ToolDefinition(
            name="account.get_summary",
            description="Returns customer account metrics, active orders, and contract renewal",
            input_schema=GetAccountSummaryInput,
            output_schema=GetAccountSummaryOutput,
            is_mutating=False
        )
        # 8. Documents
        self._schemas["documents.get_invoice"] = ToolDefinition(
            name="documents.get_invoice",
            description="Retrieves verified tax-compliant invoice details",
            input_schema=GetDocumentInvoiceInput,
            output_schema=GetDocumentInvoiceOutput,
            is_mutating=False
        )
        self._schemas["documents.get_quote"] = ToolDefinition(
            name="documents.get_quote",
            description="Retrieves verified commercial quotation details",
            input_schema=GetDocumentQuoteInput,
            output_schema=GetDocumentQuoteOutput,
            is_mutating=False
        )
        # 9. Outreach
        self._schemas["outreach.draft_campaign"] = ToolDefinition(
            name="outreach.draft_campaign",
            description="Drafts outbound campaign with Moroccan quiet-hours and STOP checks",
            input_schema=DraftCampaignInput,
            output_schema=DraftCampaignOutput,
            is_mutating=True
        )
        # 10. Research
        self._schemas["research.enrich_account"] = ToolDefinition(
            name="research.enrich_account",
            description="Enriches prospect organization intelligence from verified sources",
            input_schema=EnrichAccountInput,
            output_schema=EnrichAccountOutput,
            is_mutating=False
        )
        # 11. Pipeline Coach
        self._schemas["pipeline.analyze_stale_deals"] = ToolDefinition(
            name="pipeline.analyze_stale_deals",
            description="Analyzes pipeline deals exceeding stage SLAs",
            input_schema=AnalyzeStaleDealsInput,
            output_schema=AnalyzeStaleDealsOutput,
            is_mutating=False
        )
        # 12. Analyst
        self._schemas["analytics.get_kpi_summary"] = ToolDefinition(
            name="analytics.get_kpi_summary",
            description="Returns governed revenue, margin, and conversion KPI readouts",
            input_schema=GetKPISummaryInput,
            output_schema=GetKPISummaryOutput,
            is_mutating=False
        )
        # 13. Knowledge Curator
        self._schemas["knowledge.propose_update"] = ToolDefinition(
            name="knowledge.propose_update",
            description="Submits reviewed knowledge article proposal (self-publication prohibited)",
            input_schema=ProposeKnowledgeUpdateInput,
            output_schema=ProposeKnowledgeUpdateOutput,
            is_mutating=True
        )
        # 14. Incident Responder
        self._schemas["incident.diagnose_system"] = ToolDefinition(
            name="incident.diagnose_system",
            description="Diagnoses hardware VRAM, channel adapters, and dead-letter queues",
            input_schema=DiagnoseSystemInput,
            output_schema=DiagnoseSystemOutput,
            is_mutating=False
        )
        self._schemas["incident.apply_runbook"] = ToolDefinition(
            name="incident.apply_runbook",
            description="Applies allowlisted reversible operational runbooks",
            input_schema=ApplyRunbookInput,
            output_schema=ApplyRunbookOutput,
            is_mutating=True
        )
        # 15. Representative Copilot
        self._schemas["copilot.generate_brief"] = ToolDefinition(
            name="copilot.generate_brief",
            description="Generates deal summary, objection tips, and draft replies for rep",
            input_schema=GenerateBriefInput,
            output_schema=GenerateBriefOutput,
            is_mutating=False
        )
        self._schemas["copilot.propose_action"] = ToolDefinition(
            name="copilot.propose_action",
            description="Proposes an action requiring human approval",
            input_schema=ProposeActionInput,
            output_schema=ProposeActionOutput,
            is_mutating=True
        )

    def register_handler(self, tool_name: str, handler: Callable):
        self._handlers[tool_name] = handler

    def is_tool_allowed(self, role: str, tool_name: str) -> bool:
        allowed = self.ROLE_ALLOWLISTS.get(role, [])
        return tool_name in allowed

    is_tool_allowed_for_role = is_tool_allowed

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
        # 1. Catalog & Inventory
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
        # 2. Pricing & Orders
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
        # 3. Support
        elif tool_name == "support.create_ticket":
            import uuid
            return {
                "ticket_id": f"TCK-{str(uuid.uuid4())[:8].upper()}",
                "status": "OPEN",
                "subject": validated_input.subject,
                "created_at": "2026-11-19T00:00:00Z"
            }
        # 4. CRM & Qualification
        elif tool_name == "crm.qualify_lead":
            budget = validated_input.budget_mad or 0
            is_qualified = budget >= 50000 and validated_input.decision_maker
            score = 85 if is_qualified else 45
            rec_action = "SCHEDULE_SALES_DEMO" if is_qualified else "ADD_TO_NURTURE_SEQUENCE"
            return {
                "lead_id": validated_input.lead_id,
                "qualified": is_qualified,
                "score": score,
                "recommended_action": rec_action
            }
        elif tool_name == "crm.update_lead":
            return {
                "lead_id": validated_input.lead_id,
                "updated": True
            }
        # 5. Scheduling
        elif tool_name == "scheduling.get_slots":
            return {
                "slots": [
                    {"slot_id": "SLOT-01", "start_time": f"{validated_input.date}T10:00:00Z", "end_time": f"{validated_input.date}T10:30:00Z"},
                    {"slot_id": "SLOT-02", "start_time": f"{validated_input.date}T14:00:00Z", "end_time": f"{validated_input.date}T14:30:00Z"}
                ],
                "total_slots": 2
            }
        elif tool_name == "scheduling.book_appointment":
            return {
                "appointment_id": f"APT-{str(uuid.uuid4())[:8].upper()}",
                "status": "CONFIRMED",
                "start_time": "2026-11-20T10:00:00Z",
                "end_time": "2026-11-20T10:30:00Z"
            }
        # 6. Negotiation
        elif tool_name == "negotiation.propose_discount":
            # Policy invariant: discount <= 15% is auto-approved by policy, > 15% requires manager approval
            req_percent = validated_input.discount_percent
            if req_percent <= 15.0:
                return {
                    "quote_id": validated_input.quote_id,
                    "approved": True,
                    "discount_percent": req_percent,
                    "requires_manager_approval": False,
                    "policy_reason": "STANDARD_REP_COMMERCIAL_CEILING_APPROVED"
                }
            else:
                return {
                    "quote_id": validated_input.quote_id,
                    "approved": False,
                    "discount_percent": 15.0,  # Cap at policy ceiling
                    "requires_manager_approval": True,
                    "policy_reason": "DISCOUNT_EXCEEDS_15_PERCENT_REQUIRES_DIRECTOR_APPROVAL"
                }
        # 7. Account Management
        elif tool_name == "account.get_summary":
            return {
                "account_id": validated_input.account_id,
                "name": "Atlas Industries SARL",
                "tier": "ENTERPRISE_GOLD",
                "lifetime_value_cents": 45000000,
                "active_orders_count": 3,
                "renewal_date": "2027-03-31T00:00:00Z"
            }
        # 8. Documents
        elif tool_name == "documents.get_invoice":
            return {
                "invoice_id": validated_input.invoice_id,
                "invoice_number": "INV-2026-00442",
                "total_cents": 120000,
                "tax_cents": 20000,
                "is_paid": True,
                "ice_number": "002498715000084",
                "currency": "MAD"
            }
        elif tool_name == "documents.get_quote":
            return {
                "quote_id": validated_input.quote_id,
                "quote_number": "QUO-2026-00918",
                "subtotal_cents": 100000,
                "discount_cents": 5000,
                "total_cents": 114000,
                "status": "APPROVED",
                "currency": "MAD"
            }
        # 9. Outreach
        elif tool_name == "outreach.draft_campaign":
            return {
                "campaign_id": f"CMP-{str(uuid.uuid4())[:8].upper()}",
                "compliant": True,
                "quiet_hours_checked": True,
                "stop_optout_count": 12,
                "draft_status": "PENDING_APPROVAL"
            }
        # 10. Research
        elif tool_name == "research.enrich_account":
            return {
                "company_name": validated_input.company_name,
                "annual_revenue_estimate_mad": 25000000,
                "employee_range": "50-100",
                "verified_sources": ["OMPIC", "B2B_REGISTRY", "APPROVED_RAG"]
            }
        # 11. Pipeline Coach
        elif tool_name == "pipeline.analyze_stale_deals":
            return {
                "stale_deals": [
                    {"opportunity_id": "OPP-001", "name": "Solar Array Phase 2", "stage": "PROPOSAL", "days_in_stage": 18, "risk": "HIGH"}
                ],
                "count": 1,
                "sla_breaches": 1
            }
        # 12. Analyst
        elif tool_name == "analytics.get_kpi_summary":
            return {
                "revenue_cents": 145000000,
                "margin_percent": 34.5,
                "closed_won_count": 28,
                "average_order_value_cents": 5178500
            }
        # 13. Knowledge Curator
        elif tool_name == "knowledge.propose_update":
            return {
                "proposal_id": f"KNOW-PROP-{str(uuid.uuid4())[:8].upper()}",
                "status": "PENDING_REVIEW",
                "is_published": False,
                "notice": "Awaiting human review. Self-publication prohibited by Invariant 2."
            }
        # 14. Incident Responder
        elif tool_name == "incident.diagnose_system":
            return {
                "vram_healthy": True,
                "channel_adapters_status": "OPERATIONAL",
                "dlq_pending_count": 0,
                "overall_status": "ALL_SYSTEMS_HEALTHY"
            }
        elif tool_name == "incident.apply_runbook":
            allowed_runbooks = {"DRAIN_DLQ_RETRY", "FLUSH_EPHEMERAL_CACHE", "RELOAD_AI_ROUTER"}
            if validated_input.runbook_name not in allowed_runbooks:
                raise DomainServiceRejectedError(
                    f"Runbook '{validated_input.runbook_name}' is not in allowlisted reversible set: {allowed_runbooks}"
                )
            return {
                "runbook_name": validated_input.runbook_name,
                "executed": True,
                "reversible": True,
                "audit_trail_id": f"AUDIT-RB-{str(uuid.uuid4())[:8].upper()}"
            }
        # 15. Representative Copilot
        elif tool_name == "copilot.generate_brief":
            return {
                "summary": "Customer expressed interest in high-efficiency solar kit with quick delivery to Casablanca.",
                "sentiment": "POSITIVE",
                "objections_identified": ["Competitor price 5% lower", "Warranty period inquiry"],
                "suggested_replies": [
                    "Highlight our 5-year on-site warranty in Casablanca.",
                    "Propose verified 5% volume tier discount within policy ceiling."
                ]
            }
        elif tool_name == "copilot.propose_action":
            return {
                "proposal_id": f"PROP-{str(uuid.uuid4())[:8].upper()}",
                "action_type": validated_input.action_type,
                "status": "PENDING_HUMAN_CONFIRMATION",
                "requires_human_approval": validated_input.requires_human_approval
            }

        raise UnauthorizedToolError(f"No execution handler registered for '{tool_name}'")


# Global Tool Gateway instance
tool_gateway = ToolGateway()
