from app.agents.base import BaseAgent
from app.schemas.agents import SlowSqlAnalysisOutput
from app.schemas.data import SlowQueryRecord


class SlowSqlAgent(BaseAgent):
    agent_name = "slow_sql"

    async def run(self, fault_description: str, slow_queries: list[SlowQueryRecord]) -> SlowSqlAnalysisOutput:
        system_prompt = """
You are a Slow SQL Analysis Agent.
Review slow query records for bottlenecks, full scans, missing indexes, lock contention, and rewrite opportunities.
Output strict JSON with:
- slow_queries: query, service, exec_time_ms, rows_examined, issues, optimizations, trace_id
- optimizations: global optimization actions
- summary: concise conclusion
Return JSON only.
"""
        payload = {
            "fault_description": fault_description,
            "slow_queries": [item.model_dump(mode="json") for item in slow_queries],
        }
        return await self.with_timeout(self.client.complete_json(system_prompt, payload, SlowSqlAnalysisOutput))

