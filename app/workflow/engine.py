from typing import Any
from uuid import uuid4

from app.agents import MainAgent
from app.datasources import DataSource
from app.llm import LLMConfigurationError, LLMRequestError, LLMResponseError
from app.schemas.common import RuntimeErrorInfo, utc_now
from app.schemas.diagnosis import DiagnosisCreate, DiagnosisState, DiagnosisStatus
from app.storage.json_store import JsonDiagnosisStore


class WorkflowEngine:
    def __init__(
        self,
        agents: MainAgent,
        data_source: DataSource,
        store: JsonDiagnosisStore,
        low_confidence_threshold: float,
    ):
        self.agents = agents
        self.data_source = data_source
        self.store = store
        self.low_confidence_threshold = low_confidence_threshold

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

        try:
            state = await self.agents.run(
                state=state,
                data_source=self.data_source,
                low_confidence_threshold=self.low_confidence_threshold,
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
        return state
