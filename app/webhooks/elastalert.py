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


class ElastAlertWebhookPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    rule_name: str | None = Field(default=None, max_length=300)
    match_body: dict[str, Any] = Field(default_factory=dict)
    alert_time: str | None = Field(default=None, max_length=80)
    num_matches: int | None = None
    alert_info: dict[str, Any] = Field(default_factory=dict)


@router.post("/elastalert", response_model=WebhookAcceptedResponse)
async def ingest_elastalert(
    payload: ElastAlertWebhookPayload,
    response: Response,
    background_tasks: BackgroundTasks,
    engine: WorkflowEngine = Depends(get_engine),
    settings: Settings = Depends(get_settings_from_app),
    dedup: DeduplicationService = Depends(get_dedup_service),
) -> WebhookAcceptedResponse:
    rule_name = first_non_empty(payload.rule_name, _extra(payload, "rule_name"), _extra(payload, "rule"), "ElastAlert alert")
    match_body = payload.match_body or _match_from_extra(payload)
    ensure_dashscope_configured(settings)
    fingerprint = dedup.fingerprint("elastalert", [rule_name, dedup.fingerprint("elastalert-match", match_body)])
    if await dedup.is_duplicate(fingerprint):
        return accepted_response(response, [], deduplicated=1)

    labels = stringify_mapping(_extract_labels(match_body))
    service_hint = first_non_empty(
        labels.get("service"),
        labels.get("service_name"),
        labels.get("app"),
        labels.get("application"),
        labels.get("job"),
        match_body.get("service"),
    )
    mysql_slow_query = "mysql" in rule_name.lower() or "slow" in rule_name.lower()
    title = f"MySQL slow query: {rule_name}" if mysql_slow_query else rule_name
    alert = AlertEventCreate(
        source="elastalert",
        title=truncate(title, 200),
        severity=normalize_severity(first_non_empty(payload.alert_info.get("severity"), match_body.get("severity")), "high"),
        service_hint=service_hint,
        description=truncate(_elastalert_description(rule_name, payload.num_matches, match_body), 4000),
        triggered_at=first_non_empty(payload.alert_time, match_body.get("@timestamp"), match_body.get("timestamp")),
        labels=labels,
        metadata={
            "rule_name": rule_name,
            "num_matches": payload.num_matches,
            "alert_info": payload.alert_info,
            "match_body": match_body,
            "mysql_slow_query": mysql_slow_query,
        },
    )
    diagnosis_id = await create_webhook_diagnosis(alert, background_tasks, engine, settings)
    return accepted_response(response, [diagnosis_id])


def _extra(payload: ElastAlertWebhookPayload, key: str) -> Any:
    return (payload.model_extra or {}).get(key)


def _match_from_extra(payload: ElastAlertWebhookPayload) -> dict[str, Any]:
    ignored = {"rule_name", "match_body", "alert_time", "num_matches", "alert_info"}
    return {key: value for key, value in (payload.model_extra or {}).items() if key not in ignored}


def _extract_labels(match_body: dict[str, Any]) -> dict[str, Any]:
    labels = match_body.get("labels")
    if isinstance(labels, dict):
        return labels
    return {
        key: value
        for key, value in match_body.items()
        if key in {"service", "service_name", "app", "application", "job", "host", "instance", "pod"}
    }


def _elastalert_description(rule_name: str, num_matches: int | None, match_body: dict[str, Any]) -> str:
    parts = [f"ElastAlert rule: {rule_name}"]
    if num_matches is not None:
        parts.append(f"Matched documents: {num_matches}")
    if match_body:
        parts.append(f"Match body: {match_body}")
    return "\n".join(parts)
