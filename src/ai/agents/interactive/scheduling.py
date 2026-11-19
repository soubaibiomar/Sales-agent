"""
Scheduling & Appointment Specialist Agent (A05).
Step 09: Complete 18-Role Agent Ecosystem & Sales Representative Copilot
"""
from src.ai.agents.base import BaseAgent


class SchedulingAgent(BaseAgent):
    def __init__(self):
        super().__init__("scheduling")

    def is_valid_booking_hour(self, time_str: str) -> bool:
        try:
            hour = int(time_str.split(":")[0])
            return 8 <= hour < 19
        except Exception:
            return False


SchedulingSpecialistAgent = SchedulingAgent
