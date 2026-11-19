"""
Order & Payment Specialist Agent (A04).
Step 09: Complete 18-Role Agent Ecosystem & Sales Representative Copilot
"""
from src.ai.agents.base import BaseAgent


class OrderPaymentAgent(BaseAgent):
    def __init__(self):
        super().__init__("order_payment")

    def format_order_summary(self, order_number: str, status: str, tracking_number: str) -> str:
        return f"Commande {order_number} statut {status}. Numéro de suivi: {tracking_number}"


OrderCheckoutSpecialistAgent = OrderPaymentAgent
