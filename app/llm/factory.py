from app.config import Settings
from app.llm.base import LLMClient
from app.llm.errors import LLMConfigurationError
from app.llm.providers import ClaudeProvider, DashScopeProvider, OpenAIProvider


def build_llm_client(settings: Settings) -> LLMClient:
    if settings.llm_provider == "dashscope":
        return DashScopeProvider(settings)
    if settings.llm_provider == "openai":
        return OpenAIProvider(settings)
    if settings.llm_provider == "claude":
        return ClaudeProvider(settings)
    raise LLMConfigurationError(f"Unsupported LLM_PROVIDER: {settings.llm_provider}")
