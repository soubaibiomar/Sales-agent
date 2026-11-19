"""
Account Research & Enrichment Agent (B02).
Step 09: Complete 18-Role Agent Ecosystem & Sales Representative Copilot
"""
from src.ai.agents.base import BaseAgent


class ResearchAgent(BaseAgent):
    def __init__(self):
        super().__init__("research")
