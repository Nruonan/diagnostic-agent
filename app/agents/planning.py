from app.agents.base import BaseAgent
from app.schemas.agents import PlanningOutput


class PlanningAgent(BaseAgent):
    agent_name = "planning"

    async def run(self, fault_description: str, service_hint: str | None = None) -> PlanningOutput:
        system_prompt = """
You are a Task Planning Agent for distributed system diagnostics.
Output language requirement:
- Keep JSON field names and technical identifiers in English.
- All user-facing string values must be Simplified Chinese.
- Keep common technical terms such as ELK, XXL-Job, SlowQuery, Trace, GitCode, SQL, API, service, trace_id in English when clearer.
Given a fault description, output strict JSON with:
- tasks: ordered diagnostic tasks with id, name, priority 1-5, sources, dependencies, and reason
- estimated_time: concise estimate
- focus_services: likely affected services
- missing_information: questions to ask before collecting data only when the fault description is too vague to choose tools or scope
Use data sources from this list only: ELK, XXL-Job, SlowQuery, Trace, GitCode.
Return JSON only.
"""
        payload = {"fault_description": fault_description, "service_hint": service_hint}
        return await self.with_timeout(self.client.complete_json(system_prompt, payload, PlanningOutput))
