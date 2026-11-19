"""
Operational Incident Responder Agent (B06).
Step 09: Complete 18-Role Agent Ecosystem & Sales Representative Copilot
Invariant: Allowlisted reversible runbooks only.
"""
from src.ai.agents.base import BaseAgent


class IncidentResponderAgent(BaseAgent):
    ALLOWED_RUNBOOKS = {"FLUSH_EPHEMERAL_CACHE", "RESTART_WORKER", "PING_DEPENDENCIES"}

    def __init__(self):
        super().__init__("incident_responder")

    def is_runbook_allowed(self, runbook_name: str) -> bool:
        return runbook_name in self.ALLOWED_RUNBOOKS
