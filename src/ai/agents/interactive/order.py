"""
Order & Payment Specialist Agent (A04).
Step 09: Complete 18-Role Agent Ecosystem & Sales Representative Copilot
"""
from src.ai.agents.base import BaseAgent


class OrderPaymentAgent(BaseAgent):
    def __init__(self):
        super().__init__("order_payment")
