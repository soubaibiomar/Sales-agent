"""
Complete 18-Role Agent Ecosystem & Sales Representative Copilot Package.
Step 09: Complete 18-Role Agent Ecosystem & Sales Representative Copilot
"""
from src.ai.agents.registry import AgentRegistry, AgentRoleDefinition, AGENT_CATALOG
from src.ai.agents.base import BaseAgent, AgentInput, AgentOutput
from src.ai.agents.supervisors.conversation_supervisor import ConversationSupervisorAgent
from src.ai.agents.supervisors.operations_supervisor import OperationsSupervisorAgent
from src.ai.agents.copilot.sales_copilot import SalesRepresentativeCopilot

__all__ = [
    "AgentRegistry",
    "AgentRoleDefinition",
    "AGENT_CATALOG",
    "BaseAgent",
    "AgentInput",
    "AgentOutput",
    "ConversationSupervisorAgent",
    "OperationsSupervisorAgent",
    "SalesRepresentativeCopilot",
]
