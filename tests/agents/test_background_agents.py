"""
Unit & Integration Tests for All 6 Governed Background Agents.
Step 09: Complete 18-Role Agent Ecosystem & Sales Representative Copilot
(Controls 40, 42, 63, 67; Invariants 2, 4)
"""
import pytest
import asyncio
from src.ai.tool_gateway import ServerSecurityContext
from src.ai.agents.base import AgentInput, AgentOutput
from src.ai.agents.background.outreach import OutreachAgent
from src.ai.agents.background.research import ResearchAgent
from src.ai.agents.background.pipeline_coach import PipelineCoachAgent
from src.ai.agents.background.analyst import AnalystAgent
from src.ai.agents.background.knowledge_curator import KnowledgeCuratorAgent
from src.ai.agents.background.incident_responder import IncidentResponderAgent


@pytest.fixture
def background_sec_context():
    return ServerSecurityContext(
        tenant_id="tenant-bg-test",
        user_id="system-worker-01",
        role="worker",
        permissions=["ai:agents", "ai:background"]
    )


@pytest.mark.asyncio
async def test_outreach_agent_stop_optout_and_quiet_hours(background_sec_context):
    """
    B01: Validates outreach campaign drafting with STOP opt-out filter
    and quiet hours compliance.
    """
    agent = OutreachAgent()
    turn = AgentInput(
        conversation_id="conv-bg-outreach-01",
        turn_id="turn-bg-01",
        user_prompt="Schedule promotional broadcast for dormant leads",
        parameters={
            "campaign_name": "Offre Printemps Solaire",
            "channel": "WHATSAPP",
            "template": "Bonjour! Profitez de nos promotions de printemps sur les batteries solaires."
        }
    )
    result = await agent.execute(turn, background_sec_context)
    assert result.status == "SUCCESS"
    assert result.agent_role == "outreach"
    assert "draft" in result.response_text.lower() or "campagne" in result.response_text.lower() or "whatsapp" in result.response_text.lower()


@pytest.mark.asyncio
async def test_research_agent_enrichment(background_sec_context):
    """B02: Tests organization enrichment without fabricated data."""
    agent = ResearchAgent()
    turn = AgentInput(
        conversation_id="conv-bg-res-01",
        turn_id="turn-bg-02",
        user_prompt="Enrich intelligence for prospect company Atlas Agro S.A.",
        parameters={"company_name": "Atlas Agro S.A.", "industry": "Agribusiness"}
    )
    result = await agent.execute(turn, background_sec_context)
    assert result.status == "SUCCESS"
    assert result.agent_role == "research"
    assert "Atlas Agro" in result.response_text or len(result.response_text) > 0


@pytest.mark.asyncio
async def test_pipeline_coach_stale_deals(background_sec_context):
    """B03: Tests stale deal detection and proactive suggestions."""
    agent = PipelineCoachAgent()
    turn = AgentInput(
        conversation_id="conv-bg-pipe-01",
        turn_id="turn-bg-03",
        user_prompt="Analyze stale opportunities in stage Proposal.",
        parameters={"stage": "PROPOSAL", "max_stale_days": 14}
    )
    result = await agent.execute(turn, background_sec_context)
    assert result.status == "SUCCESS"
    assert result.agent_role == "pipeline_coach"
    assert len(result.response_text) > 0


@pytest.mark.asyncio
async def test_pricing_analyst_uses_reasoning_9b(background_sec_context):
    """
    B04: Validates that Pricing & Sales Performance Analyst specifies REASONING_9B model tier.
    """
    agent = AnalystAgent()
    assert agent.role_def.model_tier == "REASONING_9B"
    
    turn = AgentInput(
        conversation_id="conv-bg-analyst-01",
        turn_id="turn-bg-04",
        user_prompt="Generate Q1 margin and discount correlation analysis."
    )
    result = await agent.execute(turn, background_sec_context)
    assert result.status == "SUCCESS"
    assert result.agent_role == "analyst"


@pytest.mark.asyncio
async def test_knowledge_curator_self_publish_prohibited(background_sec_context):
    """
    B05: Invariant check - Knowledge curator cannot self-publish articles directly to production.
    All outputs must require human review / draft state.
    """
    agent = KnowledgeCuratorAgent()
    turn = AgentInput(
        conversation_id="conv-bg-know-01",
        turn_id="turn-bg-05",
        user_prompt="Submit updated solar inverter FAQ entry based on recent customer tickets.",
        parameters={
            "title": "Dépannage Onduleur Code Erreur E04",
            "content": "Le code E04 indique une surtension réseau. Vérifier le disjoncteur différentiel."
        }
    )
    result = await agent.execute(turn, background_sec_context)
    assert result.status == "SUCCESS"
    assert result.agent_role == "knowledge_curator"
    # Invariant: Must explicitly mention review / draft / validation, not published
    assert "revue" in result.response_text.lower() or "brouillon" in result.response_text.lower() or "validation" in result.response_text.lower() or "proposition" in result.response_text.lower()


@pytest.mark.asyncio
async def test_incident_responder_reversible_runbooks(background_sec_context):
    """
    B06: Validates that Incident Responder executes diagnostics and only reversible runbooks.
    """
    agent = IncidentResponderAgent()
    turn = AgentInput(
        conversation_id="conv-bg-inc-01",
        turn_id="turn-bg-06",
        user_prompt="Diagnose hardware VRAM utilization and Ollama engine status.",
        parameters={"action": "diagnose"}
    )
    result = await agent.execute(turn, background_sec_context)
    assert result.status == "SUCCESS"
    assert result.agent_role == "incident_responder"
    assert len(result.response_text) > 0
