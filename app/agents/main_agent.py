import asyncio

from app.agents.error_analysis import ErrorAnalysisAgent
from app.agents.planning import PlanningAgent
from app.agents.root_cause import RootCauseAgent
from app.agents.slow_sql import SlowSqlAgent
from app.config import Settings
from app.datasources import DataSource
from app.events import WorkflowEventBus
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
        event_bus: WorkflowEventBus | None = None,
    ) -> DiagnosisState:
        await self._publish(event_bus, state, "stage_started", "planning", "任务规划 Agent 开始执行")
        state.planning = await self.planning.run(state.fault_description, state.service_hint)
        await self._publish(
            event_bus,
            state,
            "stage_completed",
            "planning",
            "任务规划 Agent 执行完成",
            payload={"planning": state.planning.model_dump(mode="json")},
        )
        if state.planning.missing_information and not state.human_inputs:
            state.status = DiagnosisStatus.NEED_USER_INPUT
            state.need_user_input = state.planning.missing_information
            await self._publish(
                event_bus,
                state,
                "need_user_input",
                "planning",
                "任务规划阶段需要人工补充信息",
                payload={"need_user_input": state.need_user_input},
            )
            return state

        error_task = self._run_error_analysis(state, data_source, event_bus)
        sql_task = self._run_slow_sql(state, data_source, event_bus)
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
            await self._publish(
                event_bus,
                state,
                "need_user_input",
                "analysis",
                "上游分析阶段需要人工补充信息",
                payload={"need_user_input": state.need_user_input},
            )
            return state

        upstream_errors = [
            error.model_dump(mode="json")
            for error in [*error_context.source_errors, *sql_context.source_errors]
        ]
        await self._publish(event_bus, state, "stage_started", "root_cause", "根因分析 Agent 开始执行")
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
        await self._publish(
            event_bus,
            state,
            "stage_completed",
            "root_cause",
            "根因分析 Agent 执行完成",
            payload={"root_cause": state.root_cause.model_dump(mode="json")},
        )
        state.collected_data = self._merge_collected_data(error_context, sql_context, root_context)

        if state.root_cause.confidence < low_confidence_threshold:
            state.status = DiagnosisStatus.NEED_USER_INPUT
            state.need_user_input = state.root_cause.missing_information or [
                "请补充更精确的故障时间窗口、影响服务、关键错误日志、最近变更或可复现步骤。"
            ]
            await self._publish(
                event_bus,
                state,
                "need_user_input",
                "root_cause",
                "根因置信度低，需要人工补充信息",
                payload={"need_user_input": state.need_user_input},
            )
        else:
            state.status = DiagnosisStatus.COMPLETED
            state.need_user_input = []
            await self._publish(event_bus, state, "diagnosis_completed", "workflow", "诊断已完成")
        return state

    async def _run_error_analysis(
        self,
        state: DiagnosisState,
        data_source: DataSource,
        event_bus: WorkflowEventBus | None,
    ):
        await self._publish(event_bus, state, "stage_started", "error_analysis", "错误分析 Agent 开始执行")
        result = await self.error_analysis.run(state.fault_description, state.service_hint, data_source)
        await self._publish(
            event_bus,
            state,
            "stage_completed",
            "error_analysis",
            "错误分析 Agent 执行完成",
            payload={"error_analysis": result[0].model_dump(mode="json")},
        )
        return result

    async def _run_slow_sql(
        self,
        state: DiagnosisState,
        data_source: DataSource,
        event_bus: WorkflowEventBus | None,
    ):
        await self._publish(event_bus, state, "stage_started", "slow_sql", "慢 SQL Agent 开始执行")
        result = await self.slow_sql.run(state.fault_description, state.service_hint, data_source)
        await self._publish(
            event_bus,
            state,
            "stage_completed",
            "slow_sql",
            "慢 SQL Agent 执行完成",
            payload={"slow_sql_analysis": result[0].model_dump(mode="json")},
        )
        return result

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

    async def _publish(
        self,
        event_bus: WorkflowEventBus | None,
        state: DiagnosisState,
        event: str,
        stage: str,
        message: str,
        payload: dict | None = None,
    ) -> None:
        if event_bus is None:
            return
        await event_bus.publish(
            diagnosis_id=state.diagnosis_id,
            event=event,
            stage=stage,
            status=state.status.value,
            message=message,
            payload=payload,
        )
