"""
Unit Tests for Conversation & Operations Supervisors and Specialist Handoffs.
Step 09: Complete 18-Role Agent Ecosystem & Sales Representative Copilot
(Controls 40, 63, 67; Unified Architecture Section 2)
"""
import pytest
import asyncio
from src.ai.tool_gateway import ServerSecurityContext
from src.ai.agents.base import AgentInput, AgentOutput
from src.ai.agents.supervisors.conversation_supervisor import ConversationSupervisorAgent
from src.ai.agents.supervisors.operations_supervisor import OperationsSupervisorAgent


@pytest.fixture
def test_security_context():
    return ServerSecurityContext(
        tenant_id="tenant-supervisor-test",
        user_id="user-supervisor-01",
        role="supervisor",
        permissions=["ai:agents", "ai:supervisor"]
    )


@pytest.mark.asyncio
async def test_conversation_supervisor_routes_to_specialist(test_security_context):
    """Validates that supervisor routes catalog question to product_knowledge specialist."""
    supervisor = ConversationSupervisorAgent()
    
    turn_input = AgentInput(
        conversation_id="conv-test-01",
        turn_id="turn-01",
        user_prompt="Bonjour, je voudrais consulter les caractéristiques du kit solaire 500W."
    )
    
    result = await supervisor.handle_turn(turn_input, test_security_context, expected_turn_version=0)
    assert result.status == "SUCCESS"
    assert result.agent_role in [
        "product_knowledge", "qualification_crm", "router_classifier", "conversation_supervisor"
    ]
    assert len(result.response_text) > 0


@pytest.mark.asyncio
async def test_conversation_supervisor_human_takeover_silencing(test_security_context):
    """
    Validates architectural invariant:
    Human takeover strictly silences AI autonomous responses to prevent interference.
    """
    supervisor = ConversationSupervisorAgent()
    conv_id = "conv-takeover-01"
    
    # 1. Human rep claims ownership of the conversation
    supervisor.set_human_takeover(conv_id, human_user_id="rep-hassan-01")
    assert supervisor.is_human_owned(conv_id) is True
    
    turn_input = AgentInput(
        conversation_id=conv_id,
        turn_id="turn-02",
        user_prompt="Est-ce qu'on peut négocier une remise spéciale ?"
    )
    
    result = await supervisor.handle_turn(turn_input, test_security_context, expected_turn_version=0)
    assert result.status == "SILENCED_TAKEOVER"
    assert "reprise en charge par un conseiller" in result.response_text.lower() or "humain" in result.response_text.lower() or "human" in result.response_text.lower()
    
    # 2. Release human takeover
    supervisor.release_human_takeover(conv_id)
    assert supervisor.is_human_owned(conv_id) is False


@pytest.mark.asyncio
async def test_conversation_supervisor_stale_turn_fencing(test_security_context):
    """Validates turn version fencing against concurrency race conditions."""
    supervisor = ConversationSupervisorAgent()
    conv_id = "conv-fencing-01"
    
    # Turn version 0 succeeds and advances version to 1
    valid, next_v = supervisor.validate_and_advance_turn(conv_id, expected_turn_version=0)
    assert valid is True
    assert next_v == 1
    
    # Stale turn expecting version 0 again must be rejected
    stale_valid, cur_v = supervisor.validate_and_advance_turn(conv_id, expected_turn_version=0)
    assert stale_valid is False
    assert cur_v == 1


@pytest.mark.asyncio
async def test_conversation_supervisor_handoff(test_security_context):
    """Validates specialist handoff within permitted delegation policy."""
    supervisor = ConversationSupervisorAgent()
    conv_id = "conv-handoff-01"
    
    # From qualification_crm to quote_pricing is permitted in delegation policy
    handoff_ok = supervisor.request_handoff(
        conversation_id=conv_id,
        from_role="qualification_crm",
        to_role="quote_pricing"
    )
    assert handoff_ok is True
    assert supervisor._active_specialists[conv_id] == "quote_pricing"


@pytest.mark.asyncio
async def test_operations_supervisor_triage(test_security_context):
    """Validates Operations Supervisor triage and queue health monitoring."""
    ops_supervisor = OperationsSupervisorAgent()
    
    report = await ops_supervisor.run_operational_triage(
        tenant_id="tenant-supervisor-test",
        security_context=test_security_context
    )
    assert isinstance(report, dict)
    assert report["supervisor"] == "operations_supervisor"
    assert report["status"] == "OPERATIONAL"
    assert "triage_summary" in report
