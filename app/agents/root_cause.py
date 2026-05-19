from app.agents.base import BaseAgent
from app.schemas.agents import ErrorAnalysisOutput, PlanningOutput, RootCauseOutput, SlowSqlAnalysisOutput
from app.schemas.data import CodeSnippet, TraceSpan


class RootCauseAgent(BaseAgent):
    agent_name = "root_cause"

    async def run(
        self,
        fault_description: str,
        planning: PlanningOutput,
        error_analysis: ErrorAnalysisOutput,
        slow_sql_analysis: SlowSqlAnalysisOutput,
        traces: list[TraceSpan],
        code_snippets: list[CodeSnippet],
        source_errors: list[dict],
        human_inputs: list[str],
    ) -> RootCauseOutput:
        system_prompt = """
You are a Root Cause Analysis Agent.
Synthesize task planning, error analysis, slow SQL analysis, trace spans, code snippets, source errors, and human input.
Output strict JSON with:
- root_cause: one precise root cause statement
- confidence: number from 0 to 1
- evidence: concrete evidence list
- fix_steps: ordered fix actions
- mermaid: Mermaid diagram text for timeline or call chain
- missing_information: list of facts needed if confidence is low
If evidence is insufficient, lower confidence and list missing_information. Do not invent facts.
Return JSON only.
"""
        payload = {
            "fault_description": fault_description,
            "planning": planning.model_dump(mode="json"),
            "error_analysis": error_analysis.model_dump(mode="json"),
            "slow_sql_analysis": slow_sql_analysis.model_dump(mode="json"),
            "traces": [item.model_dump(mode="json") for item in traces],
            "code_snippets": [item.model_dump(mode="json") for item in code_snippets],
            "source_errors": source_errors,
            "human_inputs": human_inputs,
        }
        return await self.with_timeout(self.client.complete_json(system_prompt, payload, RootCauseOutput))

