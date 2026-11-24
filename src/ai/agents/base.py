"""
Base Agent Execution Engine.
Step 09: Complete 18-Role Agent Ecosystem & Sales Representative Copilot
(Controls 40, 63, 65, 66, 67; Invariants 2, 4, 9)

Enforces:
1. One authoritative execution lifecycle for every agent role.
2. Tenant and role boundary enforcement via server-issued SecurityContext.
3. Model Gateway invocation with token budgets and GPU VRAM safety.
4. Tool execution strictly through protected ToolGateway.
5. Deterministic claim verification and statutory AI disclosure via OutputGuard.
6. Execution audit logging to agent_execution_logs.
"""
import time
import uuid
import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from src.ai.agents.registry import AgentRegistry, AgentRoleDefinition
from src.ai.model_gateway import model_gateway, ModelGatewayRequest
from src.ai.tool_gateway import tool_gateway, ServerSecurityContext, ToolGatewayError
from src.ai.output_guard import OutputGuard, EvidenceEnvelope
from src.ai.rag.models import RAGQueryRequest
from src.ai.rag.service import KnowledgeService
from src.backend.models.entities import AgentExecutionLog

logger = logging.getLogger("SalesAI.BaseAgent")


class AgentInput(BaseModel):
    conversation_id: Optional[str] = None
    turn_id: Optional[str] = None
    user_prompt: str
    channel: str = "WEBCHAT"  # WEBCHAT, WHATSAPP, EMAIL, VOICE
    trace_id: Optional[str] = None
    evidence: Optional[Dict[str, Any]] = None
    parameters: Dict[str, Any] = Field(default_factory=dict)


class AgentOutput(BaseModel):
    agent_role: str
    response_text: str
    tools_called: List[Dict[str, Any]] = Field(default_factory=list)
    execution_class: str = "BOUNDED_REASONING_TURN"
    status: str = "SUCCESS"  # SUCCESS, REJECTED_GUARD, TIMEOUT, ERROR, SILENCED_TAKEOVER
    latency_ms: int = 0
    tokens_used: int = 0
    model_name: str = "qwen3.5:4b"
    trace_id: str
    error_details: Optional[str] = None


class BaseAgent:
    """Base implementation providing bounded execution and invariant governance."""

    def __init__(self, role_id: str):
        self.role_def: AgentRoleDefinition = AgentRegistry.get_role(role_id)
        self.role_id: str = role_id

    async def execute(
        self,
        input_data: AgentInput,
        security_context: ServerSecurityContext,
        evidence: Optional[Dict[str, Any]] = None,
        db_session=None
    ) -> AgentOutput:
        """Executes a bounded, observable, and verified agent reasoning turn."""
        start_time = time.time()
        trace_id = input_data.trace_id or f"TRC-{uuid.uuid4().hex[:12]}"
        tools_called: List[Dict[str, Any]] = []
        tokens_used = 0
        status = "SUCCESS"
        error_details = None

        # Step 1: Context & Role Boundary Verification
        # Invariant 4: Security context is server-issued and trusted
        if not security_context.tenant_id:
            raise ValueError("ServerSecurityContext missing tenant_id.")

        # Step 2: Context Retrieval via RAG (if permitted for this role)
        rag_context_snippets = []
        if db_session and self.role_def.retrieval_roles:
            try:
                rag_service = KnowledgeService(db_session)
                rag_req = RAGQueryRequest(
                    query=input_data.user_prompt,
                    limit=2,
                    user_roles=self.role_def.retrieval_roles
                )
                chunks = await rag_service.retrieve_context(
                    tenant_id=security_context.tenant_id,
                    req=rag_req
                )
                rag_context_snippets = [c.content for c in chunks]
            except Exception as e:
                logger.warning(f"RAG context retrieval failed non-critically for {self.role_id}: {e}")

        # Step 3: Tool Execution Preparation
        # Check if user prompt requests a specific tool action allowed for this agent
        tool_results_for_prompt = []
        for tool_name in self.role_def.allowed_tools:
            # Simple keyword matching to decide if a tool should be executed proactively
            should_invoke = False
            tool_params = {}
            if tool_name == "catalog.search" and any(k in input_data.user_prompt.lower() for k in ["panneau", "onduleur", "produit", "catalogue", "solar"]):
                should_invoke = True
                tool_params = {"query": "solaire", "limit": 2}
            elif tool_name == "inventory.check_atp" and any(k in input_data.user_prompt.lower() for k in ["stock", "disponible", "dispo"]):
                should_invoke = True
                tool_params = {"sku": "SKU-SOLAR-01"}
            elif tool_name == "pricing.calculate_quote" and any(k in input_data.user_prompt.lower() for k in ["devis", "prix", "chhal", "combien"]):
                should_invoke = True
                tool_params = {"items": [{"sku": "SKU-SOLAR-01", "quantity": 1}], "customer_tier": "standard"}
            elif tool_name == "orders.get_status" and any(k in input_data.user_prompt.lower() for k in ["commande", "suivi", "tracking"]):
                should_invoke = True
                tool_params = {"order_id": "ORD-2026-99182"}
            elif tool_name == "scheduling.get_slots" and any(k in input_data.user_prompt.lower() for k in ["rdv", "rendez-vous", "reunion"]):
                should_invoke = True
                tool_params = {"date": "2026-11-20"}
            elif tool_name == "account.get_summary" and any(k in input_data.user_prompt.lower() for k in ["compte", "account", "client"]):
                should_invoke = True
                tool_params = {"account_id": "ACC-9921"}
            elif tool_name == "documents.get_invoice" and any(k in input_data.user_prompt.lower() for k in ["facture", "invoice"]):
                should_invoke = True
                tool_params = {"invoice_id": "INV-00442"}
            elif tool_name == "pipeline.analyze_stale_deals" and self.role_id == "pipeline_coach":
                should_invoke = True
                tool_params = {"max_days_in_stage": 14}
            elif tool_name == "analytics.get_kpi_summary" and self.role_id == "analyst":
                should_invoke = True
                tool_params = {"period": "CURRENT_MONTH"}
            elif tool_name == "incident.diagnose_system" and self.role_id == "incident_responder":
                should_invoke = True
                tool_params = {"scope": "ALL"}
            elif tool_name == "copilot.generate_brief" and self.role_id == "sales_copilot":
                should_invoke = True
                tool_params = {"conversation_id": input_data.conversation_id or "CONV-001"}

            if should_invoke:
                try:
                    tool_res = await tool_gateway.execute_tool(
                        tool_name=tool_name,
                        params=tool_params,
                        context=ServerSecurityContext(
                            tenant_id=security_context.tenant_id,
                            user_id=security_context.user_id,
                            role=self.role_id,
                            permissions=security_context.permissions
                        ),
                        db_session=db_session
                    )
                    tools_called.append({"tool": tool_name, "params": tool_params, "result": tool_res})
                    tool_results_for_prompt.append(f"Tool {tool_name} returned: {tool_res}")
                except ToolGatewayError as tge:
                    logger.warning(f"Tool invocation failed: {tge}")

        # Step 4: Model Gateway Reasoning Turn
        model_name = "qwen3.5:9b-q4_K_M" if self.role_def.model_tier == "REASONING_9B" else "qwen3.5:4b"
        prompt_parts = [
            f"Role: {self.role_def.display_name}",
            f"Instructions: {self.role_def.system_prompt}",
            f"User Query: {input_data.user_prompt}"
        ]
        if rag_context_snippets:
            prompt_parts.append("Approved Knowledge Context: " + "\n".join(rag_context_snippets))
        if tool_results_for_prompt:
            prompt_parts.append("Verified Tool Evidence: " + "\n".join(tool_results_for_prompt))

        full_prompt = "\n\n".join(prompt_parts)

        # Build Model Gateway Request
        gw_req = ModelGatewayRequest(
            tenant_id=security_context.tenant_id,
            user_id=security_context.user_id,
            prompt=full_prompt,
            model=model_name,
            max_tokens=min(512, self.role_def.context_token_cap),
            channel=input_data.channel,
            turn_id=input_data.turn_id
        )

        gw_res = await model_gateway.generate(gw_req, db_session=db_session)
        raw_text = gw_res.content or ""
        tokens_used = gw_res.total_tokens
        if gw_res.status in ("UNAVAILABLE_HANDOFF", "ERROR"):
            # F-16: the model could not answer; the turn must go to a human, and this is
            # recorded explicitly instead of looking like a normal successful answer.
            status = "MODEL_UNAVAILABLE_HANDOFF"
            error_details = gw_res.error_message

        # Step 5: Commercial Claim Grounding & Output Guard (Invariant 2 & Control 65, 66)
        # Extract evidence envelope from tool results, explicit evidence param, or input
        evidence_dict = {**(evidence or {}), **(input_data.evidence or {})}
        # F-07/F-08: only authoritative (non-simulated) tool results become evidence,
        # converted to the units the ClaimVerifier compares against (major currency units).
        verified_prices = dict(evidence_dict.get("verified_prices", {}))
        verified_stock = dict(evidence_dict.get("verified_stock_atp", {}))
        verified_order_status = evidence_dict.get("verified_order_status")
        verified_tracking = evidence_dict.get("verified_tracking_number")
        currency = evidence_dict.get("currency", "MAD")
        for tc in tools_called:
            res = tc.get("result") or {}
            if not isinstance(res, dict) or res.get("simulated"):
                continue
            if tc["tool"] == "pricing.calculate_quote":
                for key in ("total_cents", "subtotal_cents", "tax_cents"):
                    if res.get(key) is not None:
                        verified_prices[f"quote_{key[:-6]}"] = res[key] / 100.0
                currency = res.get("currency", currency)
            elif tc["tool"] == "catalog.search":
                for prod in res.get("products", []):
                    verified_prices[prod["sku"]] = prod["price_cents"] / 100.0
            elif tc["tool"] == "inventory.check_atp":
                verified_stock[res["sku"]] = int(res["available_units"])
            elif tc["tool"] == "orders.get_status":
                verified_order_status = res.get("payment_status")
                verified_tracking = res.get("tracking_number")

        # Always build an envelope: an empty one means "nothing verified", so any
        # commercial claim in the model output is rejected (fail closed).
        envelope = EvidenceEnvelope(
            tenant_id=security_context.tenant_id,
            verified_prices=verified_prices,
            verified_currency=currency,
            verified_stock_atp=verified_stock,
            approved_discounts_percent=evidence_dict.get("approved_discounts_percent", []),
            verified_order_status=verified_order_status,
            verified_tracking_number=verified_tracking
        )
        guarded = OutputGuard.inspect_and_guard(
            text=raw_text,
            evidence=envelope,
            include_disclosure=True
        )

        final_text = guarded.sanitized_text
        if not guarded.is_safe or guarded.status == "UNVERIFIED_CLAIMS_FALLBACK":
            status = "REJECTED_GUARD"

        latency_ms = int((time.time() - start_time) * 1000)

        # Step 6: Audit Execution Logging
        if db_session:
            try:
                log_entry = AgentExecutionLog(
                    id=f"AGL-{uuid.uuid4().hex[:12]}",
                    tenant_id=security_context.tenant_id,
                    conversation_id=input_data.conversation_id,
                    agent_role=self.role_id,
                    execution_class="BOUNDED_REASONING_TURN",
                    turn_id=input_data.turn_id,
                    trace_id=trace_id,
                    input_summary=input_data.user_prompt[:250],
                    output_summary=final_text[:250],
                    tools_called=[t["tool"] for t in tools_called],
                    model_name=model_name,
                    prompt_tokens=gw_res.prompt_tokens,
                    completion_tokens=gw_res.completion_tokens,
                    total_tokens=tokens_used,
                    latency_ms=latency_ms,
                    status=status,
                    error_details=error_details
                )
                db_session.add(log_entry)
                await db_session.flush()
            except Exception as ex:
                logger.warning(f"Failed to persist agent execution log: {ex}")

        return AgentOutput(
            agent_role=self.role_id,
            response_text=final_text,
            tools_called=tools_called,
            execution_class="BOUNDED_REASONING_TURN",
            status=status,
            latency_ms=latency_ms,
            tokens_used=tokens_used,
            model_name=model_name,
            trace_id=trace_id,
            error_details=error_details
        )
