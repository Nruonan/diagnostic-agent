from collections.abc import Mapping
from typing import Any

from fastapi import BackgroundTasks, HTTPException, Response, status
from pydantic import BaseModel

from app.config import Settings
from app.schemas.alerts import AlertEventCreate
from app.workflow import WorkflowEngine


class WebhookAcceptedResponse(BaseModel):
    accepted: int
    deduplicated: int
    diagnosis_ids: list[str]


def normalize_severity(value: Any, default: str = "high") -> str:
    severity = str(value or default).strip().lower()
    mapping = {
        "0": "info",
        "1": "info",
        "2": "low",
        "3": "medium",
        "4": "high",
        "5": "critical",
        "not classified": "info",
        "information": "info",
        "info": "info",
        "warning": "low",
        "average": "medium",
        "medium": "medium",
        "high": "high",
        "disaster": "critical",
        "critical": "critical",
        "error": "high",
        "fatal": "critical",
    }
    return mapping.get(severity, default)


def stringify_mapping(data: Mapping[str, Any] | None) -> dict[str, str]:
    if not data:
        return {}
    return {str(key): _stringify(value) for key, value in data.items() if value is not None}


def first_non_empty(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def truncate(value: str, limit: int) -> str:
    return value if len(value) <= limit else f"{value[: limit - 3]}..."


def ensure_dashscope_configured(settings: Settings) -> None:
    if not settings.dashscope_configured():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="DASHSCOPE_API_KEY is not configured")


async def create_webhook_diagnosis(
    alert: AlertEventCreate,
    background_tasks: BackgroundTasks,
    engine: WorkflowEngine,
    settings: Settings,
) -> str:
    ensure_dashscope_configured(settings)
    state = await engine.create(
        alert.to_diagnosis_create(),
        trigger_source="webhook",
        trigger_context=alert.model_dump(mode="json"),
    )
    background_tasks.add_task(engine.run, state.diagnosis_id)
    return state.diagnosis_id


def accepted_response(response: Response, diagnosis_ids: list[str], deduplicated: int = 0) -> WebhookAcceptedResponse:
    response.status_code = status.HTTP_202_ACCEPTED if diagnosis_ids else status.HTTP_200_OK
    return WebhookAcceptedResponse(
        accepted=len(diagnosis_ids),
        deduplicated=deduplicated,
        diagnosis_ids=diagnosis_ids,
    )


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list, tuple)):
        return truncate(str(value), 1000)
    return str(value)
