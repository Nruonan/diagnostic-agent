from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, MetaData, String, Table, Text, desc, select, update
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import create_async_engine

from app.events import WorkflowEvent
from app.schemas.diagnosis import DiagnosisState
from app.schemas.sessions import DiagnosisSession, UserRecord


metadata = MetaData()
DEFAULT_USER_ID = "anonymous"

users_table = Table(
    "users",
    metadata,
    Column("user_id", String(64), primary_key=True),
    Column("display_name", String(120), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("metadata_json", JSONB, nullable=False, default=dict),
    Index("idx_users_created_at", "created_at"),
)

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

diagnosis_sessions_table = Table(
    "diagnosis_sessions",
    metadata,
    Column("session_id", String(64), primary_key=True),
    Column("diagnosis_id", String(64), nullable=False, unique=True),
    Column("user_id", String(64), ForeignKey("users.user_id"), nullable=False),
    Column("title", String(200), nullable=False),
    Column("status", String(32), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("metadata_json", JSONB, nullable=False, default=dict),
    Index("idx_diagnosis_sessions_user_id", "user_id"),
    Index("idx_diagnosis_sessions_status", "status"),
    Index("idx_diagnosis_sessions_created_at", "created_at"),
    Index("idx_diagnosis_sessions_updated_at", "updated_at"),
)

workflow_events_table = Table(
    "workflow_events",
    metadata,
    Column("event_id", BigInteger, primary_key=True, autoincrement=True),
    Column("diagnosis_id", String(64), nullable=False),
    Column("event", String(120), nullable=False),
    Column("message", Text, nullable=False),
    Column("stage", String(64), nullable=True),
    Column("status", String(32), nullable=True),
    Column("payload", JSONB, nullable=False, default=dict),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Index("idx_workflow_events_diagnosis_event", "diagnosis_id", "event_id"),
    Index("idx_workflow_events_created_at", "created_at"),
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
            await conn.execute(
                update(diagnosis_sessions_table)
                .where(diagnosis_sessions_table.c.diagnosis_id == state.diagnosis_id)
                .values(status=state.status.value, updated_at=_parse_iso_datetime(state.updated_at))
            )

    async def get(self, diagnosis_id: str) -> DiagnosisState:
        statement = select(diagnoses_table.c.state_json).where(diagnoses_table.c.diagnosis_id == diagnosis_id)
        async with self.engine.connect() as conn:
            result = await conn.execute(statement)
            state_json = result.scalar_one_or_none()
        if state_json is None:
            raise HTTPException(status_code=404, detail=f"diagnosis {diagnosis_id} not found")
        return DiagnosisState.model_validate(state_json)

    async def ensure_default_user(self) -> UserRecord:
        now = datetime.now(timezone.utc)
        values = {
            "user_id": DEFAULT_USER_ID,
            "display_name": "Anonymous User",
            "created_at": now,
            "metadata_json": {"kind": "system_default"},
        }
        statement = insert(users_table).values(**values)
        statement = statement.on_conflict_do_nothing(index_elements=[users_table.c.user_id])
        async with self.engine.begin() as conn:
            await conn.execute(statement)
        return UserRecord(
            user_id=DEFAULT_USER_ID,
            display_name="Anonymous User",
            created_at=now.isoformat(),
            metadata={"kind": "system_default"},
        )

    async def create_session(
        self,
        session_id: str,
        diagnosis_id: str,
        title: str,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DiagnosisSession:
        user = await self.ensure_default_user()
        resolved_user_id = user_id or user.user_id
        now = datetime.now(timezone.utc)
        values = {
            "session_id": session_id,
            "diagnosis_id": diagnosis_id,
            "user_id": resolved_user_id,
            "title": title[:200] or diagnosis_id,
            "status": "created",
            "created_at": now,
            "updated_at": now,
            "metadata_json": metadata or {},
        }
        statement = insert(diagnosis_sessions_table).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[diagnosis_sessions_table.c.session_id],
            set_={
                "diagnosis_id": statement.excluded.diagnosis_id,
                "user_id": statement.excluded.user_id,
                "title": statement.excluded.title,
                "updated_at": statement.excluded.updated_at,
                "metadata_json": statement.excluded.metadata_json,
            },
        )
        async with self.engine.begin() as conn:
            await conn.execute(statement)
        return await self.get_session(session_id)

    async def get_session(self, session_id: str) -> DiagnosisSession:
        statement = select(diagnosis_sessions_table).where(diagnosis_sessions_table.c.session_id == session_id)
        async with self.engine.connect() as conn:
            result = await conn.execute(statement)
            row = result.mappings().one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail=f"session {session_id} not found")
        return _session_from_row(row)

    async def list_sessions(self, user_id: str | None = None, limit: int = 50) -> list[DiagnosisSession]:
        bounded_limit = max(1, min(limit, 200))
        statement = select(diagnosis_sessions_table).order_by(desc(diagnosis_sessions_table.c.updated_at)).limit(
            bounded_limit
        )
        if user_id is not None:
            statement = statement.where(diagnosis_sessions_table.c.user_id == user_id)
        async with self.engine.connect() as conn:
            result = await conn.execute(statement)
            rows = result.mappings().all()
        return [_session_from_row(row) for row in rows]

    async def save_event(self, event: WorkflowEvent) -> WorkflowEvent:
        values = {
            "diagnosis_id": event.diagnosis_id,
            "event": event.event,
            "message": event.message,
            "stage": event.stage,
            "status": event.status,
            "payload": event.payload,
            "created_at": _parse_iso_datetime(event.created_at),
        }
        statement = insert(workflow_events_table).values(**values).returning(workflow_events_table)
        async with self.engine.begin() as conn:
            result = await conn.execute(statement)
            row = result.mappings().one()
        return _event_from_row(row)

    async def list_events(self, diagnosis_id: str, after_event_id: int | None = None) -> list[WorkflowEvent]:
        statement = select(workflow_events_table).where(workflow_events_table.c.diagnosis_id == diagnosis_id)
        if after_event_id is not None:
            statement = statement.where(workflow_events_table.c.event_id > after_event_id)
        statement = statement.order_by(workflow_events_table.c.event_id)
        async with self.engine.connect() as conn:
            result = await conn.execute(statement)
            rows = result.mappings().all()
        return [_event_from_row(row) for row in rows]


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


def _iso_datetime(value: datetime | str) -> str:
    if isinstance(value, str):
        return value
    return value.isoformat()


def _session_from_row(row) -> DiagnosisSession:
    return DiagnosisSession(
        session_id=row["session_id"],
        diagnosis_id=row["diagnosis_id"],
        title=row["title"],
        status=row["status"],
        user_id=row["user_id"],
        created_at=_iso_datetime(row["created_at"]),
        updated_at=_iso_datetime(row["updated_at"]),
        metadata=row["metadata_json"] or {},
    )


def _event_from_row(row) -> WorkflowEvent:
    return WorkflowEvent(
        event_id=int(row["event_id"]),
        diagnosis_id=row["diagnosis_id"],
        event=row["event"],
        message=row["message"],
        stage=row["stage"],
        status=row["status"],
        payload=row["payload"] or {},
        created_at=_iso_datetime(row["created_at"]),
    )
