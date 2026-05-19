import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query


app = FastAPI(title="Diagnostic Datasource Mock", version="0.1.0")
SAMPLE_DIR = Path(__file__).resolve().parent / "sample_data"


def load_items(filename: str) -> list[dict[str, Any]]:
    path = SAMPLE_DIR / filename
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a JSON array")
    return data


def filter_by_service(items: list[dict[str, Any]], service_hint: str | None) -> list[dict[str, Any]]:
    if not service_hint:
        return items

    normalized_hint = service_hint.strip().lower()
    if not normalized_hint:
        return items

    filtered = [
        item
        for item in items
        if normalized_hint in str(item.get("service", "")).lower()
        or normalized_hint in str(item.get("job_name", "")).lower()
        or normalized_hint in str(item.get("repository", "")).lower()
        or normalized_hint in str(item.get("file_path", "")).lower()
    ]
    return filtered or items


def response_from_sample(filename: str, service_hint: str | None) -> dict[str, list[dict[str, Any]]]:
    return {"items": filter_by_service(load_items(filename), service_hint)}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "mode": "mock"}


@app.get("/elk")
async def elk(
    fault_description: str = Query(min_length=1),
    service_hint: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    return response_from_sample("logs.json", service_hint)


@app.get("/xxl-job")
async def xxl_job(
    fault_description: str = Query(min_length=1),
    service_hint: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    return response_from_sample("xxl_jobs.json", service_hint)


@app.get("/slow-query")
async def slow_query(
    fault_description: str = Query(min_length=1),
    service_hint: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    return response_from_sample("slow_queries.json", service_hint)


@app.get("/trace")
async def trace(
    fault_description: str = Query(min_length=1),
    service_hint: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    return response_from_sample("traces.json", service_hint)


@app.get("/git-code")
async def git_code(
    fault_description: str = Query(min_length=1),
    service_hint: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    return response_from_sample("code_snippets.json", service_hint)
