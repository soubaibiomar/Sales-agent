"""
Unit Tests for Agent Registry and 18-Role Capability Catalog.
Step 09: Complete 18-Role Agent Ecosystem & Sales Representative Copilot
(Controls 40, 63, 67; Unified Architecture Section 2)
"""
import pytest
from src.ai.agents.registry import (
    AgentRegistry,
    AgentRoleDefinition,
    AGENT_CATALOG
)


def test_catalog_has_all_18_roles():
    """Validates that all 18 logical roles + 1 additional front-door classifier are registered."""
    roles = AgentRegistry.list_roles()
    assert len(roles) == 19  # 1 Router + 2 Supervisors + 9 Interactive + 6 Background + 1 Copilot
    role_codes = {r.role_code for r in roles}
    
    # Verify core catalog role codes
    expected_codes = {
        "R00", "S00_CONV", "S00_OPS",
        "A01", "A02", "A03", "A04", "A05", "A06", "A07", "A08", "A09",
        "B01", "B02", "B03", "B04", "B05", "B06",
        "I01"
    }
    assert expected_codes.issubset(role_codes)


def test_role_group_filtering():
    """Validates filtering by role group."""
    supervisors = AgentRegistry.list_by_group("SUPERVISOR")
    assert len(supervisors) == 2
    assert {s.role_id for s in supervisors} == {"conversation_supervisor", "operations_supervisor"}

    interactive = AgentRegistry.list_by_group("INTERACTIVE_SPECIALIST")
    assert len(interactive) == 9

    background = AgentRegistry.list_by_group("BACKGROUND_AGENT")
    assert len(background) == 6

    copilot = AgentRegistry.list_by_group("COPILOT")
    assert len(copilot) == 1
    assert copilot[0].role_id == "sales_copilot"


def test_model_tier_allocations():
    """
    Validates model allocation:
    - Default interactive roles use PRIMARY_4B to remain resident in VRAM.
    - Deep reasoning/analyst roles use REASONING_9B.
    """
    # 4B resident models
    assert AgentRegistry.get_model_tier("conversation_supervisor") == "PRIMARY_4B"
    assert AgentRegistry.get_model_tier("product_knowledge") == "PRIMARY_4B"
    assert AgentRegistry.get_model_tier("sales_copilot") == "PRIMARY_4B"
    
    # 9B on-demand reasoning models
    assert AgentRegistry.get_model_tier("analyst") == "REASONING_9B"
    assert AgentRegistry.get_model_tier("analyst") == "REASONING_9B"


def test_token_caps_within_hardware_budget():
    """Validates that token caps respect local 8GB VRAM envelope (<= 4096)."""
    for role in AgentRegistry.list_roles():
        assert role.context_token_cap <= 4096
        assert role.context_token_cap >= 1024


def test_allowed_tools_least_privilege():
    """Validates that critical financial/mutation tools are only in authorized roles."""
    # Discovery cannot reserve stock or process payments
    discovery_tools = AgentRegistry.get_allowed_tools("qualification_crm")
    assert "inventory.reserve" not in discovery_tools
    assert "payments.process" not in discovery_tools
    assert "crm.qualify_lead" in discovery_tools

    # Knowledge curator cannot publish without human review
    curator_tools = AgentRegistry.get_allowed_tools("knowledge_curator")
    assert "knowledge.propose_update" in curator_tools
    assert "inventory.reserve" not in curator_tools

    # Copilot has read/propose tools but no unconfirmed mutations
    copilot_tools = AgentRegistry.get_allowed_tools("sales_copilot")
    assert "copilot.generate_brief" in copilot_tools
    assert "copilot.propose_action" in copilot_tools
    assert "payments.process" not in copilot_tools


def test_unknown_role_raises_value_error():
    """Validates fail-closed behavior for unregistered role lookups."""
    with pytest.raises(ValueError) as exc:
        AgentRegistry.get_role("non_existent_super_agent")
    assert "not registered" in str(exc.value)
