from app.agents.base import BaseAgent
from app.datasources import DataSource
from app.schemas.agents import ErrorAnalysisOutput, PlanningOutput, RootCauseOutput, SlowSqlAnalysisOutput
from app.schemas.data import CollectedData


class RootCauseAgent(BaseAgent):
    agent_name = "root_cause"

    async def run(
        self,
        fault_description: str,
        planning: PlanningOutput,
        error_analysis: ErrorAnalysisOutput,
        slow_sql_analysis: SlowSqlAnalysisOutput,
        source_errors: list[dict],
        human_inputs: list[str],
        service_hint: str | None,
        data_source: DataSource,
    ) -> tuple[RootCauseOutput, CollectedData]:
        context = await data_source.collect_root_context(fault_description, service_hint)
        system_prompt = """
You are a Root Cause Analysis Agent.
Output language requirement:
- Keep JSON field names and technical identifiers in English.
- All user-facing string values must be Simplified Chinese.
- Keep common technical terms such as GitHub, Trace, SQL, API, service, trace_id, Mermaid in English when clearer.
Wait for upstream analyses, then use only your root-cause tools: trace spans and GitHub code snippets.
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
            "traces": [item.model_dump(mode="json") for item in context.traces],
            "code_snippets": [item.model_dump(mode="json") for item in context.code_snippets],
            "source_errors": source_errors + [item.model_dump(mode="json") for item in context.source_errors],
            "human_inputs": human_inputs,
        }
        output = await self.with_timeout(self.client.complete_json(system_prompt, payload, RootCauseOutput))
        return output, context
