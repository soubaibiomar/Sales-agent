"""
Pipeline Coach & Deal Monitor Agent (B03).
Step 09: Complete 18-Role Agent Ecosystem & Sales Representative Copilot
"""
from typing import Tuple
from src.ai.agents.base import BaseAgent


class PipelineCoachAgent(BaseAgent):
    def __init__(self):
        super().__init__("pipeline_coach")

    def evaluate_deal_staleness(self, days_idle: int, current_stage: str) -> Tuple[bool, str]:
        if days_idle > 14:
            return True, f"Deal stalled for {days_idle} days in {current_stage}. Trigger sales rep nudge."
        return False, "Deal velocity within normal cycle"
