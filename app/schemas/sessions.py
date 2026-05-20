from typing import Any

from pydantic import BaseModel, Field


class UserRecord(BaseModel):
    user_id: str
    display_name: str
    created_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class DiagnosisSession(BaseModel):
    session_id: str
    diagnosis_id: str
    title: str
    status: str
    user_id: str
    created_at: str
    updated_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class DiagnosisSessionResponse(BaseModel):
    session: DiagnosisSession


class DiagnosisSessionListResponse(BaseModel):
    sessions: list[DiagnosisSession]
