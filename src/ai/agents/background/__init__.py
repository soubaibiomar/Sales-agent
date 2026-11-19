"""Governed Background Agents Package."""
from src.ai.agents.background.outreach import OutreachAgent
from src.ai.agents.background.research import ResearchAgent
from src.ai.agents.background.pipeline_coach import PipelineCoachAgent
from src.ai.agents.background.analyst import AnalystAgent
from src.ai.agents.background.knowledge_curator import KnowledgeCuratorAgent
from src.ai.agents.background.incident_responder import IncidentResponderAgent

__all__ = [
    "OutreachAgent",
    "ResearchAgent",
    "PipelineCoachAgent",
    "AnalystAgent",
    "KnowledgeCuratorAgent",
    "IncidentResponderAgent",
]
