from app.agents.base import BaseAgent
from app.datasources import DataSource
from app.schemas.agents import ErrorAnalysisOutput
from app.schemas.data import CollectedData


class ErrorAnalysisAgent(BaseAgent):
    agent_name = "error_analysis"

    async def run(
        self,
        fault_description: str,
        service_hint: str | None,
        data_source: DataSource,
    ) -> tuple[ErrorAnalysisOutput, CollectedData]:
        context = await data_source.collect_error_context(fault_description, service_hint)
        system_prompt = """
You are an Error Analysis Agent.
Use only your error-analysis tool evidence: ELK logs, XXL-Job records, and Zabbix events.
Analyze error patterns, timestamps, affected services, and suspects.
Output strict JSON with:
- errors: timestamp, error_type, service, message, trace_id, evidence
  - evidence must be an array of strings. Never return evidence as a string or null.
- timeline: ordered event descriptions
- suspects: concrete suspected failure points
- summary: concise conclusion
- missing_information: questions for the user only when error evidence is missing, ambiguous, or contradictory
Example error item:
{"timestamp":"2026-05-19T10:00:01+08:00","error_type":"DatabaseTimeout","service":"user-service","message":"Authentication query exceeded service deadline","trace_id":"trace-login-001","evidence":["DatabaseTimeout: SELECT user profile by mobile"]}
Return JSON only.
"""
        payload = {
            "fault_description": fault_description,
            "logs": [item.model_dump(mode="json") for item in context.logs],
            "jobs": [item.model_dump(mode="json") for item in context.jobs],
            "zabbix_events": [item.model_dump(mode="json") for item in context.zabbix_events],
            "source_errors": [item.model_dump(mode="json") for item in context.source_errors],
        }
        output = await self.with_timeout(self.client.complete_json(system_prompt, payload, ErrorAnalysisOutput))
        return output, context
