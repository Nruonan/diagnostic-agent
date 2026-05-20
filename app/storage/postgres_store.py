from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import Column, DateTime, Index, MetaData, String, Table, Text, select
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import create_async_engine

from app.schemas.diagnosis import DiagnosisState


metadata = MetaData()

diagnoses_table = Table(
    "diagnoses",
    metadata,
    Column("diagnosis_id", String(64), primary_key=True),
    Column("status", String(32), nullable=False),
    Column("fault_description", Text, nullable=False),
    Column("service_hint", String(200), nullable=True),
    Column("trigger_source", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("state_json", JSONB, nullable=False),
    Index("idx_diagnoses_status", "status"),
    Index("idx_diagnoses_created_at", "created_at"),
    Index("idx_diagnoses_updated_at", "updated_at"),
    Index("idx_diagnoses_trigger_source", "trigger_source"),
    Index("idx_diagnoses_service_hint", "service_hint"),
    Index("idx_diagnoses_state_json_gin", "state_json", postgresql_using="gin"),
)


class PostgresDiagnosisStore:
    def __init__(self, database_url: str):
        if not database_url.strip():
            raise ValueError("DATABASE_URL is required when STORAGE_MODE=postgres")
        self.engine = create_async_engine(_normalize_database_url(database_url), pool_pre_ping=True)

    async def initialize(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(metadata.create_all)

    async def close(self) -> None:
        await self.engine.dispose()

    async def save(self, state: DiagnosisState) -> None:
        state_json = state.model_dump(mode="json")
        values = {
            "diagnosis_id": state.diagnosis_id,
            "status": state.status.value,
            "fault_description": state.fault_description,
            "service_hint": state.service_hint,
            "trigger_source": state.trigger_source,
            "created_at": _parse_iso_datetime(state.created_at),
            "updated_at": _parse_iso_datetime(state.updated_at),
            "state_json": state_json,
        }
        statement = insert(diagnoses_table).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[diagnoses_table.c.diagnosis_id],
            set_={
                "status": statement.excluded.status,
                "fault_description": statement.excluded.fault_description,
                "service_hint": statement.excluded.service_hint,
                "trigger_source": statement.excluded.trigger_source,
                "created_at": statement.excluded.created_at,
                "updated_at": statement.excluded.updated_at,
                "state_json": statement.excluded.state_json,
            },
        )
        async with self.engine.begin() as conn:
            await conn.execute(statement)

    async def get(self, diagnosis_id: str) -> DiagnosisState:
        statement = select(diagnoses_table.c.state_json).where(diagnoses_table.c.diagnosis_id == diagnosis_id)
        async with self.engine.connect() as conn:
            result = await conn.execute(statement)
            state_json = result.scalar_one_or_none()
        if state_json is None:
            raise HTTPException(status_code=404, detail=f"diagnosis {diagnosis_id} not found")
        return DiagnosisState.model_validate(state_json)


def _normalize_database_url(database_url: str) -> str:
    value = database_url.strip()
    if value.startswith("postgresql://"):
        return value.replace("postgresql://", "postgresql+asyncpg://", 1)
    return value


def _parse_iso_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
