"""
Conversation Supervisor Agent.
Step 09: Complete 18-Role Agent Ecosystem & Sales Representative Copilot
(Controls 39, 40, 65, 67; Invariants 1, 2, 4)

Responsibilities:
1. Own the interactive conversation turn.
2. Select appropriate specialist via ConversationRouter.
3. Manage specialist handoffs and turn state machine.
4. Enforce Human Takeover Silencing (silence autonomous AI turns when human claims ownership).
5. Enforce Stale-Turn Version Fencing against concurrency races.
"""
import logging
from typing import Dict, Any, Optional, Tuple

from src.ai.agents.base import BaseAgent, AgentInput, AgentOutput
from src.ai.agents.registry import AgentRegistry
from src.ai.router import ConversationRouter, RoutingDecision
from src.ai.tool_gateway import ServerSecurityContext

logger = logging.getLogger("SalesAI.ConversationSupervisor")


class ConversationSupervisorAgent(BaseAgent):
    """Authoritative supervisor for live customer turns."""

    def __init__(self):
        super().__init__("conversation_supervisor")
        # In-memory turn tracking {conversation_id: version}
        self._turn_versions: Dict[str, int] = {}
        # Human ownership tracker {conversation_id: human_user_id}
        self._human_owners: Dict[str, str] = {}
        # Active specialist per conversation {conversation_id: specialist_role_id}
        self._active_specialists: Dict[str, str] = {}

    def set_human_takeover(self, conversation_id: str, human_user_id: str):
        """Designates human rep as sole owner, immediately suppressing autonomous AI."""
        self._human_owners[conversation_id] = human_user_id
        logger.info(f"Human takeover enabled for conversation {conversation_id} by user {human_user_id}")

    def release_human_takeover(self, conversation_id: str):
        """Releases human ownership, allowing AI autonomy to resume."""
        self._human_owners.pop(conversation_id, None)
        logger.info(f"Human takeover released for conversation {conversation_id}")

    def is_human_owned(self, conversation_id: str) -> bool:
        return conversation_id in self._human_owners

    def validate_and_advance_turn(
        self,
        conversation_id: str,
        expected_turn_version: int
    ) -> Tuple[bool, int]:
        """Validates expected turn version; increments on match; rejects on mismatch."""
        current_version = self._turn_versions.get(conversation_id, 0)
        if expected_turn_version != current_version:
            logger.warning(
                f"Stale turn rejected: conv={conversation_id}, expected={expected_turn_version}, current={current_version}"
            )
            return False, current_version

        new_version = current_version + 1
        self._turn_versions[conversation_id] = new_version
        return True, new_version

    def validate_turn_version(self, conversation_id: str, incoming_version: int, current_version: int) -> Tuple[bool, str]:
        """Validates turn concurrency against race conditions."""
        if incoming_version <= current_version:
            return False, f"Stale turn rejected: incoming {incoming_version} <= current {current_version}"
        return True, "Turn version valid"

    def evaluate_turn_eligibility(self, is_human_takeover: bool = False, has_active_handshake: bool = True):
        """Evaluates whether autonomous turn should execute or be suppressed."""
        class EligibilityResult:
            def __init__(self, status, should_generate):
                self.status = status
                self.should_generate = should_generate
        if is_human_takeover:
            return EligibilityResult("SILENCED_TAKEOVER", False)
        return EligibilityResult("ACTIVE", True)


    def select_specialist(self, routing: RoutingDecision, conversation_id: Optional[str] = None) -> str:
        """Determines which interactive specialist role should own this turn."""
        intent = routing.intent
        mapping = {
            "GREETING": "product_knowledge",
            "CATALOG_QUERY": "product_knowledge",
            "INVENTORY_ATP": "product_knowledge",
            "PRICING_QUOTE": "quote_pricing",
            "ORDER_INQUIRY": "order_payment",
            "SCHEDULE_APPOINTMENT": "scheduling",
            "SUPPORT_ISSUE": "support_returns",
            "QUALIFICATION": "qualification_crm"
        }
        selected = mapping.get(intent, "product_knowledge")
        if conversation_id:
            self._active_specialists[conversation_id] = selected
        return selected

    def request_handoff(self, conversation_id: str, from_role: str, to_role: str) -> bool:
        """Validates and executes a specialist handoff within permitted delegation policy."""
        role_def = AgentRegistry.get_role(from_role)
        if to_role not in role_def.delegation_policy:
            logger.warning(f"Unauthorized handoff attempt from '{from_role}' to '{to_role}'")
            return False

        self._active_specialists[conversation_id] = to_role
        logger.info(f"Specialist handoff executed: conv={conversation_id}, {from_role} -> {to_role}")
        return True

    async def handle_turn(
        self,
        input_data: AgentInput,
        security_context: ServerSecurityContext,
        expected_turn_version: int = 0,
        db_session=None
    ) -> AgentOutput:
        """Orchestrates the complete turn: routing, fencing, specialist execution."""
        conv_id = input_data.conversation_id or "CONV-DEFAULT"

        # Check 1: Human Takeover Silencing (Invariant: Rep ownership suppresses AI)
        if self.is_human_owned(conv_id):
            logger.info(f"Turn silenced due to active human takeover on {conv_id}")
            return AgentOutput(
                agent_role="conversation_supervisor",
                response_text="[AI response silenced: Human representative is managing this conversation / Reprise en charge par un conseiller humain]",
                status="SILENCED_TAKEOVER",
                trace_id=input_data.trace_id or "TRC-TAKEOVER",
                model_name="none"
            )

        # Check 2: Stale-Turn Version Fencing
        valid, current_ver = self.validate_and_advance_turn(conv_id, expected_turn_version)
        if not valid:
            return AgentOutput(
                agent_role="conversation_supervisor",
                response_text="[Stale turn rejected: A newer customer or agent action has updated this conversation]",
                status="ERROR",
                error_details=f"Turn version mismatch: expected {expected_turn_version}, current {current_ver}",
                trace_id=input_data.trace_id or "TRC-STALE",
                model_name="none"
            )

        # Check 3: Route Intent and Adversarial Risk
        routing = ConversationRouter.route(
            text=input_data.user_prompt,
            turn_id=input_data.turn_id,
            is_human_owned=False
        )

        if routing.action == "REJECT_ADVERSARIAL":
            return AgentOutput(
                agent_role="conversation_supervisor",
                response_text="Je ne peux pas traiter cette demande car elle ne respecte pas nos consignes de sécurité.",
                status="REJECTED_GUARD",
                trace_id=input_data.trace_id or "TRC-ADV",
                model_name="none"
            )

        # Check 4: Dispatch to Selected Specialist
        specialist_role = self.select_specialist(routing, conv_id)
        specialist_agent = BaseAgent(specialist_role)

        output = await specialist_agent.execute(
            input_data=input_data,
            security_context=security_context,
            db_session=db_session
        )
        return output
