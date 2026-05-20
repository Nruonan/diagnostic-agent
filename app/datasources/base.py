from typing import Protocol

from app.config import Settings
from app.schemas.data import CollectedData


class DataSource(Protocol):
    async def collect_error_context(self, fault_description: str, service_hint: str | None = None) -> CollectedData:
        raise NotImplementedError

    async def collect_sql_context(self, fault_description: str, service_hint: str | None = None) -> CollectedData:
        raise NotImplementedError

    async def collect_root_context(self, fault_description: str, service_hint: str | None = None) -> CollectedData:
        raise NotImplementedError

    async def collect(self, fault_description: str, service_hint: str | None = None) -> CollectedData:
        raise NotImplementedError


def build_data_source(settings: Settings) -> DataSource:
    if settings.data_source_mode == "http":
        from app.datasources.http import HttpDataSource

        return HttpDataSource(settings)

    from app.datasources.sample import SampleDataSource

    return SampleDataSource(settings.sample_data_path())
