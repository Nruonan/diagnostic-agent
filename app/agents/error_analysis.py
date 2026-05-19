from app.agents.base import BaseAgent
from app.schemas.agents import ErrorAnalysisOutput
from app.schemas.data import JobRecord, LogRecord


class ErrorAnalysisAgent(BaseAgent):
    agent_name = "error_analysis"

    async def run(
        self,
        fault_description: str,
        logs: list[LogRecord],
        jobs: list[JobRecord],
    ) -> ErrorAnalysisOutput:
        system_prompt = """
You are an Error Analysis Agent.
Analyze logs and XXL-Job records for error patterns, timestamps, affected services, and suspects.
Output strict JSON with:
- errors: timestamp, error_type, service, message, trace_id, evidence
  - evidence must be an array of strings. Never return evidence as a string or null.
- timeline: ordered event descriptions
- suspects: concrete suspected failure points
- summary: concise conclusion
Example error item:
{"timestamp":"2026-05-19T10:00:01+08:00","error_type":"DatabaseTimeout","service":"user-service","message":"Authentication query exceeded service deadline","trace_id":"trace-login-001","evidence":["DatabaseTimeout: SELECT user profile by mobile"]}
Return JSON only.
"""
        payload = {
            "fault_description": fault_description,
            "logs": [item.model_dump(mode="json") for item in logs],
            "jobs": [item.model_dump(mode="json") for item in jobs],
        }
        return await self.with_timeout(self.client.complete_json(system_prompt, payload, ErrorAnalysisOutput))
