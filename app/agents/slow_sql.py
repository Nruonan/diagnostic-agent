from app.agents.base import BaseAgent
from app.datasources import DataSource
from app.schemas.agents import SlowSqlAnalysisOutput
from app.schemas.data import CollectedData


class SlowSqlAgent(BaseAgent):
    agent_name = "slow_sql"

    async def run(
        self,
        fault_description: str,
        service_hint: str | None,
        data_source: DataSource,
    ) -> tuple[SlowSqlAnalysisOutput, CollectedData]:
        context = await data_source.collect_sql_context(fault_description, service_hint)
        system_prompt = """
You are a Slow SQL Analysis Agent.
Output language requirement:
- Keep JSON field names and technical identifiers in English.
- All user-facing string values must be Simplified Chinese.
- Keep common technical terms such as SQL, SlowQuery, Prometheus, API, service, trace_id in English when clearer.
Use only your SQL-performance tool evidence: slow query records and Prometheus metrics.
Review bottlenecks, full scans, missing indexes, lock contention, and rewrite opportunities.
Output strict JSON with:
- slow_queries: query, service, exec_time_ms, rows_examined, issues, optimizations, trace_id
- optimizations: global optimization actions
- summary: concise conclusion
- missing_information: questions for the user only when SQL or metric evidence is missing, ambiguous, or contradictory
Return JSON only.
"""
        payload = {
            "fault_description": fault_description,
            "slow_queries": [item.model_dump(mode="json") for item in context.slow_queries],
            "metrics": [item.model_dump(mode="json") for item in context.metrics],
            "source_errors": [item.model_dump(mode="json") for item in context.source_errors],
        }
        output = await self.with_timeout(self.client.complete_json(system_prompt, payload, SlowSqlAnalysisOutput))
        return output, context
