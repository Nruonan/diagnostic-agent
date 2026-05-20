import asyncio
import json
from time import perf_counter
from typing import Any

from pydantic import BaseModel

from app.config import Settings
from app.llm.base import LLMClient, ModelT
from app.llm.errors import LLMConfigurationError, LLMRequestError, LLMResponseError
from app.llm.metrics import LLMMetricLabels, LLMMetricsRegistry, clear_current_llm_usage, get_current_llm_usage


class ResilientLLMClient:
    def __init__(
        self,
        providers: list[LLMClient],
        settings: Settings,
        metrics: LLMMetricsRegistry,
    ):
        self.providers = providers
        self.settings = settings
        self.metrics = metrics

    async def complete_json(
        self,
        system_prompt: str,
        user_payload: dict[str, Any],
        response_model: type[ModelT],
    ) -> ModelT:
        if not self.providers:
            raise LLMConfigurationError("No LLM providers are available")

        last_error: Exception | None = None
        previous_provider_name: str | None = None
        for provider in self.providers:
            provider_name = _provider_name(provider)
            if previous_provider_name:
                self.metrics.record_fallback(previous_provider_name, provider_name)
            previous_provider_name = provider_name

            try:
                return await self._try_provider(provider, system_prompt, user_payload, response_model)
            except LLMConfigurationError as exc:
                last_error = exc
                continue
            except (LLMRequestError, LLMResponseError) as exc:
                last_error = exc
                continue

        if last_error:
            raise last_error
        raise LLMConfigurationError("No configured LLM provider could complete the request")

    async def _try_provider(
        self,
        provider: LLMClient,
        system_prompt: str,
        user_payload: dict[str, Any],
        response_model: type[ModelT],
    ) -> ModelT:
        max_attempts = self.settings.llm_retry_attempts + 1
        labels = LLMMetricLabels(
            provider=_provider_name(provider),
            model=_provider_model(provider),
            response_model=response_model.__name__,
        )
        input_tokens = _estimate_tokens(system_prompt) + _estimate_tokens(json.dumps(user_payload, ensure_ascii=False))
        last_error: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            started_at = perf_counter()
            try:
                clear_current_llm_usage()
                result = await provider.complete_json(system_prompt, user_payload, response_model)
            except LLMConfigurationError:
                raise
            except (LLMRequestError, LLMResponseError) as exc:
                latency_ms = (perf_counter() - started_at) * 1000
                self.metrics.record_call(labels, latency_ms, input_tokens, 0, success=False)
                clear_current_llm_usage()
                last_error = exc
                if attempt < max_attempts:
                    self.metrics.record_retry(labels)
                    await asyncio.sleep(self._backoff_delay(attempt))
                    continue
                raise

            latency_ms = (perf_counter() - started_at) * 1000
            usage = get_current_llm_usage()
            actual_input_tokens = usage.input_tokens if usage and usage.input_tokens is not None else input_tokens
            output_tokens = (
                usage.output_tokens
                if usage and usage.output_tokens is not None
                else _estimate_model_tokens(result)
            )
            self.metrics.record_call(labels, latency_ms, actual_input_tokens, output_tokens, success=True)
            clear_current_llm_usage()
            return result

        if last_error:
            raise last_error
        raise LLMRequestError(f"{labels.provider} request failed without a captured error")

    def _backoff_delay(self, attempt: int) -> float:
        return self.settings.llm_retry_backoff_seconds * (2 ** (attempt - 1))


def _provider_name(provider: LLMClient) -> str:
    return str(getattr(provider, "provider_name", provider.__class__.__name__.lower()))


def _provider_model(provider: LLMClient) -> str:
    settings = getattr(provider, "settings", None)
    provider_name = _provider_name(provider)
    if provider_name == "dashscope" and settings:
        return settings.dashscope_model
    if provider_name == "openai" and settings:
        return settings.openai_model
    if provider_name == "claude" and settings:
        return settings.claude_model
    return "unknown"


def _estimate_model_tokens(result: BaseModel) -> int:
    return _estimate_tokens(result.model_dump_json())


def _estimate_tokens(text: str) -> int:
    stripped = text.strip()
    if not stripped:
        return 0
    return max(1, len(stripped) // 4)
