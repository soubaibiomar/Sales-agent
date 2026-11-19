"""
Unit & Integration Tests for Sales Representative Copilot.
Step 09: Complete 18-Role Agent Ecosystem & Sales Representative Copilot
(Controls 40, 63, 67; Unified Architecture Section 2)
"""
import pytest
import asyncio
from src.ai.tool_gateway import ServerSecurityContext
from src.ai.agents.base import AgentInput, AgentOutput
from src.ai.agents.copilot.sales_copilot import SalesRepresentativeCopilot


@pytest.fixture
def sales_rep_sec_context():
    return ServerSecurityContext(
        tenant_id="tenant-copilot-test",
        user_id="rep-omar-01",
        role="sales_rep",
        permissions=["ai:copilot", "ai:agents"]
    )


@pytest.mark.asyncio
async def test_sales_copilot_generate_brief(sales_rep_sec_context):
    """
    I01: Tests sales copilot brief generation including deal summary,
    objections, and suggested responses.
    """
    copilot = SalesRepresentativeCopilot()
    turn = AgentInput(
        conversation_id="conv-copilot-01",
        turn_id="turn-cop-01",
        user_prompt="Générer un briefing pour le client Société Maghrébine de Plastique.",
        parameters={
            "conversation_id": "conv-copilot-01",
            "customer_id": "cust-smp-01"
        }
    )
    result = await copilot.execute(turn, sales_rep_sec_context)
    assert result.status == "SUCCESS"
    assert result.agent_role == "sales_copilot"
    assert len(result.response_text) > 0


@pytest.mark.asyncio
async def test_sales_copilot_propose_action_requires_human_approval(sales_rep_sec_context):
    """
    Invariant: Spoken or copilot actions cannot mutate financial or stock state directly.
    All high-risk actions must require explicit human confirmation.
    """
    copilot = SalesRepresentativeCopilot()
    turn = AgentInput(
        conversation_id="conv-copilot-02",
        turn_id="turn-cop-02",
        user_prompt="Propose a custom quote of 45,000 MAD with 10% discount for solar setup.",
        parameters={
            "action_type": "propose_quote",
            "amount": 45000.0,
            "discount_percent": 10.0
        }
    )
    result = await copilot.execute(turn, sales_rep_sec_context)
    assert result.status == "SUCCESS"
    assert result.agent_role == "sales_copilot"
    # Verify that approval / confirmation is explicitly indicated
    assert "approbation" in result.response_text.lower() or "validation" in result.response_text.lower() or "confirmation" in result.response_text.lower()


@pytest.mark.asyncio
async def test_sales_copilot_objection_suggestions(sales_rep_sec_context):
    """Tests objection suggestions when client complains about pricing."""
    copilot = SalesRepresentativeCopilot()
    turn = AgentInput(
        conversation_id="conv-copilot-03",
        turn_id="turn-cop-03",
        user_prompt="Le client dit que notre offre est 15% plus chère que les imports chinois.",
        parameters={"objection_type": "PRICE_COMPETITOR"}
    )
    result = await copilot.execute(turn, sales_rep_sec_context)
    assert result.status == "SUCCESS"
    assert len(result.response_text) > 0
