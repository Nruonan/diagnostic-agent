from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.diagnosis import DiagnosisCreate


class AlertEventCreate(BaseModel):
    source: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=200)
    severity: Literal["critical", "high", "medium", "low", "info"] = "high"
    service_hint: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    triggered_at: str | None = Field(default=None, max_length=64)
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_diagnosis_create(self) -> DiagnosisCreate:
        parts = [
            f"告警来源：{self.source}",
            f"告警级别：{self.severity}",
            f"告警标题：{self.title}",
        ]
        if self.triggered_at:
            parts.append(f"触发时间：{self.triggered_at}")
        if self.description:
            parts.append(f"描述：{self.description}")
        if self.labels:
            parts.append(f"标签：{self.labels}")
        if self.annotations:
            parts.append(f"注解：{self.annotations}")
        if self.metadata:
            parts.append(f"元数据：{self.metadata}")
        fault_description = "\n".join(parts)
        if len(fault_description) > 4000:
            fault_description = f"{fault_description[:3997]}..."
        return DiagnosisCreate(
            fault_description=fault_description,
            service_hint=self._service_hint(),
        )

    def _service_hint(self) -> str | None:
        if self.service_hint:
            return self.service_hint
        for key in ("service", "service_name", "app", "application", "job"):
            value = self.labels.get(key)
            if value:
                return value[:200]
        return None
