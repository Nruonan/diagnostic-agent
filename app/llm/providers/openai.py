import json
from typing import Any

import httpx
from pydantic import ValidationError

from app.config import Settings
from app.llm.base import ModelT
from app.llm.errors import LLMConfigurationError, LLMRequestError, LLMResponseError
from app.llm.json_utils import openai_compatible_content, parse_json_content
from app.llm.metrics import set_current_llm_usage


class OpenAIProvider:
    provider_name = "openai"

    def __init__(self, settings: Settings):
        self.settings = settings

    async def complete_json(
        self,
        system_prompt: str,
        user_payload: dict[str, Any],
        response_model: type[ModelT],
    ) -> ModelT:
        if not self.settings.openai_configured():
            raise LLMConfigurationError("OPENAI_API_KEY is not configured")

        payload = {
            "model": self.settings.openai_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self.settings.openai_api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self.settings.openai_timeout_seconds) as client:
                response = await client.post(self._completion_url(), headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise LLMRequestError("OpenAI request timed out") from exc
        except httpx.HTTPError as exc:
            raise LLMRequestError(f"OpenAI request failed: {exc}") from exc

        if response.status_code >= 400:
            raise LLMRequestError(f"OpenAI returned HTTP {response.status_code}: {response.text[:500]}")

        response_data = response.json()
        _record_usage(response_data)
        content = openai_compatible_content(response_data, "OpenAI")
        data = parse_json_content(content, "OpenAI")
        try:
            return response_model.model_validate(data)
        except ValidationError as exc:
            raise LLMResponseError(
                f"OpenAI JSON did not match {response_model.__name__}: {exc}; raw={content[:800]}"
            ) from exc

    def _completion_url(self) -> str:
        base_url = self.settings.openai_base_url.rstrip("/")
        if base_url.endswith("/chat/completions"):
            return base_url
        return f"{base_url}/chat/completions"


def _record_usage(response_data: dict[str, Any]) -> None:
    usage = response_data.get("usage")
    if not isinstance(usage, dict):
        return
    set_current_llm_usage(
        input_tokens=_int_or_none(usage.get("prompt_tokens")),
        output_tokens=_int_or_none(usage.get("completion_tokens")),
    )


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
