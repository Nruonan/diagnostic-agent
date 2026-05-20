from app.config import Settings
from app.llm.base import LLMClient
from app.llm.errors import LLMConfigurationError
from app.llm.metrics import llm_metrics_registry
from app.llm.providers import ClaudeProvider, DashScopeProvider, OpenAIProvider
from app.llm.resilient import ResilientLLMClient


def build_llm_client(settings: Settings) -> LLMClient:
    providers = [_build_provider(settings, provider_name) for provider_name in settings.ordered_llm_providers()]
    return ResilientLLMClient(providers, settings, llm_metrics_registry)


def _build_provider(settings: Settings, provider_name: str) -> LLMClient:
    if provider_name == "dashscope":
        return DashScopeProvider(settings)
    if provider_name == "openai":
        return OpenAIProvider(settings)
    if provider_name == "claude":
        return ClaudeProvider(settings)
    raise LLMConfigurationError(f"Unsupported LLM provider: {provider_name}")
