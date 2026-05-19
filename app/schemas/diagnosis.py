from enum import Enum

from pydantic import BaseModel, Field

from app.schemas.agents import ErrorAnalysisOutput, PlanningOutput, RootCauseOutput, SlowSqlAnalysisOutput
from app.schemas.common import RuntimeErrorInfo, utc_now
from app.schemas.data import CollectedData


class DiagnosisStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    NEED_USER_INPUT = "need_user_input"
    COMPLETED = "completed"
    FAILED = "failed"


class DiagnosisCreate(BaseModel):
    fault_description: str = Field(min_length=3, max_length=4000)
    service_hint: str | None = Field(default=None, max_length=200)


class HumanInputCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class DiagnosisState(BaseModel):
    diagnosis_id: str
    status: DiagnosisStatus
    fault_description: str
    service_hint: str | None = None
    created_at: str = Field(default_factory=lambda: utc_now().isoformat())
    updated_at: str = Field(default_factory=lambda: utc_now().isoformat())
    human_inputs: list[str] = Field(default_factory=list)
    need_user_input: list[str] = Field(default_factory=list)
    collected_data: CollectedData | None = None
    planning: PlanningOutput | None = None
    error_analysis: ErrorAnalysisOutput | None = None
    slow_sql_analysis: SlowSqlAnalysisOutput | None = None
    root_cause: RootCauseOutput | None = None
    errors: list[RuntimeErrorInfo] = Field(default_factory=list)


class DiagnosisResponse(BaseModel):
    diagnosis: DiagnosisState

