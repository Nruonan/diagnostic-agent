import json
from pathlib import Path

from fastapi import HTTPException

from app.schemas.diagnosis import DiagnosisState


class JsonDiagnosisStore:
    def __init__(self, runtime_dir: Path):
        self.base_dir = runtime_dir / "diagnoses"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    async def save(self, state: DiagnosisState) -> None:
        path = self._path(state.diagnosis_id)
        with path.open("w", encoding="utf-8") as file:
            json.dump(state.model_dump(mode="json"), file, ensure_ascii=False, indent=2)

    async def get(self, diagnosis_id: str) -> DiagnosisState:
        path = self._path(diagnosis_id)
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"diagnosis {diagnosis_id} not found")
        with path.open("r", encoding="utf-8") as file:
            return DiagnosisState.model_validate(json.load(file))

    def _path(self, diagnosis_id: str) -> Path:
        safe_id = diagnosis_id.replace("/", "").replace("\\", "")
        return self.base_dir / f"{safe_id}.json"

