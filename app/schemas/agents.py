from pydantic import BaseModel, Field


class TaskItem(BaseModel):
    id: int
    name: str
    priority: int = Field(ge=1, le=5)
    sources: list[str]
    dependencies: list[int] = Field(default_factory=list)
    reason: str


class PlanningOutput(BaseModel):
    tasks: list[TaskItem]
    estimated_time: str
    focus_services: list[str] = Field(default_factory=list)


class ErrorItem(BaseModel):
    timestamp: str
    error_type: str
    service: str
    message: str
    trace_id: str | None = None
    evidence: list[str] = Field(default_factory=list)


class ErrorAnalysisOutput(BaseModel):
    errors: list[ErrorItem]
    timeline: list[str]
    suspects: list[str]
    summary: str


class SlowQueryFinding(BaseModel):
    query: str
    service: str
    exec_time_ms: int = Field(ge=0)
    rows_examined: int = Field(ge=0)
    issues: list[str]
    optimizations: list[str]
    trace_id: str | None = None


class SlowSqlAnalysisOutput(BaseModel):
    slow_queries: list[SlowQueryFinding]
    optimizations: list[str]
    summary: str


class RootCauseOutput(BaseModel):
    root_cause: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str]
    fix_steps: list[str]
    mermaid: str
    missing_information: list[str] = Field(default_factory=list)

