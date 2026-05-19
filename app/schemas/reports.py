from pydantic import BaseModel

from app.schemas.diagnosis import DiagnosisState


class ReportResponse(BaseModel):
    diagnosis_id: str
    report: DiagnosisState

