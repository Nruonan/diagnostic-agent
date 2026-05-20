from typing import Any

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Response

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


@router.post("/xxl-job")
async def ingest_xxl_job(
    response: Response,
    background_tasks: BackgroundTasks,
    payload: Any = Body(...),
    engine: WorkflowEngine = Depends(get_engine),
    settings: Settings = Depends(get_settings_from_app),
    dedup: DeduplicationService = Depends(get_dedup_service),
) -> dict[str, int] | WebhookAcceptedResponse:
    records = payload if isinstance(payload, list) else [payload]
    native_callback = isinstance(payload, list) or any(_has_native_callback_shape(record) for record in records)
    diagnosis_ids: list[str] = []
    deduplicated = 0
    failing_records = [
        record
        for record in records
        if isinstance(record, dict) and _int_value(record, "handle_code", "handleCode", "code") != 200
    ]
    if failing_records:
        ensure_dashscope_configured(settings)

    for record in failing_records:
        handle_code = _int_value(record, "handle_code", "handleCode", "code")
        fingerprint = dedup.fingerprint(
            "xxl-job",
            [
                first_non_empty(_value(record, "job_id", "jobId"), _value(record, "job_group", "jobGroup")),
                first_non_empty(_value(record, "job_group", "jobGroup")),
                first_non_empty(_value(record, "log_id", "logId"), _value(record, "logDateTim"), record),
            ],
        )
        if await dedup.is_duplicate(fingerprint):
            deduplicated += 1
            continue

        event = _to_alert_event(record, handle_code)
        diagnosis_ids.append(await create_webhook_diagnosis(event, background_tasks, engine, settings))

    if native_callback:
        response.status_code = 200
        return {"code": 200}
    return accepted_response(response, diagnosis_ids, deduplicated)


def _has_native_callback_shape(record: Any) -> bool:
    return isinstance(record, dict) and any(key in record for key in ("logId", "logDateTim", "handleCode", "handleMsg"))


def _to_alert_event(record: dict[str, Any], handle_code: int | None) -> AlertEventCreate:
    job_id = first_non_empty(_value(record, "job_id", "jobId"))
    job_group = first_non_empty(_value(record, "job_group", "jobGroup"))
    job_name = first_non_empty(
        _value(record, "job_name", "jobName"),
        _value(record, "job_desc", "jobDesc"),
        _value(record, "executor_handler", "executorHandler"),
        job_id,
        "XXL-Job failed",
    )
    service_hint = first_non_empty(
        _value(record, "service"),
        _value(record, "app"),
        _value(record, "executor_address", "executorAddress"),
        job_group,
    )
    labels = stringify_mapping(
        {
            "job_id": job_id,
            "job_group": job_group,
            "executor_address": _value(record, "executor_address", "executorAddress"),
            "executor_handler": _value(record, "executor_handler", "executorHandler"),
        }
    )
    message = first_non_empty(
        _value(record, "error_message", "errorMessage"),
        _value(record, "handle_msg", "handleMsg"),
        _value(record, "msg"),
        _value(record, "message"),
    )
    description_parts = [f"XXL-Job handle_code: {handle_code if handle_code is not None else 'unknown'}"]
    if message:
        description_parts.append(message)
    return AlertEventCreate(
        source="xxl-job",
        title=truncate(f"XXL-Job failure: {job_name}", 200),
        severity=normalize_severity(_value(record, "severity"), "high"),
        service_hint=service_hint,
        description=truncate("\n".join(description_parts), 4000),
        labels=labels,
        metadata={
            "job_id": job_id,
            "job_group": job_group,
            "log_id": first_non_empty(_value(record, "log_id", "logId")),
            "handle_code": handle_code,
            "raw": record,
        },
    )


def _value(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in record:
            return record[key]
    return None


def _int_value(record: dict[str, Any], *keys: str) -> int | None:
    value = _value(record, *keys)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
