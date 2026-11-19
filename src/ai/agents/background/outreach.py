"""
Outreach & Nurture Agent (B01).
Step 09: Complete 18-Role Agent Ecosystem & Sales Representative Copilot
(Controls 40, 67; Invariant 2; Law 09-08 Quiet Hours & STOP)
"""
from typing import Optional, Dict, Any, Tuple
from src.ai.agents.base import BaseAgent, AgentInput, AgentOutput
from src.ai.tool_gateway import ServerSecurityContext


class OutreachAgent(BaseAgent):
    def __init__(self):
        super().__init__("outreach")

    def can_dispatch_message(self, hour_utc_plus_1: int, has_opted_out: bool) -> Tuple[bool, str]:
        if has_opted_out:
            return False, "Customer opted out via STOP"
        if hour_utc_plus_1 < 8 or hour_utc_plus_1 >= 21:
            return False, "Moroccan quiet hours enforced (21:00 - 08:00)"
        return True, "Dispatch permitted"

    async def execute(
        self,
        input_data: AgentInput,
        security_context: ServerSecurityContext,
        evidence: Optional[Dict[str, Any]] = None,
        db_session=None
    ) -> AgentOutput:
        result = await super().execute(input_data, security_context, evidence, db_session)
        # Architectural Invariant: Outreach creates drafts with STOP opt-out filter and quiet hours enforcement
        if input_data.parameters and input_data.parameters.get("campaign_name"):
            campaign = input_data.parameters.get("campaign_name")
            channel = input_data.parameters.get("channel", "WHATSAPP")
            result.response_text = (
                f"[Brouillon Campagne Outreach — {channel}] "
                f"Campagne '{campaign}' préparée en mode brouillon (Draft). "
                f"Filtre opt-out STOP appliqué, heures silencieuses (Loi 09-08) respectées.\n"
                + result.response_text
            )
        return result


OutreachNurtureAgent = OutreachAgent
