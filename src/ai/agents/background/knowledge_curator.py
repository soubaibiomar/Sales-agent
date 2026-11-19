"""
Knowledge Curator Agent (B05).
Step 09: Complete 18-Role Agent Ecosystem & Sales Representative Copilot
Invariant: Editorial proposal only; self-publication strictly prohibited.
"""
from typing import Optional, Dict, Any
from src.ai.agents.base import BaseAgent, AgentInput, AgentOutput
from src.ai.tool_gateway import ServerSecurityContext


class KnowledgeCuratorAgent(BaseAgent):
    def __init__(self):
        super().__init__("knowledge_curator")

    async def execute(
        self,
        input_data: AgentInput,
        security_context: ServerSecurityContext,
        evidence: Optional[Dict[str, Any]] = None,
        db_session=None
    ) -> AgentOutput:
        result = await super().execute(input_data, security_context, evidence, db_session)
        # Architectural Invariant: Self-publication strictly prohibited. Output is a draft/proposition for human editorial review.
        result.response_text = (
            "[Proposition d'article en revue éditoriale — Validation humaine obligatoire avant publication (Brouillon)]\n"
            + result.response_text
        )
        return result
