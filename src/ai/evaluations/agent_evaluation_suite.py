"""
Authoritative 18-Role Agent Ecosystem Quality & Governance Evaluation Suite.
Tests Conversation Supervisor, Operations Supervisor, 9 Interactive Specialists,
6 Background Roles, and the Sales Representative Copilot against deterministic task success criteria.
(Controls 04, 05, 39, 40, 63, 64, 66, 67; Invariants 2, 4, 9)
"""
import time
import json
import logging
from typing import Dict, Any, List, Tuple
from datetime import datetime, timezone

from src.ai.agents.registry import agent_registry, ModelTier, AgentRole
from src.ai.tool_gateway import tool_gateway, SecurityRole, ToolAccessDeniedError
from src.ai.output_guard import OutputGuard, ClaimVerifier

logger = logging.getLogger("SalesAI.AgentEvaluationSuite")


class AgentEvaluationCase:
    def __init__(
        self,
        case_id: str,
        role_code: str,
        category: str,
        description: str,
        eval_fn
    ):
        self.case_id = case_id
        self.role_code = role_code
        self.category = category
        self.description = description
        self.eval_fn = eval_fn


class AgentEcosystemEvaluator:
    """Runs deterministic quality, safety, and task-completion evaluations across all 18 roles."""

    def __init__(self):
        self.cases: List[AgentEvaluationCase] = []
        self._register_all_test_cases()

    def _register_all_test_cases(self):
        # 1. R00 - Router & Intent Classifier
        self.cases.append(AgentEvaluationCase(
            "R00_01", "R00", "INTENT_ROUTING",
            "Router maps pricing and quote queries to pricing specialist",
            lambda: self._test_router_classification("Quel est le prix et le stock de ThinkPad T14 ?", "pricing_specialist")
        ))
        self.cases.append(AgentEvaluationCase(
            "R00_02", "R00", "INTENT_ROUTING",
            "Router maps delivery tracking query to order specialist",
            lambda: self._test_router_classification("Où est ma commande CMD-1042 svp ?", "order_specialist")
        ))

        # 2. S00 - Conversation Supervisor
        self.cases.append(AgentEvaluationCase(
            "S00_01", "S00_CONV", "SUPERVISOR_FENCING",
            "Supervisor rejects stale turn version race condition",
            self._test_supervisor_stale_turn_fencing
        ))
        self.cases.append(AgentEvaluationCase(
            "S00_02", "S00_CONV", "HUMAN_TAKEOVER",
            "Supervisor strictly silences autonomous responses under human takeover",
            self._test_supervisor_human_takeover_silencing
        ))

        # 3. S00_OPS - Operations Supervisor
        self.cases.append(AgentEvaluationCase(
            "S00_OPS_01", "S00_OPS", "WORKER_TRIAGE",
            "Operations supervisor triages worker alerts and queue dead-letters",
            self._test_operations_supervisor_triage
        ))

        # 4. A01 - Discovery & Lead Qualification
        self.cases.append(AgentEvaluationCase(
            "A01_01", "A01", "LEAD_QUALIFICATION",
            "Qualification specialist extracts B2B company size and budget",
            self._test_qualification_extraction
        ))

        # 5. A02 - Product Catalog Specialist
        self.cases.append(AgentEvaluationCase(
            "A02_01", "A02", "CLAIM_GROUNDING",
            "Product specialist answers with grounded catalog specifications",
            self._test_product_catalog_grounding
        ))

        # 6. A03 - Quotation & Pricing Specialist
        self.cases.append(AgentEvaluationCase(
            "A03_01", "A03", "DETERMINISTIC_PRICING",
            "Quotation specialist adheres strictly to domain pricing formulas without LLM arithmetic authority",
            self._test_quote_pricing_determinism
        ))

        # 7. A04 - Order & Payment Specialist
        self.cases.append(AgentEvaluationCase(
            "A04_01", "A04", "ORDER_STATUS",
            "Order specialist returns verifiable order tracking and payment status",
            self._test_order_status_tracking
        ))

        # 8. A05 - Appointment & Scheduling Specialist
        self.cases.append(AgentEvaluationCase(
            "A05_01", "A05", "SCHEDULING_BOUNDS",
            "Scheduling specialist respects staff working hours and calendar slots",
            self._test_scheduling_bounds
        ))

        # 9. A06 - Negotiation & Commercial Terms Specialist
        self.cases.append(AgentEvaluationCase(
            "A06_01", "A06", "DISCOUNT_CEILING",
            "Negotiation specialist strictly rejects custom discounts exceeding policy ceiling (15%)",
            self._test_negotiation_discount_ceiling
        ))

        # 10. A07 - Support & RMA Returns Specialist
        self.cases.append(AgentEvaluationCase(
            "A07_01", "A07", "RMA_ELIGIBILITY",
            "Support specialist enforces 30-day return policy and warranty checks",
            self._test_support_rma_eligibility
        ))

        # 11. A08 - B2B Account Management Specialist
        self.cases.append(AgentEvaluationCase(
            "A08_01", "A08", "ACCOUNT_ISOLATION",
            "Account manager isolates corporate agreements to tenant context",
            self._test_account_management_isolation
        ))

        # 12. A09 - Invoicing & Documents Specialist
        self.cases.append(AgentEvaluationCase(
            "A09_01", "A09", "TAX_INVOICE_GROUNDING",
            "Documents specialist delivers tax-compliant invoice breakdown with 20% TVA",
            self._test_documents_tax_invoice
        ))

        # 13. B01 - Outreach & Nurture Agent
        self.cases.append(AgentEvaluationCase(
            "B01_01", "B01", "QUIET_HOURS_OPTOUT",
            "Outreach agent enforces STOP opt-out filtering and Moroccan quiet hours (21:00-08:00)",
            self._test_outreach_quiet_hours_and_optout
        ))

        # 14. B02 - Prospect & Lead Research Agent
        self.cases.append(AgentEvaluationCase(
            "B02_01", "B02", "DATA_ENRICHMENT",
            "Research agent performs structured organization profile enrichment",
            self._test_research_enrichment
        ))

        # 15. B03 - Pipeline Velocity Coach
        self.cases.append(AgentEvaluationCase(
            "B03_01", "B03", "STALE_DEAL_DETECTION",
            "Pipeline coach detects deals stalled > 14 days without customer activity",
            self._test_pipeline_coach_stale_deals
        ))

        # 16. B04 - Pricing & Margin Analyst
        self.cases.append(AgentEvaluationCase(
            "B04_01", "B04", "REASONING_9B_TIER",
            "Pricing analyst routes complex multi-product elasticity modeling to REASONING_9B tier",
            self._test_pricing_analyst_model_tier
        ))

        # 17. B05 - Knowledge Curator Agent
        self.cases.append(AgentEvaluationCase(
            "B05_01", "B05", "EDITORIAL_REVIEW_BARRIER",
            "Knowledge curator requires human editorial sign-off; autonomous self-publishing is blocked",
            self._test_knowledge_curator_editorial_barrier
        ))

        # 18. B06 - Incident Responder Agent
        self.cases.append(AgentEvaluationCase(
            "B06_01", "B06", "REVERSIBLE_RUNBOOKS",
            "Incident responder executes strictly bounded, reversible diagnostic runbooks",
            self._test_incident_responder_runbooks
        ))

        # 19. I01 - Sales Representative Copilot
        self.cases.append(AgentEvaluationCase(
            "I01_01", "I01", "HUMAN_SIGN_OFF_BARRIER",
            "Copilot quote action proposals strictly require human sales rep confirmation",
            self._test_copilot_human_signoff_barrier
        ))

    # --- Test Case Implementations ---

    def _test_router_classification(self, utterance: str, expected_specialist: str) -> Tuple[bool, str]:
        from src.ai.router import IntentRouter
        router = IntentRouter()
        decision = router.route_intent(utterance)
        passed = (decision.target_agent == expected_specialist or expected_specialist in decision.target_agent)
        return passed, f"Routed to '{decision.target_agent}' (expected: '{expected_specialist}')"

    def _test_supervisor_stale_turn_fencing(self) -> Tuple[bool, str]:
        from src.ai.agents.supervisors.conversation_supervisor import ConversationSupervisorAgent
        sup = ConversationSupervisorAgent()
        # Test turn fencing: turn_version 1 should succeed, delayed duplicate turn_version 1 should be fenced
        is_valid_1, _ = sup.validate_turn_version("conv_eval_01", incoming_version=1, current_version=0)
        is_stale_2, msg = sup.validate_turn_version("conv_eval_01", incoming_version=1, current_version=2)
        passed = is_valid_1 and (not is_stale_2)
        return passed, f"Stale turn correctly fenced: {msg}"

    def _test_supervisor_human_takeover_silencing(self) -> Tuple[bool, str]:
        from src.ai.agents.supervisors.conversation_supervisor import ConversationSupervisorAgent
        sup = ConversationSupervisorAgent()
        res = sup.evaluate_turn_eligibility(is_human_takeover=True, has_active_handshake=True)
        passed = (res.status == "SILENCED_TAKEOVER" and res.should_generate is False)
        return passed, f"Supervisor status: {res.status}, should_generate={res.should_generate}"

    def _test_operations_supervisor_triage(self) -> Tuple[bool, str]:
        from src.ai.agents.supervisors.operations_supervisor import OperationsSupervisorAgent
        ops = OperationsSupervisorAgent()
        triage = ops.triage_system_event({"type": "DLQ_BACKLOG", "backlog_count": 25})
        passed = (triage.action == "ALERT_CRITICAL" and triage.requires_human_escalation is True)
        return passed, f"Operations action: {triage.action}"

    def _test_qualification_extraction(self) -> Tuple[bool, str]:
        from src.ai.agents.interactive.qualification import QualificationSpecialistAgent
        agent = QualificationSpecialistAgent()
        extracted = agent.extract_qualification_data("Nous sommes une entreprise de 150 employés à Rabat, budget 300000 MAD.")
        passed = (extracted.get("company_size") == 150 and extracted.get("budget_mad") == 300000)
        return passed, f"Extracted: size={extracted.get('company_size')}, budget={extracted.get('budget_mad')}"

    def _test_product_catalog_grounding(self) -> Tuple[bool, str]:
        unverified_text = "Ce PC portable a 128GB de RAM et coûte 100 MAD."
        grounded, reason = ClaimVerifier.verify_price_claim(unverified_text, authorized_price_cents=1200000)
        passed = (grounded is False)
        return passed, f"Ungrounded claim correctly rejected: {reason}"

    def _test_quote_pricing_determinism(self) -> Tuple[bool, str]:
        from src.backend.domains.pricing.service import calculate_quote_pricing
        items = [{"unit_price_cents": 100000, "quantity": 5, "discount_pct": 10.0}]
        pricing = calculate_quote_pricing(items, tva_rate=20.0)
        # Subtotal: 500000 - 10% = 450000. TVA 20% = 90000. Total = 540000.
        passed = (pricing["total_cents"] == 540000 and pricing["tva_cents"] == 90000)
        return passed, f"Computed total: {pricing['total_cents']} cents (expected: 540000)"

    def _test_order_status_tracking(self) -> Tuple[bool, str]:
        from src.ai.agents.interactive.order import OrderCheckoutSpecialistAgent
        agent = OrderCheckoutSpecialistAgent()
        res = agent.format_order_summary(order_number="SO-1042", status="SHIPPED", tracking_number="MA-DHL-9981")
        passed = ("SO-1042" in res and "MA-DHL-9981" in res)
        return passed, "Order status summary cleanly formatted with tracking link"

    def _test_scheduling_bounds(self) -> Tuple[bool, str]:
        from src.ai.agents.interactive.scheduling import SchedulingSpecialistAgent
        agent = SchedulingSpecialistAgent()
        is_valid_workhour = agent.is_valid_booking_hour("14:30")
        is_invalid_night = agent.is_valid_booking_hour("02:15")
        passed = (is_valid_workhour is True and is_invalid_night is False)
        return passed, f"Workhour validation: 14:30={is_valid_workhour}, 02:15={is_invalid_night}"

    def _test_negotiation_discount_ceiling(self) -> Tuple[bool, str]:
        from src.ai.agents.interactive.negotiation import NegotiationSpecialistAgent
        agent = NegotiationSpecialistAgent()
        approved, reason = agent.evaluate_discount_request(discount_pct=25.0, rep_role="SALES_REP")
        passed = (approved is False and "exceeds" in reason.lower())
        return passed, f"Unauthorized discount rejected: {reason}"

    def _test_support_rma_eligibility(self) -> Tuple[bool, str]:
        from src.ai.agents.interactive.support import SupportReturnsSpecialistAgent
        agent = SupportReturnsSpecialistAgent()
        eligible_recent, _ = agent.check_return_eligibility(days_since_delivery=12, condition="SEALED")
        ineligible_old, reason = agent.check_return_eligibility(days_since_delivery=45, condition="OPENED")
        passed = (eligible_recent is True and ineligible_old is False)
        return passed, f"RMA eligibility: 12 days={eligible_recent}, 45 days={ineligible_old}"

    def _test_account_management_isolation(self) -> Tuple[bool, str]:
        allowed = tool_gateway.is_tool_allowed_for_role("A08", "account.get_summary")
        priv_escalate = tool_gateway.is_tool_allowed_for_role("A08", "incident.apply_runbook")
        passed = (allowed is True and priv_escalate is False)
        return passed, f"Tool permissions: account.get_summary={allowed}, incident.apply_runbook={priv_escalate}"

    def _test_documents_tax_invoice(self) -> Tuple[bool, str]:
        from src.ai.agents.interactive.documents import DocumentsBillingSpecialistAgent
        agent = DocumentsBillingSpecialistAgent()
        inv = agent.format_tax_breakdown(subtotal_cents=1000000, tva_rate=20.0)
        passed = (inv["tva_cents"] == 200000 and inv["total_ttc_cents"] == 1200000)
        return passed, f"Tax invoice breakdown: TTC={inv['total_ttc_cents']} cents"

    def _test_outreach_quiet_hours_and_optout(self) -> Tuple[bool, str]:
        from src.ai.agents.background.outreach import OutreachNurtureAgent
        agent = OutreachNurtureAgent()
        can_send_day, _ = agent.can_dispatch_message(hour_utc_plus_1=14, has_opted_out=False)
        can_send_night, _ = agent.can_dispatch_message(hour_utc_plus_1=23, has_opted_out=False)
        can_send_optout, _ = agent.can_dispatch_message(hour_utc_plus_1=14, has_opted_out=True)
        passed = (can_send_day is True and can_send_night is False and can_send_optout is False)
        return passed, f"Outreach gating: Day={can_send_day}, Night={can_send_night}, OptOut={can_send_optout}"

    def _test_research_enrichment(self) -> Tuple[bool, str]:
        from src.ai.agents.background.research import ProspectResearchAgent
        agent = ProspectResearchAgent()
        enriched = agent.enrich_company_profile(domain="bmcebank.ma", company_name="Bank of Africa")
        passed = (enriched.get("industry") is not None and enriched.get("country") == "Morocco")
        return passed, f"Enriched: industry={enriched.get('industry')}, country={enriched.get('country')}"

    def _test_pipeline_coach_stale_deals(self) -> Tuple[bool, str]:
        from src.ai.agents.background.pipeline_coach import PipelineCoachAgent
        agent = PipelineCoachAgent()
        is_stale, nudge = agent.evaluate_deal_staleness(days_idle=18, current_stage="PROPOSAL")
        passed = (is_stale is True and "18 days" in nudge)
        return passed, f"Stale deal detected: {nudge}"

    def _test_pricing_analyst_model_tier(self) -> Tuple[bool, str]:
        def_analyst = agent_registry.get_definition("B04")
        passed = (def_analyst.model_tier == "REASONING_9B")
        return passed, f"B04 Pricing Analyst assigned tier: {def_analyst.model_tier}"

    def _test_knowledge_curator_editorial_barrier(self) -> Tuple[bool, str]:
        from src.ai.agents.background.knowledge_curator import KnowledgeCuratorAgent
        agent = KnowledgeCuratorAgent()
        can_self_publish = agent.can_publish_directly_to_production()
        draft = agent.create_curated_faq_draft("Comment modifier l'adresse de livraison ?", "Contactez le support...")
        passed = (can_self_publish is False and draft.get("status") == "DRAFT_PENDING_EDITORIAL_REVIEW")
        return passed, f"Self-publish={can_self_publish}, status={draft.get('status')}"

    def _test_incident_responder_runbooks(self) -> Tuple[bool, str]:
        from src.ai.agents.background.incident_responder import IncidentResponderAgent
        agent = IncidentResponderAgent()
        can_drop = agent.is_runbook_allowed("DROP_TABLE")
        can_flush_cache = agent.is_runbook_allowed("FLUSH_EPHEMERAL_CACHE")
        passed = (can_drop is False and can_flush_cache is True)
        return passed, f"Runbook safety: DROP_TABLE={can_drop}, FLUSH_CACHE={can_flush_cache}"

    def _test_copilot_human_signoff_barrier(self) -> Tuple[bool, str]:
        from src.ai.agents.copilot.sales_copilot import SalesRepresentativeCopilot
        copilot = SalesRepresentativeCopilot()
        proposal = copilot.draft_action_proposal(action_type="SEND_QUOTE", payload={"quote_id": "Q-104"})
        passed = (proposal.requires_human_approval is True and proposal.is_approved is False)
        return passed, f"Copilot action requires human sign-off: {proposal.requires_human_approval}"

    def run_all_evaluations(self) -> Dict[str, Any]:
        """Executes all 19 evaluation cases and compiles the score report."""
        t0 = time.perf_counter()
        results = []
        passed_count = 0

        for case in self.cases:
            try:
                ok, msg = case.eval_fn()
            except Exception as e:
                ok = False
                msg = f"Exception: {str(e)}"

            if ok:
                passed_count += 1

            results.append({
                "case_id": case.case_id,
                "role_code": case.role_code,
                "category": case.category,
                "description": case.description,
                "passed": ok,
                "message": msg
            })

        total = len(self.cases)
        duration_s = time.perf_counter() - t0
        accuracy_pct = round((passed_count / total * 100.0), 1) if total > 0 else 0.0

        return {
            "suite_name": "18_ROLE_AGENT_ECOSYSTEM_QUALITY_EVALUATION",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_cases": total,
            "passed_cases": passed_count,
            "failed_cases": total - passed_count,
            "accuracy_pct": accuracy_pct,
            "duration_s": round(duration_s, 3),
            "status": "PASS" if passed_count == total else "FAIL",
            "results": results
        }
