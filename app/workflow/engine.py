from typing import Any
from uuid import uuid4

from app.agents import MainAgent
from app.datasources import DataSource
from app.events import WorkflowEventBus
from app.llm import LLMConfigurationError, LLMRequestError, LLMResponseError
from app.schemas.common import RuntimeErrorInfo, utc_now
from app.schemas.diagnosis import DiagnosisCreate, DiagnosisState, DiagnosisStatus
from app.storage import DiagnosisStore


class WorkflowEngine:
    def __init__(
        self,
        agents: MainAgent,
        data_source: DataSource,
        store: DiagnosisStore,
        low_confidence_threshold: float,
        event_bus: WorkflowEventBus,
    ):
        self.agents = agents
        self.data_source = data_source
        self.store = store
        self.low_confidence_threshold = low_confidence_threshold
        self.event_bus = event_bus

    async def start(
        self,
        request: DiagnosisCreate,
        trigger_source: str = "manual",
        trigger_context: dict[str, Any] | None = None,
    ) -> DiagnosisState:
        state = await self.create(request, trigger_source, trigger_context)
        return await self._run(state)

    async def create(
        self,
        request: DiagnosisCreate,
        trigger_source: str = "manual",
        trigger_context: dict[str, Any] | None = None,
    ) -> DiagnosisState:
        state = DiagnosisState(
            diagnosis_id=str(uuid4()),
            status=DiagnosisStatus.CREATED,
            fault_description=request.fault_description,
            service_hint=request.service_hint,
            trigger_source=trigger_source,
            trigger_context=trigger_context,
        )
        await self.store.save(state)
        await self.store.create_session(
            session_id=state.diagnosis_id,
            diagnosis_id=state.diagnosis_id,
            title=_session_title(request.fault_description, state.diagnosis_id),
            metadata={
                "service_hint": request.service_hint,
                "trigger_source": trigger_source,
                "trigger_context": trigger_context,
            },
        )
        await self.event_bus.publish(
            diagnosis_id=state.diagnosis_id,
            event="diagnosis_created",
            stage="workflow",
            status=state.status.value,
            message="诊断任务已创建",
            payload={"trigger_source": trigger_source},
        )
        return state

    async def run(self, diagnosis_id: str) -> DiagnosisState:
        state = await self.store.get(diagnosis_id)
        return await self._run(state)

    async def add_human_input(self, diagnosis_id: str, content: str) -> DiagnosisState:
        state = await self.store.get(diagnosis_id)
        state.human_inputs.append(content)
        state.need_user_input = []
        await self.store.save(state)
        return await self._run(state)

    async def get(self, diagnosis_id: str) -> DiagnosisState:
        return await self.store.get(diagnosis_id)

    async def _run(self, state: DiagnosisState) -> DiagnosisState:
        state.status = DiagnosisStatus.RUNNING
        state.updated_at = utc_now().isoformat()
        await self.store.save(state)
        await self.event_bus.publish(
            diagnosis_id=state.diagnosis_id,
            event="diagnosis_started",
            stage="workflow",
            status=state.status.value,
            message="诊断工作流开始执行",
        )

        try:
            state = await self.agents.run(
                state=state,
                data_source=self.data_source,
                low_confidence_threshold=self.low_confidence_threshold,
                event_bus=self.event_bus,
            )
        except (LLMConfigurationError, LLMRequestError, LLMResponseError) as exc:
            state.status = DiagnosisStatus.FAILED
            state.errors.append(
                RuntimeErrorInfo(stage="llm", message=str(exc), recoverable=isinstance(exc, LLMRequestError))
            )
        except Exception as exc:
            state.status = DiagnosisStatus.FAILED
            state.errors.append(RuntimeErrorInfo(stage="workflow", message=str(exc), recoverable=False))

        state.updated_at = utc_now().isoformat()
        await self.store.save(state)
        await self.event_bus.publish(
            diagnosis_id=state.diagnosis_id,
            event="diagnosis_finished",
            stage="workflow",
            status=state.status.value,
            message=f"诊断工作流结束，状态：{state.status.value}",
            payload={"errors": [error.model_dump(mode="json") for error in state.errors]},
        )
        return state


def _session_title(fault_description: str, fallback: str) -> str:
    title = " ".join(fault_description.split())
    if not title:
        return fallback
    return title[:120]
