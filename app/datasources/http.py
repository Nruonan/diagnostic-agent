from collections.abc import Callable
from typing import Any

import httpx
from pydantic import ValidationError

from app.config import Settings
from app.schemas.common import DataSourceError
from app.schemas.data import AlertRecord, CodeSnippet, CollectedData, JobRecord, LogRecord, MetricRecord, SlowQueryRecord, TraceSpan


class HttpDataSource:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def collect(self, fault_description: str, service_hint: str | None = None) -> CollectedData:
        error_context, sql_context, root_context = await self._collect_contexts(fault_description, service_hint)
        return self._merge_contexts(error_context, sql_context, root_context)

    async def collect_error_context(self, fault_description: str, service_hint: str | None = None) -> CollectedData:
        params = {"fault_description": fault_description}
        if service_hint:
            params["service_hint"] = service_hint

        collected = CollectedData()
        async with httpx.AsyncClient(timeout=30.0) as client:
            collected.logs = await self._fetch_items(
                client,
                "elk",
                self.settings.elk_api_url,
                params,
                LogRecord.model_validate,
                collected,
            )
            collected.jobs = await self._fetch_items(
                client,
                "xxl_job",
                self.settings.xxl_job_api_url,
                params,
                JobRecord.model_validate,
                collected,
            )
            collected.zabbix_events = await self._fetch_items(
                client,
                "zabbix",
                self.settings.zabbix_api_url,
                params,
                AlertRecord.model_validate,
                collected,
                required=False,
            )
        return collected

    async def collect_sql_context(self, fault_description: str, service_hint: str | None = None) -> CollectedData:
        params = {"fault_description": fault_description}
        if service_hint:
            params["service_hint"] = service_hint

        collected = CollectedData()
        async with httpx.AsyncClient(timeout=30.0) as client:
            collected.slow_queries = await self._fetch_items(
                client,
                "slow_query",
                self.settings.slow_query_api_url,
                params,
                SlowQueryRecord.model_validate,
                collected,
            )
            collected.metrics = await self._fetch_items(
                client,
                "prometheus",
                self.settings.prometheus_api_url,
                params,
                MetricRecord.model_validate,
                collected,
                required=False,
            )
        return collected

    async def collect_root_context(self, fault_description: str, service_hint: str | None = None) -> CollectedData:
        params = {"fault_description": fault_description}
        if service_hint:
            params["service_hint"] = service_hint

        collected = CollectedData()
        async with httpx.AsyncClient(timeout=30.0) as client:
            collected.traces = await self._fetch_items(
                client,
                "trace",
                self.settings.trace_api_url,
                params,
                TraceSpan.model_validate,
                collected,
            )
            collected.code_snippets = await self._fetch_items(
                client,
                "git_code",
                self.settings.git_code_api_url,
                params,
                CodeSnippet.model_validate,
                collected,
            )
        return collected

    async def _collect_contexts(
        self,
        fault_description: str,
        service_hint: str | None,
    ) -> tuple[CollectedData, CollectedData, CollectedData]:
        return (
            await self.collect_error_context(fault_description, service_hint),
            await self.collect_sql_context(fault_description, service_hint),
            await self.collect_root_context(fault_description, service_hint),
        )

    def _merge_contexts(self, *contexts: CollectedData) -> CollectedData:
        collected = CollectedData()
        for context in contexts:
            collected.logs.extend(context.logs)
            collected.jobs.extend(context.jobs)
            collected.zabbix_events.extend(context.zabbix_events)
            collected.slow_queries.extend(context.slow_queries)
            collected.metrics.extend(context.metrics)
            collected.traces.extend(context.traces)
            collected.code_snippets.extend(context.code_snippets)
            collected.source_errors.extend(context.source_errors)
        return collected

    async def _fetch_items(
        self,
        client: httpx.AsyncClient,
        source: str,
        url: str,
        params: dict[str, str],
        validator: Callable[[Any], Any],
        collected: CollectedData,
        required: bool = True,
    ) -> list[Any]:
        if not url:
            if required:
                collected.source_errors.append(DataSourceError(source=source, message=f"{source} URL is not configured"))
            return []

        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            collected.source_errors.append(DataSourceError(source=source, message=str(exc)))
            return []
        except ValueError as exc:
            collected.source_errors.append(DataSourceError(source=source, message=f"invalid JSON: {exc}"))
            return []

        raw_items = self._extract_items(payload, source)
        items = []
        for index, raw_item in enumerate(raw_items):
            try:
                items.append(validator(raw_item))
            except ValidationError as exc:
                collected.source_errors.append(
                    DataSourceError(
                        source=source,
                        message=f"item {index} failed validation",
                        detail={"errors": exc.errors()},
                    )
                )
        return items

    def _extract_items(self, payload: Any, source: str) -> list[Any]:
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("items", "data", source, "results"):
                value = payload.get(key)
                if isinstance(value, list):
                    return value
        return []
