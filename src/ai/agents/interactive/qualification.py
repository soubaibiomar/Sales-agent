"""
Qualification & CRM Specialist Agent (A01).
Step 09: Complete 18-Role Agent Ecosystem & Sales Representative Copilot
"""
import re
from typing import Dict, Any
from src.ai.agents.base import BaseAgent


class QualificationCRMAgent(BaseAgent):
    def __init__(self):
        super().__init__("qualification_crm")

    def extract_qualification_data(self, text: str) -> Dict[str, Any]:
        data = {}
        size_match = re.search(r'(\d+)\s*(?:employés|salariés|collaborateurs|personnes)', text, re.IGNORECASE)
        if size_match:
            data["company_size"] = int(size_match.group(1))
        budget_match = re.search(r'(\d+)\s*(?:MAD|dh|dirhams)', text, re.IGNORECASE)
        if budget_match:
            data["budget_mad"] = int(budget_match.group(1))
        return data


QualificationSpecialistAgent = QualificationCRMAgent
