from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, HttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    llm_provider: Literal["dashscope", "openai", "claude"] = Field(default="dashscope", alias="LLM_PROVIDER")

    dashscope_api_key: str = Field(default="", alias="DASHSCOPE_API_KEY")
    dashscope_model: str = Field(default="qwen-plus", alias="DASHSCOPE_MODEL")
    dashscope_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        alias="DASHSCOPE_BASE_URL",
    )
    dashscope_timeout_seconds: float = Field(default=60.0, gt=0, alias="DASHSCOPE_TIMEOUT_SECONDS")

    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4.1-mini", alias="OPENAI_MODEL")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    openai_timeout_seconds: float = Field(default=60.0, gt=0, alias="OPENAI_TIMEOUT_SECONDS")

    claude_api_key: str = Field(default="", alias="CLAUDE_API_KEY")
    claude_model: str = Field(default="claude-sonnet-4-5", alias="CLAUDE_MODEL")
    claude_base_url: str = Field(default="https://api.anthropic.com/v1", alias="CLAUDE_BASE_URL")
    claude_api_version: str = Field(default="2023-06-01", alias="CLAUDE_API_VERSION")
    claude_timeout_seconds: float = Field(default=60.0, gt=0, alias="CLAUDE_TIMEOUT_SECONDS")
    claude_max_tokens: int = Field(default=4096, gt=0, alias="CLAUDE_MAX_TOKENS")
    llm_retry_attempts: int = Field(default=2, ge=0, le=5, alias="LLM_RETRY_ATTEMPTS")
    llm_retry_backoff_seconds: float = Field(default=0.5, ge=0.0, alias="LLM_RETRY_BACKOFF_SECONDS")
    llm_fallback_providers: str = Field(default="", alias="LLM_FALLBACK_PROVIDERS")

    data_source_mode: Literal["sample", "http"] = Field(default="sample", alias="DATA_SOURCE_MODE")
    elk_api_url: str = Field(default="", alias="ELK_API_URL")
    xxl_job_api_url: str = Field(default="", alias="XXL_JOB_API_URL")
    zabbix_api_url: str = Field(default="", alias="ZABBIX_API_URL")
    slow_query_api_url: str = Field(default="", alias="SLOW_QUERY_API_URL")
    prometheus_api_url: str = Field(default="", alias="PROMETHEUS_API_URL")
    trace_api_url: str = Field(default="", alias="TRACE_API_URL")
    git_code_api_url: str = Field(default="", alias="GIT_CODE_API_URL")

    agent_timeout_seconds: float = Field(default=120.0, gt=0, alias="AGENT_TIMEOUT_SECONDS")
    low_confidence_threshold: float = Field(default=0.8, ge=0.0, le=1.0, alias="LOW_CONFIDENCE_THRESHOLD")
    webhook_token: str = Field(default="", alias="WEBHOOK_TOKEN")
    webhook_dedup_cooldown_seconds: float = Field(default=300.0, gt=0, alias="WEBHOOK_DEDUP_COOLDOWN_SECONDS")
    sample_data_dir: Path = Field(default=Path("sample_data"), alias="SAMPLE_DATA_DIR")
    runtime_dir: Path = Field(default=Path(".runtime"), alias="RUNTIME_DIR")
    storage_mode: Literal["json", "postgres"] = Field(default="json", alias="STORAGE_MODE")
    database_url: str = Field(default="", alias="DATABASE_URL")

    @field_validator("dashscope_base_url", "openai_base_url", "claude_base_url")
    @classmethod
    def validate_llm_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("LLM base URLs must start with http:// or https://")
        return value

    def dashscope_configured(self) -> bool:
        return bool(self.dashscope_api_key.strip())

    def openai_configured(self) -> bool:
        return bool(self.openai_api_key.strip())

    def claude_configured(self) -> bool:
        return bool(self.claude_api_key.strip())

    def llm_configured(self) -> bool:
        return self.provider_configured(self.llm_provider)

    def any_llm_configured(self) -> bool:
        return any(self.provider_configured(provider) for provider in self.ordered_llm_providers())

    def provider_configured(self, provider: str) -> bool:
        if provider == "dashscope":
            return self.dashscope_configured()
        if provider == "openai":
            return self.openai_configured()
        if provider == "claude":
            return self.claude_configured()
        return False

    def ordered_llm_providers(self) -> list[str]:
        providers = [self.llm_provider, *self.fallback_provider_names()]
        if not self.llm_fallback_providers.strip():
            providers.extend(["dashscope", "openai", "claude"])
        ordered: list[str] = []
        for provider in providers:
            if provider in {"dashscope", "openai", "claude"} and provider not in ordered:
                ordered.append(provider)
        return ordered

    def fallback_provider_names(self) -> list[str]:
        return [
            provider.strip()
            for provider in self.llm_fallback_providers.split(",")
            if provider.strip() in {"dashscope", "openai", "claude"}
        ]

    def configured_provider_names(self) -> list[str]:
        return [provider for provider in self.ordered_llm_providers() if self.provider_configured(provider)]

    def primary_llm_configured(self) -> bool:
        if self.llm_provider == "dashscope":
            return self.dashscope_configured()
        if self.llm_provider == "openai":
            return self.openai_configured()
        if self.llm_provider == "claude":
            return self.claude_configured()
        return False

    def llm_missing_configuration_message(self) -> str:
        if not self.any_llm_configured():
            return "No LLM provider API key is configured"
        if self.llm_provider == "dashscope":
            return "DASHSCOPE_API_KEY is not configured"
        if self.llm_provider == "openai":
            return "OPENAI_API_KEY is not configured"
        if self.llm_provider == "claude":
            return "CLAUDE_API_KEY is not configured"
        return f"Unsupported LLM_PROVIDER: {self.llm_provider}"

    def sample_data_path(self) -> Path:
        return self.sample_data_dir


@lru_cache
def get_settings() -> Settings:
    return Settings()
