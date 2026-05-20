import json
from typing import Any

import httpx
from pydantic import ValidationError

from app.config import Settings
from app.llm.base import ModelT
from app.llm.errors import LLMConfigurationError, LLMRequestError, LLMResponseError
from app.llm.json_utils import parse_json_content


class ClaudeProvider:
    provider_name = "claude"

    def __init__(self, settings: Settings):
        self.settings = settings

    async def complete_json(
        self,
        system_prompt: str,
        user_payload: dict[str, Any],
        response_model: type[ModelT],
    ) -> ModelT:
        if not self.settings.claude_configured():
            raise LLMConfigurationError("CLAUDE_API_KEY is not configured")

        payload = {
            "model": self.settings.claude_model,
            "system": system_prompt,
            "messages": [{"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}],
            "temperature": 0.2,
            "max_tokens": self.settings.claude_max_tokens,
        }
        headers = {
            "x-api-key": self.settings.claude_api_key,
            "anthropic-version": self.settings.claude_api_version,
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self.settings.claude_timeout_seconds) as client:
                response = await client.post(self._messages_url(), headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise LLMRequestError("Claude request timed out") from exc
        except httpx.HTTPError as exc:
            raise LLMRequestError(f"Claude request failed: {exc}") from exc

        if response.status_code >= 400:
            raise LLMRequestError(f"Claude returned HTTP {response.status_code}: {response.text[:500]}")

        content = self._extract_content(response.json())
        data = parse_json_content(content, "Claude")
        try:
            return response_model.model_validate(data)
        except ValidationError as exc:
            raise LLMResponseError(
                f"Claude JSON did not match {response_model.__name__}: {exc}; raw={content[:800]}"
            ) from exc

    def _messages_url(self) -> str:
        base_url = self.settings.claude_base_url.rstrip("/")
        if base_url.endswith("/messages"):
            return base_url
        return f"{base_url}/messages"

    def _extract_content(self, response_data: dict[str, Any]) -> str:
        content = response_data.get("content")
        if not isinstance(content, list):
            raise LLMResponseError(f"Unexpected Claude response shape: {response_data}")
        text_parts = [
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        joined = "\n".join(part for part in text_parts if part)
        if joined.strip():
            return joined
        raise LLMResponseError("Claude response content is empty")
