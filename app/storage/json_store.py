import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.events import WorkflowEvent
from app.schemas.common import utc_now
from app.schemas.diagnosis import DiagnosisState
from app.schemas.sessions import DiagnosisSession, UserRecord


DEFAULT_USER_ID = "anonymous"


class JsonDiagnosisStore:
    def __init__(self, runtime_dir: Path):
        self.runtime_dir = runtime_dir
        self.base_dir = runtime_dir / "diagnoses"
        self.sessions_dir = runtime_dir / "sessions"
        self.events_dir = runtime_dir / "events"
        self.users_path = runtime_dir / "users.json"
        self._ensure_dirs()

    async def initialize(self) -> None:
        self._ensure_dirs()
        await self.ensure_default_user()

    async def close(self) -> None:
        return None

    async def save(self, state: DiagnosisState) -> None:
        path = self._path(state.diagnosis_id)
        with path.open("w", encoding="utf-8") as file:
            json.dump(state.model_dump(mode="json"), file, ensure_ascii=False, indent=2)
        session_path = self._session_path(state.diagnosis_id)
        if session_path.exists():
            with session_path.open("r", encoding="utf-8") as file:
                session = json.load(file)
            session["status"] = state.status.value
            session["updated_at"] = state.updated_at
            with session_path.open("w", encoding="utf-8") as file:
                json.dump(session, file, ensure_ascii=False, indent=2)

    async def get(self, diagnosis_id: str) -> DiagnosisState:
        path = self._path(diagnosis_id)
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"diagnosis {diagnosis_id} not found")
        with path.open("r", encoding="utf-8") as file:
            return DiagnosisState.model_validate(json.load(file))

    async def ensure_default_user(self) -> UserRecord:
        users = self._read_users()
        now = utc_now().isoformat()
        if DEFAULT_USER_ID not in users:
            users[DEFAULT_USER_ID] = {
                "user_id": DEFAULT_USER_ID,
                "display_name": "Anonymous User",
                "created_at": now,
                "metadata": {"kind": "system_default"},
            }
            self._write_users(users)
        return UserRecord.model_validate(users[DEFAULT_USER_ID])

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
        now = utc_now().isoformat()
        path = self._session_path(session_id)
        existing = {}
        if path.exists():
            with path.open("r", encoding="utf-8") as file:
                existing = json.load(file)
        session = {
            "session_id": session_id,
            "diagnosis_id": diagnosis_id,
            "title": (title[:200] or diagnosis_id),
            "status": existing.get("status", "created"),
            "user_id": resolved_user_id,
            "created_at": existing.get("created_at", now),
            "updated_at": now,
            "metadata": metadata or {},
        }
        with path.open("w", encoding="utf-8") as file:
            json.dump(session, file, ensure_ascii=False, indent=2)
        return DiagnosisSession.model_validate(session)

    async def get_session(self, session_id: str) -> DiagnosisSession:
        path = self._session_path(session_id)
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"session {session_id} not found")
        with path.open("r", encoding="utf-8") as file:
            return DiagnosisSession.model_validate(json.load(file))

    async def list_sessions(self, user_id: str | None = None, limit: int = 50) -> list[DiagnosisSession]:
        bounded_limit = max(1, min(limit, 200))
        sessions = []
        for path in self.sessions_dir.glob("*.json"):
            with path.open("r", encoding="utf-8") as file:
                session = DiagnosisSession.model_validate(json.load(file))
            if user_id is None or session.user_id == user_id:
                sessions.append(session)
        sessions.sort(key=lambda item: item.updated_at, reverse=True)
        return sessions[:bounded_limit]

    async def save_event(self, event: WorkflowEvent) -> WorkflowEvent:
        events = await self.list_events(event.diagnosis_id)
        next_event_id = max((item.event_id for item in events), default=0) + 1
        persisted = event.model_copy(update={"event_id": next_event_id})
        path = self._events_path(event.diagnosis_id)
        with path.open("a", encoding="utf-8") as file:
            file.write(persisted.model_dump_json() + "\n")
        return persisted

    async def list_events(self, diagnosis_id: str, after_event_id: int | None = None) -> list[WorkflowEvent]:
        path = self._events_path(diagnosis_id)
        if not path.exists():
            return []
        events = []
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue
                event = WorkflowEvent.model_validate_json(line)
                if after_event_id is None or event.event_id > after_event_id:
                    events.append(event)
        return events

    def _path(self, diagnosis_id: str) -> Path:
        safe_id = diagnosis_id.replace("/", "").replace("\\", "")
        return self.base_dir / f"{safe_id}.json"

    def _session_path(self, session_id: str) -> Path:
        safe_id = session_id.replace("/", "").replace("\\", "")
        return self.sessions_dir / f"{safe_id}.json"

    def _events_path(self, diagnosis_id: str) -> Path:
        safe_id = diagnosis_id.replace("/", "").replace("\\", "")
        return self.events_dir / f"{safe_id}.jsonl"

    def _ensure_dirs(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.events_dir.mkdir(parents=True, exist_ok=True)

    def _read_users(self) -> dict[str, Any]:
        if not self.users_path.exists():
            return {}
        with self.users_path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def _write_users(self, users: dict[str, Any]) -> None:
        with self.users_path.open("w", encoding="utf-8") as file:
            json.dump(users, file, ensure_ascii=False, indent=2)
