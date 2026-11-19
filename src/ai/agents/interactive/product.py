"""
Product & Knowledge Specialist Agent (A02).
Step 09: Complete 18-Role Agent Ecosystem & Sales Representative Copilot
"""
from src.ai.agents.base import BaseAgent


class ProductKnowledgeAgent(BaseAgent):
    def __init__(self):
        super().__init__("product_knowledge")
