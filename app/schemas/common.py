from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DataSourceError(BaseModel):
    source: str
    message: str
    recoverable: bool = True
    detail: dict[str, Any] = Field(default_factory=dict)


class RuntimeErrorInfo(BaseModel):
    stage: str
    message: str
    recoverable: bool = False
    detail: dict[str, Any] = Field(default_factory=dict)

