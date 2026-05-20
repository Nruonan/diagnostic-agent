import json
from pathlib import Path
from typing import Any

from app.schemas.data import CodeSnippet, CollectedData, JobRecord, LogRecord, SlowQueryRecord, TraceSpan


class SampleDataSource:
    def __init__(self, sample_dir: Path):
        self.sample_dir = sample_dir

    async def collect(self, fault_description: str, service_hint: str | None = None) -> CollectedData:
        return self._merge_contexts(
            await self.collect_error_context(fault_description, service_hint),
            await self.collect_sql_context(fault_description, service_hint),
            await self.collect_root_context(fault_description, service_hint),
        )

    async def collect_error_context(self, fault_description: str, service_hint: str | None = None) -> CollectedData:
        return CollectedData(
            logs=[LogRecord.model_validate(item) for item in self._load_list("logs.json")],
            jobs=[JobRecord.model_validate(item) for item in self._load_list("xxl_jobs.json")],
        )

    async def collect_sql_context(self, fault_description: str, service_hint: str | None = None) -> CollectedData:
        return CollectedData(
            slow_queries=[SlowQueryRecord.model_validate(item) for item in self._load_list("slow_queries.json")],
        )

    async def collect_root_context(self, fault_description: str, service_hint: str | None = None) -> CollectedData:
        return CollectedData(
            traces=[TraceSpan.model_validate(item) for item in self._load_list("traces.json")],
            code_snippets=[CodeSnippet.model_validate(item) for item in self._load_list("code_snippets.json")],
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

    def _load_list(self, filename: str) -> list[dict[str, Any]]:
        path = self.sample_dir / filename
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, list):
            raise ValueError(f"{path} must contain a JSON array")
        return data
