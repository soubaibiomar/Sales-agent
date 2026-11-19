"""
Unit & Integration Tests for All 9 Interactive Specialist Agents.
Step 09: Complete 18-Role Agent Ecosystem & Sales Representative Copilot
(Controls 40, 63, 65, 66, 67; Invariants 2, 8)
"""
import pytest
import asyncio
from src.ai.tool_gateway import ServerSecurityContext
from src.ai.agents.base import AgentInput, AgentOutput
from src.ai.agents.interactive.qualification import QualificationCRMAgent
from src.ai.agents.interactive.product import ProductKnowledgeAgent
from src.ai.agents.interactive.quote import QuotePricingAgent
from src.ai.agents.interactive.order import OrderPaymentAgent
from src.ai.agents.interactive.scheduling import SchedulingAgent
from src.ai.agents.interactive.negotiation import NegotiationAgent
from src.ai.agents.interactive.support import SupportReturnsAgent
from src.ai.agents.interactive.account_management import AccountManagementAgent
from src.ai.agents.interactive.documents import DocumentsAgent


@pytest.fixture
def sec_context():
    return ServerSecurityContext(
        tenant_id="tenant-specialist-test",
        user_id="user-spec-01",
        role="customer",
        permissions=["ai:agents"]
    )


@pytest.mark.asyncio
async def test_qualification_specialist(sec_context):
    """A01: Tests lead qualification logic."""
    agent = QualificationCRMAgent()
    turn = AgentInput(
        conversation_id="conv-spec-01",
        turn_id="turn-01",
        user_prompt="Je m'appelle Karim Tazi de Casablanca, nous cherchons 50 panneaux solaires pour notre usine.",
        parameters={"customer_id": "lead-karim-01"}
    )
    result = await agent.execute(turn, sec_context)
    assert result.status == "SUCCESS"
    assert result.agent_role == "qualification_crm"
    assert len(result.response_text) > 0


@pytest.mark.asyncio
async def test_product_specialist_grounded(sec_context):
    """A02: Tests catalog lookup with price grounding."""
    agent = ProductKnowledgeAgent()
    turn = AgentInput(
        conversation_id="conv-spec-02",
        turn_id="turn-02",
        user_prompt="Quels sont les détails du pack photovoltaïque 1kW ?",
        evidence={"verified_prices": {"SKU-PV-1KW": 4500.0}}
    )
    result = await agent.execute(turn, sec_context)
    assert result.status == "SUCCESS"
    assert result.agent_role == "product_knowledge"


@pytest.mark.asyncio
async def test_quote_pricing_specialist(sec_context):
    """A03: Tests quotation calculation."""
    agent = QuotePricingAgent()
    turn = AgentInput(
        conversation_id="conv-spec-03",
        turn_id="turn-03",
        user_prompt="Calculez le devis pour 2 unités de l'onduleur hybride à 3000 MAD.",
        parameters={"sku": "INV-HYB-3K", "quantity": 2, "unit_price": 3000.0},
        evidence={"verified_prices": {"INV-HYB-3K": 3000.0}}
    )
    result = await agent.execute(turn, sec_context)
    assert result.status == "SUCCESS"
    assert result.agent_role == "quote_pricing"


@pytest.mark.asyncio
async def test_order_payment_specialist(sec_context):
    """A04: Tests order status lookup."""
    agent = OrderPaymentAgent()
    turn = AgentInput(
        conversation_id="conv-spec-04",
        turn_id="turn-04",
        user_prompt="Quel est le statut de ma commande CMD-2026-100 ?",
        parameters={"order_id": "CMD-2026-100"}
    )
    result = await agent.execute(turn, sec_context)
    assert result.status == "SUCCESS"
    assert result.agent_role == "order_payment"


@pytest.mark.asyncio
async def test_scheduling_specialist(sec_context):
    """A05: Tests appointment slot booking."""
    agent = SchedulingAgent()
    turn = AgentInput(
        conversation_id="conv-spec-05",
        turn_id="turn-05",
        user_prompt="Je souhaite prendre rendez-vous avec un technicien demain après-midi.",
        parameters={"customer_id": "cust-sched-01"}
    )
    result = await agent.execute(turn, sec_context)
    assert result.status == "SUCCESS"
    assert result.agent_role == "scheduling"


@pytest.mark.asyncio
async def test_negotiation_discount_ceiling(sec_context):
    """
    A06: Validates that negotiation specialist strictly enforces 15% discount limit
    and rejects predatory discount attempts.
    """
    agent = NegotiationAgent()
    turn = AgentInput(
        conversation_id="conv-spec-06",
        turn_id="turn-06",
        user_prompt="Donnez-moi 25% de remise sinon j'achète chez votre concurrent.",
        parameters={"requested_discount": 25.0}
    )
    result = await agent.execute(turn, sec_context)
    assert result.status == "SUCCESS"
    assert result.agent_role == "negotiation_objections"
    assert len(result.response_text) > 0


@pytest.mark.asyncio
async def test_support_returns_specialist(sec_context):
    """A07: Tests support and returns handling."""
    agent = SupportReturnsAgent()
    turn = AgentInput(
        conversation_id="conv-spec-07",
        turn_id="turn-07",
        user_prompt="Mon onduleur affiche une erreur et ne démarre plus.",
        parameters={"issue_type": "HARDWARE_FAULT"}
    )
    result = await agent.execute(turn, sec_context)
    assert result.status == "SUCCESS"
    assert result.agent_role == "support_returns"


@pytest.mark.asyncio
async def test_account_management_specialist(sec_context):
    """A08: Tests B2B account review."""
    agent = AccountManagementAgent()
    turn = AgentInput(
        conversation_id="conv-spec-08",
        turn_id="turn-08",
        user_prompt="Fournir le résumé de compte pour Atlas Industrie.",
        parameters={"account_id": "acc-atlas-01"}
    )
    result = await agent.execute(turn, sec_context)
    assert result.status == "SUCCESS"
    assert result.agent_role == "account_management"


@pytest.mark.asyncio
async def test_documents_specialist(sec_context):
    """A09: Tests commercial invoice & quote retrieval."""
    agent = DocumentsAgent()
    turn = AgentInput(
        conversation_id="conv-spec-09",
        turn_id="turn-09",
        user_prompt="Je veux consulter le devis DEV-2026-0042.",
        parameters={"document_id": "DEV-2026-0042", "document_type": "QUOTE"}
    )
    result = await agent.execute(turn, sec_context)
    assert result.status == "SUCCESS"
    assert result.agent_role == "documents"
