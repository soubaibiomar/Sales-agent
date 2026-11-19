"""
Negotiation & Objections Specialist Agent (A06).
Step 09: Complete 18-Role Agent Ecosystem & Sales Representative Copilot
"""
from typing import Tuple
from src.ai.agents.base import BaseAgent


class NegotiationAgent(BaseAgent):
    def __init__(self):
        super().__init__("negotiation_objections")

    def evaluate_discount_request(self, discount_pct: float, rep_role: str = "SALES_REP") -> Tuple[bool, str]:
        if rep_role == "SALES_REP" and discount_pct > 15.0:
            return False, f"Requested discount {discount_pct}% exceeds sales rep authority ceiling of 15%."
        return True, "Discount within authorized delegation limits."


NegotiationSpecialistAgent = NegotiationAgent
