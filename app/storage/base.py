from typing import Protocol

from app.schemas.diagnosis import DiagnosisState


class DiagnosisStore(Protocol):
    async def initialize(self) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError

    async def save(self, state: DiagnosisState) -> None:
        raise NotImplementedError

    async def get(self, diagnosis_id: str) -> DiagnosisState:
        raise NotImplementedError
