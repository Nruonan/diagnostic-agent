import json
from pathlib import Path
from typing import Any

from app.schemas.data import CodeSnippet, CollectedData, JobRecord, LogRecord, SlowQueryRecord, TraceSpan


class SampleDataSource:
    def __init__(self, sample_dir: Path):
        self.sample_dir = sample_dir

    async def collect(self, fault_description: str, service_hint: str | None = None) -> CollectedData:
        return CollectedData(
            logs=[LogRecord.model_validate(item) for item in self._load_list("logs.json")],
            jobs=[JobRecord.model_validate(item) for item in self._load_list("xxl_jobs.json")],
            slow_queries=[SlowQueryRecord.model_validate(item) for item in self._load_list("slow_queries.json")],
            traces=[TraceSpan.model_validate(item) for item in self._load_list("traces.json")],
            code_snippets=[CodeSnippet.model_validate(item) for item in self._load_list("code_snippets.json")],
        )

    def _load_list(self, filename: str) -> list[dict[str, Any]]:
        path = self.sample_dir / filename
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, list):
            raise ValueError(f"{path} must contain a JSON array")
        return data

