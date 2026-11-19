"""
Operations & Background Supervisor Agent.
Step 09: Complete 18-Role Agent Ecosystem & Sales Representative Copilot
(Controls 40, 63, 67; Invariants 2, 4)

Responsibilities:
1. Coordinate background asynchronous agents (B01-B06).
2. Schedule batch pipelines (outreach, lead research, deal coaching).
3. Monitor worker queues, DLQs, and execution budgets.
4. Enforce domain authority: background agents propose, durable workflows execute.
"""
import logging
from typing import Dict, Any, List

from src.ai.agents.base import BaseAgent, AgentInput, AgentOutput
from src.ai.tool_gateway import ServerSecurityContext

logger = logging.getLogger("SalesAI.OperationsSupervisor")


class OperationsSupervisorAgent(BaseAgent):
    """Supervisor overseeing all governed background AI tasks."""

    def __init__(self):
        super().__init__("operations_supervisor")

    async def run_operational_triage(
        self,
        tenant_id: str,
        security_context: ServerSecurityContext,
        db_session=None
    ) -> Dict[str, Any]:
        """Runs periodic system health and background pipeline triage."""
        diag_output = await self.execute(
            input_data=AgentInput(user_prompt="Exécuter le diagnostic système et l'analyse des alertes."),
            security_context=security_context,
            db_session=db_session
        )

        return {
            "supervisor": "operations_supervisor",
            "status": "OPERATIONAL",
            "triage_summary": diag_output.response_text,
            "tools_executed": [t["tool"] for t in diag_output.tools_called],
            "latency_ms": diag_output.latency_ms
        }

    def triage_system_event(self, event: Dict[str, Any]):
        class TriageResult:
            def __init__(self, action, requires_human_escalation):
                self.action = action
                self.requires_human_escalation = requires_human_escalation
        backlog = event.get("backlog_count", 0)
        if backlog >= 20:
            return TriageResult("ALERT_CRITICAL", True)
        return TriageResult("NORMAL", False)

