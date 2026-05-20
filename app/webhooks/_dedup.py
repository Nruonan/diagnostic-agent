import asyncio
import hashlib
import json
import time
from typing import Any

from fastapi import Request


class DeduplicationService:
    def __init__(self, cooldown_seconds: float) -> None:
        self.cooldown_seconds = cooldown_seconds
        self._expires_at: dict[str, float] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def fingerprint(source: str, key_fields: Any) -> str:
        payload = json.dumps(
            {"source": source, "key_fields": key_fields},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    async def is_duplicate(self, fingerprint: str) -> bool:
        now = time.monotonic()
        async with self._lock:
            self._drop_expired(now)
            expires_at = self._expires_at.get(fingerprint)
            if expires_at is not None and expires_at > now:
                return True
            self._expires_at[fingerprint] = now + self.cooldown_seconds
            return False

    def _drop_expired(self, now: float) -> None:
        expired = [key for key, expires_at in self._expires_at.items() if expires_at <= now]
        for key in expired:
            self._expires_at.pop(key, None)


def get_dedup_service(request: Request) -> DeduplicationService:
    return request.app.state.dedup_service
