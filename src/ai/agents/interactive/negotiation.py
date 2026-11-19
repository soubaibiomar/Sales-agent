"""
Negotiation & Objections Specialist Agent (A06).
Step 09: Complete 18-Role Agent Ecosystem & Sales Representative Copilot
"""
from src.ai.agents.base import BaseAgent


class NegotiationAgent(BaseAgent):
    def __init__(self):
        super().__init__("negotiation_objections")
