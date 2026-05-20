from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Response
from pydantic import BaseModel, ConfigDict, Field

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


class PrometheusAlert(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    status: str = "firing"
    labels: dict[str, Any] = Field(default_factory=dict)
    annotations: dict[str, Any] = Field(default_factory=dict)
    starts_at: str | None = Field(default=None, alias="startsAt")
    ends_at: str | None = Field(default=None, alias="endsAt")
    generator_url: str | None = Field(default=None, alias="generatorURL")
    fingerprint: str | None = None


class PrometheusWebhookPayload(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    status: str = "firing"
    alerts: list[PrometheusAlert] = Field(default_factory=list)
    group_labels: dict[str, Any] = Field(default_factory=dict, alias="groupLabels")
    common_labels: dict[str, Any] = Field(default_factory=dict, alias="commonLabels")
    common_annotations: dict[str, Any] = Field(default_factory=dict, alias="commonAnnotations")
    external_url: str | None = Field(default=None, alias="externalURL")


@router.post("/prometheus", response_model=WebhookAcceptedResponse)
async def ingest_prometheus(
    payload: PrometheusWebhookPayload,
    response: Response,
    background_tasks: BackgroundTasks,
    engine: WorkflowEngine = Depends(get_engine),
    settings: Settings = Depends(get_settings_from_app),
    dedup: DeduplicationService = Depends(get_dedup_service),
) -> WebhookAcceptedResponse:
    diagnosis_ids: list[str] = []
    deduplicated = 0
    firing_alerts = [alert for alert in payload.alerts if alert.status.strip().lower() == "firing"]
    if not firing_alerts:
        return accepted_response(response, [])

    ensure_dashscope_configured(settings)
    for alert in firing_alerts:
        labels = stringify_mapping(alert.labels)
        annotations = stringify_mapping(alert.annotations)
        title = first_non_empty(labels.get("alertname"), annotations.get("summary"), "Prometheus alert")
        service_hint = first_non_empty(
            labels.get("service"),
            labels.get("service_name"),
            labels.get("app"),
            labels.get("application"),
            labels.get("job"),
        )
        target = first_non_empty(labels.get("instance"), labels.get("pod"), service_hint, alert.fingerprint)
        fingerprint = dedup.fingerprint("prometheus", [title, target])
        if await dedup.is_duplicate(fingerprint):
            deduplicated += 1
            continue

        description = _prometheus_description(annotations, alert.generator_url)
        event = AlertEventCreate(
            source="prometheus",
            title=truncate(title, 200),
            severity=normalize_severity(first_non_empty(labels.get("severity"), labels.get("priority")), "high"),
            service_hint=service_hint,
            description=description,
            triggered_at=alert.starts_at,
            labels=labels,
            annotations=annotations,
            metadata={
                "status": alert.status,
                "ends_at": alert.ends_at,
                "fingerprint": alert.fingerprint,
                "generator_url": alert.generator_url,
                "group_labels": payload.group_labels,
                "common_labels": payload.common_labels,
                "common_annotations": payload.common_annotations,
                "external_url": payload.external_url,
            },
        )
        diagnosis_ids.append(await create_webhook_diagnosis(event, background_tasks, engine, settings))

    return accepted_response(response, diagnosis_ids, deduplicated)


def _prometheus_description(annotations: dict[str, str], generator_url: str | None) -> str | None:
    parts = [
        first_non_empty(annotations.get("description"), annotations.get("message")),
        first_non_empty(annotations.get("summary")),
    ]
    if generator_url:
        parts.append(f"Generator URL: {generator_url}")
    text = "\n".join(part for part in parts if part)
    return truncate(text, 4000) if text else None
