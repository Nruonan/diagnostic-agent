import json
from typing import Any

import httpx
from pydantic import ValidationError

from app.config import Settings
from app.llm.base import ModelT
from app.llm.errors import LLMConfigurationError, LLMRequestError, LLMResponseError
from app.llm.json_utils import openai_compatible_content, parse_json_content


class DashScopeProvider:
    provider_name = "dashscope"

    def __init__(self, settings: Settings):
        self.settings = settings

    async def complete_json(
        self,
        system_prompt: str,
        user_payload: dict[str, Any],
        response_model: type[ModelT],
    ) -> ModelT:
        if not self.settings.dashscope_configured():
            raise LLMConfigurationError("DASHSCOPE_API_KEY is not configured")

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
            raise LLMRequestError("DashScope request timed out") from exc
        except httpx.HTTPError as exc:
            raise LLMRequestError(f"DashScope request failed: {exc}") from exc

        if response.status_code >= 400:
            raise LLMRequestError(f"DashScope returned HTTP {response.status_code}: {response.text[:500]}")

        content = openai_compatible_content(response.json(), "DashScope")
        data = parse_json_content(content, "DashScope")
        try:
            return response_model.model_validate(data)
        except ValidationError as exc:
            raise LLMResponseError(
                f"DashScope JSON did not match {response_model.__name__}: {exc}; raw={content[:800]}"
            ) from exc

    def _completion_url(self) -> str:
        base_url = self.settings.dashscope_base_url.rstrip("/")
        if base_url.endswith("/chat/completions"):
            return base_url
        return f"{base_url}/chat/completions"
