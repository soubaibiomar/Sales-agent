"""
Agent Registry & 18-Role Capability Catalog.
Step 09: Complete 18-Role Agent Ecosystem & Sales Representative Copilot
(Controls 40, 63, 67; SAI-06 to SAI-12; Unified Architecture Section 2)

Registers all 18 logical roles:
1 Router/Classifier + 2 Supervisors + 9 Interactive Specialists + 6 Background Roles + 1 Rep Copilot.
Enforces:
- Exact role boundaries, allowed tools, retrieval roles, and model tiers.
- Context cap of 4096 tokens.
- Shared Model Gateway infrastructure (zero separate LLM processes).
"""
import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger("SalesAI.AgentRegistry")


class AgentRoleDefinition(BaseModel):
    role_id: str
    role_code: str
    role_group: str  # FRONT_DOOR, SUPERVISOR, INTERACTIVE_SPECIALIST, BACKGROUND_AGENT, COPILOT
    display_name: str
    description: str
    model_tier: str = "PRIMARY_4B"  # PRIMARY_4B or REASONING_9B
    context_token_cap: int = 4096
    allowed_tools: List[str] = Field(default_factory=list)
    retrieval_roles: List[str] = Field(default_factory=list)
    prompt_version: str = "v1.0"
    system_prompt: str = ""
    is_enabled: bool = True
    delegation_policy: List[str] = Field(default_factory=list)
    failure_policy: str = "SAFE_GROUNDED_FALLBACK"


# Master 18-Role Catalog Definitions
AGENT_CATALOG: Dict[str, AgentRoleDefinition] = {
    # ------------------------------------------------------------------------
    # Front Door & Supervisors
    # ------------------------------------------------------------------------
    "router_classifier": AgentRoleDefinition(
        role_id="router_classifier",
        role_code="R00",
        role_group="FRONT_DOOR",
        display_name="Inbound Router & Intent Classifier",
        description="Classifies intent, language (5 matrices), urgency, execution class, and prompt injection risk.",
        model_tier="PRIMARY_4B",
        context_token_cap=1024,
        allowed_tools=[],
        retrieval_roles=["public"],
        prompt_version="v1.0",
        system_prompt="You are the Inbound Router. Classify the customer language, intent, and execution class without side effects.",
        delegation_policy=["conversation_supervisor"],
        failure_policy="DIRECT_SAFE_READ"
    ),
    "conversation_supervisor": AgentRoleDefinition(
        role_id="conversation_supervisor",
        role_code="S00_CONV",
        role_group="SUPERVISOR",
        display_name="Conversation Supervisor",
        description="Owns the interactive conversation turn, selects specialists, manages handoffs, and silences AI on human takeover.",
        model_tier="PRIMARY_4B",
        context_token_cap=4096,
        allowed_tools=["catalog.search", "inventory.check_atp", "orders.get_status", "crm.update_lead"],
        retrieval_roles=["public", "sales_rep"],
        prompt_version="v1.0",
        system_prompt="You are the Conversation Supervisor. Coordinate interactive specialists, maintain turn ownership, and enforce human handoff.",
        delegation_policy=[
            "qualification_crm", "product_knowledge", "quote_pricing", "order_payment",
            "scheduling", "negotiation_objections", "support_returns", "account_management", "documents"
        ],
        failure_policy="SAFE_GROUNDED_FALLBACK"
    ),
    "operations_supervisor": AgentRoleDefinition(
        role_id="operations_supervisor",
        role_code="S00_OPS",
        role_group="SUPERVISOR",
        display_name="Operations & Background Supervisor",
        description="Coordinates governed background tasks, schedules batch pipelines, monitors SLAs, and triages system alerts.",
        model_tier="PRIMARY_4B",
        context_token_cap=4096,
        allowed_tools=["analytics.get_kpi_summary", "pipeline.analyze_stale_deals", "incident.diagnose_system", "incident.apply_runbook"],
        retrieval_roles=["manager", "admin"],
        prompt_version="v1.0",
        system_prompt="You are the Operations Supervisor. Manage background tasks, monitor worker queues, and ensure domain safety.",
        delegation_policy=["outreach", "research", "pipeline_coach", "analyst", "knowledge_curator", "incident_responder"],
        failure_policy="HOLD_FOR_OPERATOR_REVIEW"
    ),

    # ------------------------------------------------------------------------
    # 9 Interactive Specialists
    # ------------------------------------------------------------------------
    "qualification_crm": AgentRoleDefinition(
        role_id="qualification_crm",
        role_code="A01",
        role_group="INTERACTIVE_SPECIALIST",
        display_name="Qualification & CRM Specialist",
        description="Captures prospect requirements, calculates qualification scores, and requests scoped CRM updates.",
        model_tier="PRIMARY_4B",
        context_token_cap=4096,
        allowed_tools=["crm.qualify_lead", "crm.update_lead", "catalog.search"],
        retrieval_roles=["public", "sales_rep"],
        prompt_version="v1.0",
        system_prompt="You are the Qualification & CRM Specialist. Elicit customer needs, qualify opportunities, and update CRM records.",
        delegation_policy=["quote_pricing", "scheduling", "product_knowledge"],
        failure_policy="SAFE_GROUNDED_FALLBACK"
    ),
    "product_knowledge": AgentRoleDefinition(
        role_id="product_knowledge",
        role_code="A02",
        role_group="INTERACTIVE_SPECIALIST",
        display_name="Product & Catalog Specialist",
        description="Explains catalog features, technical specifications, and verified inventory availability using approved RAG.",
        model_tier="PRIMARY_4B",
        context_token_cap=4096,
        allowed_tools=["catalog.search", "inventory.check_atp"],
        retrieval_roles=["public", "sales_rep"],
        prompt_version="v1.0",
        system_prompt="You are the Product & Catalog Specialist. Present accurate product specifications and verified inventory availability.",
        delegation_policy=["quote_pricing", "qualification_crm"],
        failure_policy="SAFE_GROUNDED_FALLBACK"
    ),
    "quote_pricing": AgentRoleDefinition(
        role_id="quote_pricing",
        role_code="A03",
        role_group="INTERACTIVE_SPECIALIST",
        display_name="Quote & Pricing Specialist",
        description="Gathers quoting requirements and requests deterministic pricing. Never invents amounts or grants unauthorized discounts.",
        model_tier="PRIMARY_4B",
        context_token_cap=4096,
        allowed_tools=["catalog.search", "pricing.calculate_quote", "inventory.check_atp"],
        retrieval_roles=["public", "sales_rep"],
        prompt_version="v1.0",
        system_prompt="You are the Quote & Pricing Specialist. Build commercial proposals using strictly verified pricing calculations.",
        delegation_policy=["negotiation_objections", "order_payment"],
        failure_policy="SAFE_GROUNDED_FALLBACK"
    ),
    "order_payment": AgentRoleDefinition(
        role_id="order_payment",
        role_code="A04",
        role_group="INTERACTIVE_SPECIALIST",
        display_name="Order & Payment Specialist",
        description="Explains order progression and payment status using verified ledger evidence. Never marks orders paid from conversation.",
        model_tier="PRIMARY_4B",
        context_token_cap=4096,
        allowed_tools=["orders.get_status", "inventory.check_atp"],
        retrieval_roles=["public", "sales_rep"],
        prompt_version="v1.0",
        system_prompt="You are the Order & Payment Specialist. Guide customers through checkout and explain verified order status.",
        delegation_policy=["support_returns", "documents"],
        failure_policy="SAFE_GROUNDED_FALLBACK"
    ),
    "scheduling": AgentRoleDefinition(
        role_id="scheduling",
        role_code="A05",
        role_group="INTERACTIVE_SPECIALIST",
        display_name="Scheduling & Appointment Specialist",
        description="Retrieves staff availability and books authorized appointments through SchedulingService.",
        model_tier="PRIMARY_4B",
        context_token_cap=4096,
        allowed_tools=["scheduling.get_slots", "scheduling.book_appointment"],
        retrieval_roles=["public", "sales_rep"],
        prompt_version="v1.0",
        system_prompt="You are the Scheduling Specialist. Propose available appointment slots and confirm bookings without double-booking.",
        delegation_policy=["qualification_crm"],
        failure_policy="SAFE_GROUNDED_FALLBACK"
    ),
    "negotiation_objections": AgentRoleDefinition(
        role_id="negotiation_objections",
        role_code="A06",
        role_group="INTERACTIVE_SPECIALIST",
        display_name="Negotiation & Objections Specialist",
        description="Proposes compliant commercial alternatives within policy ceilings. Escalates discount requests exceeding 15% to management.",
        model_tier="PRIMARY_4B",
        context_token_cap=4096,
        allowed_tools=["catalog.search", "pricing.calculate_quote", "negotiation.propose_discount"],
        retrieval_roles=["public", "sales_rep"],
        prompt_version="v1.0",
        system_prompt="You are the Negotiation Specialist. Handle objections and propose value options within authorized policy limits.",
        delegation_policy=["quote_pricing"],
        failure_policy="SAFE_GROUNDED_FALLBACK"
    ),
    "support_returns": AgentRoleDefinition(
        role_id="support_returns",
        role_code="A07",
        role_group="INTERACTIVE_SPECIALIST",
        display_name="Support, Warranty & Returns Specialist",
        description="Assists with ticket triage, warranty claims, and return authorizations under domain validation.",
        model_tier="PRIMARY_4B",
        context_token_cap=4096,
        allowed_tools=["orders.get_status", "support.create_ticket"],
        retrieval_roles=["public", "support_agent"],
        prompt_version="v1.0",
        system_prompt="You are the Support Specialist. Handle post-sale issues, verify warranty eligibility, and create support tickets.",
        delegation_policy=["order_payment"],
        failure_policy="SAFE_GROUNDED_FALLBACK"
    ),
    "account_management": AgentRoleDefinition(
        role_id="account_management",
        role_code="A08",
        role_group="INTERACTIVE_SPECIALIST",
        display_name="Account Management & Renewals Specialist",
        description="Summarizes customer history, contract renewal dates, and reorder opportunities under strict tenant authorization.",
        model_tier="PRIMARY_4B",
        context_token_cap=4096,
        allowed_tools=["account.get_summary", "orders.get_status", "catalog.search"],
        retrieval_roles=["sales_rep", "manager"],
        prompt_version="v1.0",
        system_prompt="You are the Account Management Specialist. Monitor account health, track contract renewals, and identify reorders.",
        delegation_policy=["quote_pricing", "pipeline_coach"],
        failure_policy="SAFE_GROUNDED_FALLBACK"
    ),
    "documents": AgentRoleDefinition(
        role_id="documents",
        role_code="A09",
        role_group="INTERACTIVE_SPECIALIST",
        display_name="Commercial Documents Specialist",
        description="Retrieves and summarizes verified tax-compliant invoices and quotations. Issuance is strictly owned by domain services.",
        model_tier="PRIMARY_4B",
        context_token_cap=4096,
        allowed_tools=["documents.get_invoice", "documents.get_quote"],
        retrieval_roles=["sales_rep", "manager"],
        prompt_version="v1.0",
        system_prompt="You are the Documents Specialist. Provide verified invoice and quotation details without altering commercial figures.",
        delegation_policy=["order_payment"],
        failure_policy="SAFE_GROUNDED_FALLBACK"
    ),

    # ------------------------------------------------------------------------
    # 6 Governed Background Agents
    # ------------------------------------------------------------------------
    "outreach": AgentRoleDefinition(
        role_id="outreach",
        role_code="B01",
        role_group="BACKGROUND_AGENT",
        display_name="Outreach & Nurture Agent",
        description="Drafts outbound campaign content while respecting Moroccan quiet hours and multi-script STOP opt-outs.",
        model_tier="PRIMARY_4B",
        context_token_cap=4096,
        allowed_tools=["outreach.draft_campaign", "crm.update_lead"],
        retrieval_roles=["sales_rep", "marketing"],
        prompt_version="v1.0",
        system_prompt="You are the Outreach Agent. Propose targeted customer follow-ups conforming to communication consent rules.",
        delegation_policy=[],
        failure_policy="HOLD_FOR_OPERATOR_REVIEW"
    ),
    "research": AgentRoleDefinition(
        role_id="research",
        role_code="B02",
        role_group="BACKGROUND_AGENT",
        display_name="Account Research & Enrichment Agent",
        description="Enriches prospect and account intelligence using verified company records and authorized RAG context.",
        model_tier="PRIMARY_4B",
        context_token_cap=4096,
        allowed_tools=["research.enrich_account", "catalog.search"],
        retrieval_roles=["sales_rep", "manager"],
        prompt_version="v1.0",
        system_prompt="You are the Research Agent. Gather verified enterprise intelligence to enrich lead profiles.",
        delegation_policy=[],
        failure_policy="HOLD_FOR_OPERATOR_REVIEW"
    ),
    "pipeline_coach": AgentRoleDefinition(
        role_id="pipeline_coach",
        role_code="B03",
        role_group="BACKGROUND_AGENT",
        display_name="Pipeline Coach & Deal Monitor",
        description="Analyzes deal velocity, identifies stagnant opportunities, and recommends next-best actions for sales reps.",
        model_tier="PRIMARY_4B",
        context_token_cap=4096,
        allowed_tools=["pipeline.analyze_stale_deals", "account.get_summary"],
        retrieval_roles=["sales_rep", "manager"],
        prompt_version="v1.0",
        system_prompt="You are the Pipeline Coach. Audit deal health, detect stale pipelines, and suggest proactive closing steps.",
        delegation_policy=[],
        failure_policy="HOLD_FOR_OPERATOR_REVIEW"
    ),
    "analyst": AgentRoleDefinition(
        role_id="analyst",
        role_code="B04",
        role_group="BACKGROUND_AGENT",
        display_name="Sales & Pricing Analyst",
        description="Performs deep reasoning on governed revenue KPIs, margin trends, and pricing optimization.",
        model_tier="REASONING_9B",  # High-complexity reasoning model
        context_token_cap=4096,
        allowed_tools=["analytics.get_kpi_summary", "pricing.calculate_quote"],
        retrieval_roles=["manager", "admin"],
        prompt_version="v1.0",
        system_prompt="You are the Pricing & Sales Performance Analyst. Explain KPI trends and margin models with factual rigor.",
        delegation_policy=[],
        failure_policy="HOLD_FOR_OPERATOR_REVIEW"
    ),
    "knowledge_curator": AgentRoleDefinition(
        role_id="knowledge_curator",
        role_code="B05",
        role_group="BACKGROUND_AGENT",
        display_name="Knowledge Curator Agent",
        description="Identifies knowledge base gaps and drafts article proposals. Self-publication is strictly prohibited.",
        model_tier="PRIMARY_4B",
        context_token_cap=4096,
        allowed_tools=["knowledge.propose_update", "catalog.search"],
        retrieval_roles=["manager", "admin"],
        prompt_version="v1.0",
        system_prompt="You are the Knowledge Curator. Draft knowledge base additions for human editorial review. Never publish directly.",
        delegation_policy=[],
        failure_policy="HOLD_FOR_OPERATOR_REVIEW"
    ),
    "incident_responder": AgentRoleDefinition(
        role_id="incident_responder",
        role_code="B06",
        role_group="BACKGROUND_AGENT",
        display_name="Operational Incident Responder",
        description="Diagnoses system alerts and executes tightly allowlisted, reversible operational runbooks.",
        model_tier="PRIMARY_4B",
        context_token_cap=4096,
        allowed_tools=["incident.diagnose_system", "incident.apply_runbook"],
        retrieval_roles=["admin"],
        prompt_version="v1.0",
        system_prompt="You are the Incident Responder. Triage infrastructure warnings and suggest allowlisted remediation runbooks.",
        delegation_policy=[],
        failure_policy="HOLD_FOR_OPERATOR_REVIEW"
    ),

    # ------------------------------------------------------------------------
    # Representative Copilot
    # ------------------------------------------------------------------------
    "sales_copilot": AgentRoleDefinition(
        role_id="sales_copilot",
        role_code="I01",
        role_group="COPILOT",
        display_name="Sales Representative Copilot",
        description="Assists human sales reps with live deal summaries, objection responses, and draft proposals requiring human confirmation.",
        model_tier="PRIMARY_4B",
        context_token_cap=4096,
        allowed_tools=[
            "catalog.search", "inventory.check_atp", "pricing.calculate_quote",
            "orders.get_status", "copilot.generate_brief", "copilot.propose_action",
            "account.get_summary"
        ],
        retrieval_roles=["public", "sales_rep"],
        prompt_version="v1.0",
        system_prompt="You are the Sales Representative Copilot. Assist human representatives with deal briefs, objection handling, and draft actions.",
        delegation_policy=["quote_pricing", "product_knowledge", "account_management"],
        failure_policy="SAFE_GROUNDED_FALLBACK"
    )
}


class AgentRegistry:
    """Central registry and authority for agent capability metadata and policy."""

    @classmethod
    def get_role(cls, role_id: str) -> AgentRoleDefinition:
        if role_id not in AGENT_CATALOG:
            raise ValueError(f"Agent role '{role_id}' is not registered in capability catalog.")
        return AGENT_CATALOG[role_id]

    @classmethod
    def list_roles(cls) -> List[AgentRoleDefinition]:
        return list(AGENT_CATALOG.values())

    @classmethod
    def list_by_group(cls, group: str) -> List[AgentRoleDefinition]:
        return [r for r in AGENT_CATALOG.values() if r.role_group == group]

    @classmethod
    def get_allowed_tools(cls, role_id: str) -> List[str]:
        role = cls.get_role(role_id)
        return role.allowed_tools

    @classmethod
    def get_model_tier(cls, role_id: str) -> str:
        role = cls.get_role(role_id)
        return role.model_tier
