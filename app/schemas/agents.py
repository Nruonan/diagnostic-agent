import json
from typing import Any

from pydantic import BaseModel, Field, field_validator


def normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [text for item in value if (text := stringify_list_item(item))]
    text = stringify_list_item(value)
    return [text] if text else []


def stringify_list_item(value: Any) -> str:
    if isinstance(value, dict):
        if "timestamp" in value and "description" in value:
            return f"{value['timestamp']} - {value['description']}"
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


class TaskItem(BaseModel):
    id: str
    name: str
    priority: int = Field(ge=1, le=5)
    sources: list[str]
    dependencies: list[str] = Field(default_factory=list)
    reason: str

    @field_validator("id", mode="before")
    @classmethod
    def normalize_id(cls, value: Any) -> str:
        return str(value)

    @field_validator("dependencies", mode="before")
    @classmethod
    def normalize_dependencies(cls, value: Any) -> list[str]:
        return normalize_string_list(value)


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

    @field_validator("evidence", mode="before")
    @classmethod
    def normalize_evidence(cls, value: Any) -> Any:
        return normalize_string_list(value)


class ErrorAnalysisOutput(BaseModel):
    errors: list[ErrorItem]
    timeline: list[str]
    suspects: list[str]
    summary: str

    @field_validator("timeline", "suspects", mode="before")
    @classmethod
    def normalize_string_fields(cls, value: Any) -> list[str]:
        return normalize_string_list(value)


class SlowQueryFinding(BaseModel):
    query: str
    service: str
    exec_time_ms: int = Field(ge=0)
    rows_examined: int = Field(ge=0)
    issues: list[str]
    optimizations: list[str]
    trace_id: str | None = None

    @field_validator("issues", "optimizations", mode="before")
    @classmethod
    def normalize_string_fields(cls, value: Any) -> list[str]:
        return normalize_string_list(value)


class SlowSqlAnalysisOutput(BaseModel):
    slow_queries: list[SlowQueryFinding]
    optimizations: list[str]
    summary: str

    @field_validator("optimizations", mode="before")
    @classmethod
    def normalize_optimizations(cls, value: Any) -> list[str]:
        return normalize_string_list(value)


class RootCauseOutput(BaseModel):
    root_cause: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str]
    fix_steps: list[str]
    mermaid: str
    missing_information: list[str] = Field(default_factory=list)

    @field_validator("evidence", "fix_steps", "missing_information", mode="before")
    @classmethod
    def normalize_string_fields(cls, value: Any) -> list[str]:
        return normalize_string_list(value)
