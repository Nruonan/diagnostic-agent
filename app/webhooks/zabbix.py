from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Response
from pydantic import BaseModel, Field

from app.api.deps import get_engine, get_settings_from_app
from app.config import Settings
from app.schemas.alerts import AlertEventCreate
from app.webhooks._dedup import DeduplicationService, get_dedup_service
from app.webhooks._shared import (
    WebhookAcceptedResponse,
    accepted_response,
    create_webhook_diagnosis,
    ensure_dashscope_configured,
    first_non_empty,
    normalize_severity,
    stringify_mapping,
    truncate,
)
from app.workflow import WorkflowEngine

router = APIRouter()


class ZabbixWebhookPayload(BaseModel):
    event_id: str = Field(min_length=1, max_length=200)
    host: str = Field(min_length=1, max_length=200)
    trigger_name: str = Field(min_length=1, max_length=300)
    severity: str | int = "high"
    status: str = Field(default="PROBLEM", max_length=80)
    description: str | None = Field(default=None, max_length=4000)
    tags: dict[str, Any] | list[dict[str, Any]] | None = None
    items: list[dict[str, Any]] | None = None


@router.post("/zabbix", response_model=WebhookAcceptedResponse)
async def ingest_zabbix(
    payload: ZabbixWebhookPayload,
    response: Response,
    background_tasks: BackgroundTasks,
    engine: WorkflowEngine = Depends(get_engine),
    settings: Settings = Depends(get_settings_from_app),
    dedup: DeduplicationService = Depends(get_dedup_service),
) -> WebhookAcceptedResponse:
    if _is_resolved(payload.status):
        return accepted_response(response, [])

    ensure_dashscope_configured(settings)
    fingerprint = dedup.fingerprint("zabbix", [payload.event_id, payload.host, payload.trigger_name])
    if await dedup.is_duplicate(fingerprint):
        return accepted_response(response, [], deduplicated=1)

    labels = stringify_mapping(_tags_to_mapping(payload.tags))
    labels.setdefault("host", payload.host)
    alert = AlertEventCreate(
        source="zabbix",
        title=truncate(payload.trigger_name, 200),
        severity=normalize_severity(payload.severity),
        service_hint=payload.host,
        description=payload.description,
        labels=labels,
        metadata={
            "event_id": payload.event_id,
            "status": payload.status,
            "items": payload.items or [],
        },
    )
    diagnosis_id = await create_webhook_diagnosis(alert, background_tasks, engine, settings)
    return accepted_response(response, [diagnosis_id])


def _is_resolved(status: str) -> bool:
    return status.strip().upper() in {"0", "OK", "RESOLVED"}


def _tags_to_mapping(tags: dict[str, Any] | list[dict[str, Any]] | None) -> dict[str, Any]:
    if isinstance(tags, dict):
        return tags
    if not tags:
        return {}
    result: dict[str, Any] = {}
    for tag in tags:
        key = first_non_empty(tag.get("tag"), tag.get("key"), tag.get("name"))
        value = first_non_empty(tag.get("value"), tag.get("val"))
        if key and value is not None:
            result[key] = value
    return result
