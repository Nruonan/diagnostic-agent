import json
import re
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.config import Settings


class DashScopeConfigurationError(RuntimeError):
    """Raised when required DashScope configuration is missing."""


class DashScopeRequestError(RuntimeError):
    """Raised when DashScope cannot be reached or returns an HTTP error."""


class DashScopeResponseError(RuntimeError):
    """Raised when DashScope returns empty, invalid, or schema-incompatible content."""


ModelT = TypeVar("ModelT", bound=BaseModel)


class DashScopeClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def complete_json(
        self,
        system_prompt: str,
        user_payload: dict[str, Any],
        response_model: type[ModelT],
    ) -> ModelT:
        if not self.settings.dashscope_configured():
            raise DashScopeConfigurationError("DASHSCOPE_API_KEY is not configured")

        payload = {
            "model": self.settings.dashscope_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self.settings.dashscope_api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self.settings.dashscope_timeout_seconds) as client:
                response = await client.post(self._completion_url(), headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise DashScopeRequestError("DashScope request timed out") from exc
        except httpx.HTTPError as exc:
            raise DashScopeRequestError(f"DashScope request failed: {exc}") from exc

        if response.status_code >= 400:
            raise DashScopeRequestError(
                f"DashScope returned HTTP {response.status_code}: {response.text[:500]}"
            )

        content = self._extract_content(response.json())
        data = self._parse_json_content(content)
        try:
            return response_model.model_validate(data)
        except ValidationError as exc:
            excerpt = content[:800]
            raise DashScopeResponseError(
                f"DashScope JSON did not match {response_model.__name__}: {exc}; raw={excerpt}"
            ) from exc

    def _extract_content(self, response_data: dict[str, Any]) -> str:
        try:
            message = response_data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise DashScopeResponseError(f"Unexpected DashScope response shape: {response_data}") from exc

        content = message.get("content")
        if isinstance(content, str):
            if content.strip():
                return content
        elif isinstance(content, list):
            text_parts = [part.get("text", "") for part in content if isinstance(part, dict)]
            joined = "\n".join(part for part in text_parts if part)
            if joined.strip():
                return joined
        raise DashScopeResponseError("DashScope response content is empty")

    def _completion_url(self) -> str:
        base_url = self.settings.dashscope_base_url.rstrip("/")
        if base_url.endswith("/chat/completions"):
            return base_url
        return f"{base_url}/chat/completions"

    def _parse_json_content(self, content: str) -> dict[str, Any]:
        normalized = content.strip()
        fenced_match = re.search(r"```(?:json)?\s*(.*?)```", normalized, re.DOTALL | re.IGNORECASE)
        if fenced_match:
            normalized = fenced_match.group(1).strip()

        try:
            data = json.loads(normalized)
        except json.JSONDecodeError as exc:
            raise DashScopeResponseError(f"DashScope response is not valid JSON: {content[:800]}") from exc
        if not isinstance(data, dict):
            raise DashScopeResponseError("DashScope response JSON must be an object")
        return data
