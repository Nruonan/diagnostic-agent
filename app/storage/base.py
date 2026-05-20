from typing import Any, Protocol

from app.events import WorkflowEvent
from app.schemas.diagnosis import DiagnosisState
from app.schemas.sessions import DiagnosisSession, UserRecord


class DiagnosisStore(Protocol):
    async def initialize(self) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError

    async def save(self, state: DiagnosisState) -> None:
        raise NotImplementedError

    async def get(self, diagnosis_id: str) -> DiagnosisState:
        raise NotImplementedError

    async def ensure_default_user(self) -> UserRecord:
        raise NotImplementedError

    async def create_session(
        self,
        session_id: str,
        diagnosis_id: str,
        title: str,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DiagnosisSession:
        raise NotImplementedError

    async def get_session(self, session_id: str) -> DiagnosisSession:
        raise NotImplementedError

    async def list_sessions(self, user_id: str | None = None, limit: int = 50) -> list[DiagnosisSession]:
        raise NotImplementedError

    async def save_event(self, event: WorkflowEvent) -> WorkflowEvent:
        raise NotImplementedError

    async def list_events(self, diagnosis_id: str, after_event_id: int | None = None) -> list[WorkflowEvent]:
        raise NotImplementedError
