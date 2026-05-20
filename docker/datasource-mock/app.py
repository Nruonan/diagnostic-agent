import os
from datetime import datetime, timezone
from typing import Any

import httpx
import pymysql
from fastapi import FastAPI, Query


app = FastAPI(title="Diagnostic Datasource Bridge", version="0.2.0")

ELASTICSEARCH_URL = os.getenv("ELASTICSEARCH_URL", "http://elasticsearch:9200").rstrip("/")
XXL_JOB_MYSQL_HOST = os.getenv("XXL_JOB_MYSQL_HOST", "xxl-job-mysql")
XXL_JOB_MYSQL_PORT = int(os.getenv("XXL_JOB_MYSQL_PORT", "3306"))
XXL_JOB_MYSQL_DATABASE = os.getenv("XXL_JOB_MYSQL_DATABASE", "xxl_job")
XXL_JOB_MYSQL_USER = os.getenv("XXL_JOB_MYSQL_USER", "xxl_job")
XXL_JOB_MYSQL_PASSWORD = os.getenv("XXL_JOB_MYSQL_PASSWORD", "xxl_job")


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "mode": "live-bridge",
        "elasticsearch_url": ELASTICSEARCH_URL,
        "xxl_job_mysql_host": XXL_JOB_MYSQL_HOST,
    }


@app.get("/elk")
async def elk(
    fault_description: str = Query(min_length=1),
    service_hint: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    hits = await _search_elasticsearch("app-logs-*,logs-*,mysql-slow-query-*", service_hint)
    return {"items": [_hit_to_log(hit) for hit in hits]}


@app.get("/slow-query")
async def slow_query(
    fault_description: str = Query(min_length=1),
    service_hint: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    hits = await _search_elasticsearch("mysql-slow-query-*", service_hint)
    return {"items": [_hit_to_slow_query(hit) for hit in hits if _hit_to_slow_query(hit)]}


@app.get("/xxl-job")
async def xxl_job(
    fault_description: str = Query(min_length=1),
    service_hint: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    return {"items": _fetch_xxl_job_failures(service_hint)}


@app.get("/trace")
async def trace(
    fault_description: str = Query(min_length=1),
    service_hint: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    hits = await _search_elasticsearch("traces-*,apm-*-transaction*,apm-*-span*", service_hint)
    return {"items": [_hit_to_trace(hit) for hit in hits if _hit_to_trace(hit)]}


@app.get("/git-code")
async def git_code(
    fault_description: str = Query(min_length=1),
    service_hint: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    return {"items": []}


async def _search_elasticsearch(index: str, service_hint: str | None, size: int = 25) -> list[dict[str, Any]]:
    query: dict[str, Any] = {"match_all": {}}
    if service_hint:
        query = {
            "multi_match": {
                "query": service_hint,
                "fields": ["service^3", "service_name^3", "app", "host", "message", "trace_id"],
                "lenient": True,
            }
        }

    body = {
        "size": size,
        "query": query,
        "sort": [{"@timestamp": {"order": "desc", "unmapped_type": "date"}}],
    }
    url = f"{ELASTICSEARCH_URL}/{index}/_search"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, params={"ignore_unavailable": "true"}, json=body)
        response.raise_for_status()
        payload = response.json()
    return payload.get("hits", {}).get("hits", [])


def _source(hit: dict[str, Any]) -> dict[str, Any]:
    source = hit.get("_source")
    return source if isinstance(source, dict) else {}


def _timestamp(value: Any = None) -> str:
    if value:
        return str(value)
    return datetime.now(timezone.utc).isoformat()


def _hit_to_log(hit: dict[str, Any]) -> dict[str, Any]:
    source = _source(hit)
    query_time = _float_value(source.get("query_time"))
    sql = source.get("sql") or source.get("query")
    message = source.get("message")
    if not message and sql:
        message = f"Slow query detected: {sql}"
    return {
        "timestamp": _timestamp(source.get("@timestamp") or source.get("timestamp")),
        "service": str(source.get("service") or source.get("service_name") or source.get("app") or "elasticsearch"),
        "level": str(source.get("level") or ("WARN" if query_time else "INFO")),
        "message": str(message or f"Elasticsearch document {hit.get('_id', '')} matched diagnostic query"),
        "trace_id": source.get("trace_id"),
        "error_type": source.get("error_type") or ("SlowQuery" if query_time else None),
        "stack_trace": source.get("stack_trace"),
    }


def _hit_to_slow_query(hit: dict[str, Any]) -> dict[str, Any] | None:
    source = _source(hit)
    sql = source.get("sql") or source.get("query")
    query_time = _float_value(source.get("query_time"))
    exec_time_ms = _int_value(source.get("exec_time_ms"))
    if not sql and not query_time and not exec_time_ms:
        return None
    return {
        "timestamp": _timestamp(source.get("@timestamp") or source.get("timestamp")),
        "service": str(source.get("service") or source.get("service_name") or "mysql"),
        "database": str(source.get("database") or source.get("db") or "mysql"),
        "query": str(sql or "unknown"),
        "exec_time_ms": exec_time_ms or int((query_time or 0) * 1000),
        "rows_examined": _int_value(source.get("rows_examined")) or 0,
        "lock_time_ms": _int_value(source.get("lock_time_ms")) or 0,
        "trace_id": source.get("trace_id"),
    }


def _hit_to_trace(hit: dict[str, Any]) -> dict[str, Any] | None:
    source = _source(hit)
    trace_id = source.get("trace_id") or source.get("trace.id")
    span_id = source.get("span_id") or source.get("span.id") or hit.get("_id")
    if not trace_id or not span_id:
        return None
    return {
        "trace_id": str(trace_id),
        "span_id": str(span_id),
        "parent_span_id": source.get("parent_span_id") or source.get("parent.id"),
        "service": str(source.get("service") or source.get("service.name") or "unknown"),
        "operation": str(source.get("operation") or source.get("transaction.name") or source.get("name") or "unknown"),
        "start_time": _timestamp(source.get("@timestamp") or source.get("start_time")),
        "duration_ms": _int_value(source.get("duration_ms") or source.get("event.duration")) or 0,
        "status": str(source.get("status") or source.get("event.outcome") or "unknown"),
    }


def _fetch_xxl_job_failures(service_hint: str | None) -> list[dict[str, Any]]:
    sql = """
        SELECT
            l.job_id,
            l.job_group,
            l.executor_address,
            l.executor_handler,
            l.trigger_time,
            l.handle_time,
            l.handle_code,
            l.handle_msg,
            i.job_desc
        FROM xxl_job_log l
        LEFT JOIN xxl_job_info i ON i.id = l.job_id
        WHERE l.handle_code <> 200
        ORDER BY COALESCE(l.handle_time, l.trigger_time) DESC
        LIMIT 25
    """
    connection = pymysql.connect(
        host=XXL_JOB_MYSQL_HOST,
        port=XXL_JOB_MYSQL_PORT,
        user=XXL_JOB_MYSQL_USER,
        password=XXL_JOB_MYSQL_PASSWORD,
        database=XXL_JOB_MYSQL_DATABASE,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5,
        read_timeout=10,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql)
            rows = cursor.fetchall()
    finally:
        connection.close()

    items = [_xxl_row_to_job(row) for row in rows]
    if service_hint:
        normalized = service_hint.strip().lower()
        filtered = [
            item
            for item in items
            if normalized in item["job_name"].lower()
            or normalized in item["message"].lower()
            or normalized in str(item.get("trace_id") or "").lower()
        ]
        return filtered or items
    return items


def _xxl_row_to_job(row: dict[str, Any]) -> dict[str, Any]:
    timestamp = row.get("handle_time") or row.get("trigger_time")
    job_name = row.get("job_desc") or row.get("executor_handler") or f"xxl-job-{row.get('job_id')}"
    return {
        "timestamp": _timestamp(timestamp.isoformat() if hasattr(timestamp, "isoformat") else timestamp),
        "job_name": str(job_name),
        "status": "FAILED",
        "duration_ms": 0,
        "message": str(row.get("handle_msg") or f"XXL-Job failed with handle_code={row.get('handle_code')}"),
        "trace_id": f"xxl-job-{row.get('job_id')}-{row.get('job_group')}",
    }


def _int_value(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _float_value(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
