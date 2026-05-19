from pydantic import BaseModel, Field

from app.schemas.common import DataSourceError


class LogRecord(BaseModel):
    timestamp: str
    service: str
    level: str
    message: str
    trace_id: str | None = None
    error_type: str | None = None
    stack_trace: str | None = None


class JobRecord(BaseModel):
    timestamp: str
    job_name: str
    status: str
    duration_ms: int = Field(ge=0)
    message: str
    trace_id: str | None = None


class SlowQueryRecord(BaseModel):
    timestamp: str
    service: str
    database: str
    query: str
    exec_time_ms: int = Field(ge=0)
    rows_examined: int = Field(ge=0)
    lock_time_ms: int = Field(default=0, ge=0)
    trace_id: str | None = None


class TraceSpan(BaseModel):
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    service: str
    operation: str
    start_time: str
    duration_ms: int = Field(ge=0)
    status: str


class CodeSnippet(BaseModel):
    repository: str
    file_path: str
    service: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    language: str
    content: str


class CollectedData(BaseModel):
    logs: list[LogRecord] = Field(default_factory=list)
    jobs: list[JobRecord] = Field(default_factory=list)
    slow_queries: list[SlowQueryRecord] = Field(default_factory=list)
    traces: list[TraceSpan] = Field(default_factory=list)
    code_snippets: list[CodeSnippet] = Field(default_factory=list)
    source_errors: list[DataSourceError] = Field(default_factory=list)

