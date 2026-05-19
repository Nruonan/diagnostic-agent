from app.agents.base import BaseAgent
from app.schemas.agents import PlanningOutput


class PlanningAgent(BaseAgent):
    agent_name = "planning"

    async def run(self, fault_description: str, service_hint: str | None = None) -> PlanningOutput:
        system_prompt = """
You are a Task Planning Agent for distributed system diagnostics.
Given a fault description, output strict JSON with:
- tasks: ordered diagnostic tasks with id, name, priority 1-5, sources, dependencies, and reason
- estimated_time: concise estimate
- focus_services: likely affected services
Use data sources from this list only: ELK, XXL-Job, SlowQuery, Trace, GitCode.
Return JSON only.
"""
        payload = {"fault_description": fault_description, "service_hint": service_hint}
        return await self.with_timeout(self.client.complete_json(system_prompt, payload, PlanningOutput))

