import asyncio

from app.agents.error_analysis import ErrorAnalysisAgent
from app.agents.planning import PlanningAgent
from app.agents.root_cause import RootCauseAgent
from app.agents.slow_sql import SlowSqlAgent
from app.config import Settings
from app.datasources import DataSource
from app.llm import LLMClient
from app.schemas.data import CollectedData
from app.schemas.diagnosis import DiagnosisState, DiagnosisStatus


class MainAgent:
    def __init__(self, settings: Settings, client: LLMClient):
        self.planning = PlanningAgent(client, settings)
        self.error_analysis = ErrorAnalysisAgent(client, settings)
        self.slow_sql = SlowSqlAgent(client, settings)
        self.root_cause = RootCauseAgent(client, settings)

    async def run(
        self,
        state: DiagnosisState,
        data_source: DataSource,
        low_confidence_threshold: float,
    ) -> DiagnosisState:
        state.planning = await self.planning.run(state.fault_description, state.service_hint)
        if state.planning.missing_information and not state.human_inputs:
            state.status = DiagnosisStatus.NEED_USER_INPUT
            state.need_user_input = state.planning.missing_information
            return state

        error_task = self.error_analysis.run(state.fault_description, state.service_hint, data_source)
        sql_task = self.slow_sql.run(state.fault_description, state.service_hint, data_source)
        (state.error_analysis, error_context), (state.slow_sql_analysis, sql_context) = await asyncio.gather(
            error_task,
            sql_task,
        )
        upstream_questions = [
            *state.error_analysis.missing_information,
            *state.slow_sql_analysis.missing_information,
        ]
        if upstream_questions and not state.human_inputs:
            state.collected_data = self._merge_collected_data(error_context, sql_context)
            state.status = DiagnosisStatus.NEED_USER_INPUT
            state.need_user_input = upstream_questions
            return state

        upstream_errors = [
            error.model_dump(mode="json")
            for error in [*error_context.source_errors, *sql_context.source_errors]
        ]
        state.root_cause, root_context = await self.root_cause.run(
            fault_description=state.fault_description,
            planning=state.planning,
            error_analysis=state.error_analysis,
            slow_sql_analysis=state.slow_sql_analysis,
            source_errors=upstream_errors,
            human_inputs=state.human_inputs,
            service_hint=state.service_hint,
            data_source=data_source,
        )
        state.collected_data = self._merge_collected_data(error_context, sql_context, root_context)

        if state.root_cause.confidence < low_confidence_threshold:
            state.status = DiagnosisStatus.NEED_USER_INPUT
            state.need_user_input = state.root_cause.missing_information or [
                "请补充更精确的故障时间窗口、影响服务、关键错误日志、最近变更或可复现步骤。"
            ]
        else:
            state.status = DiagnosisStatus.COMPLETED
            state.need_user_input = []
        return state

    def _merge_collected_data(self, *contexts: CollectedData) -> CollectedData:
        collected = CollectedData()
        for context in contexts:
            collected.logs.extend(context.logs)
            collected.jobs.extend(context.jobs)
            collected.zabbix_events.extend(context.zabbix_events)
            collected.slow_queries.extend(context.slow_queries)
            collected.metrics.extend(context.metrics)
            collected.traces.extend(context.traces)
            collected.code_snippets.extend(context.code_snippets)
            collected.source_errors.extend(context.source_errors)
        return collected
