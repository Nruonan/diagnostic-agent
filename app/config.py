from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, HttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    dashscope_api_key: str = Field(default="", alias="DASHSCOPE_API_KEY")
    dashscope_model: str = Field(default="qwen-plus", alias="DASHSCOPE_MODEL")
    dashscope_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        alias="DASHSCOPE_BASE_URL",
    )
    dashscope_timeout_seconds: float = Field(default=60.0, gt=0, alias="DASHSCOPE_TIMEOUT_SECONDS")

    data_source_mode: Literal["sample", "http"] = Field(default="sample", alias="DATA_SOURCE_MODE")
    elk_api_url: str = Field(default="", alias="ELK_API_URL")
    xxl_job_api_url: str = Field(default="", alias="XXL_JOB_API_URL")
    slow_query_api_url: str = Field(default="", alias="SLOW_QUERY_API_URL")
    trace_api_url: str = Field(default="", alias="TRACE_API_URL")
    git_code_api_url: str = Field(default="", alias="GIT_CODE_API_URL")

    agent_timeout_seconds: float = Field(default=120.0, gt=0, alias="AGENT_TIMEOUT_SECONDS")
    low_confidence_threshold: float = Field(default=0.8, ge=0.0, le=1.0, alias="LOW_CONFIDENCE_THRESHOLD")
    webhook_token: str = Field(default="", alias="WEBHOOK_TOKEN")
    webhook_dedup_cooldown_seconds: float = Field(default=300.0, gt=0, alias="WEBHOOK_DEDUP_COOLDOWN_SECONDS")
    sample_data_dir: Path = Field(default=Path("sample_data"), alias="SAMPLE_DATA_DIR")
    runtime_dir: Path = Field(default=Path(".runtime"), alias="RUNTIME_DIR")

    @field_validator("dashscope_base_url")
    @classmethod
    def validate_dashscope_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("DASHSCOPE_BASE_URL must start with http:// or https://")
        return value

    def dashscope_configured(self) -> bool:
        return bool(self.dashscope_api_key.strip())

    def sample_data_path(self) -> Path:
        return self.sample_data_dir


@lru_cache
def get_settings() -> Settings:
    return Settings()
