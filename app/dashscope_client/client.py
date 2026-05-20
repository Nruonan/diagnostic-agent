from app.llm.errors import LLMConfigurationError, LLMRequestError, LLMResponseError
from app.llm.providers.dashscope import DashScopeProvider


DashScopeClient = DashScopeProvider
DashScopeConfigurationError = LLMConfigurationError
DashScopeRequestError = LLMRequestError
DashScopeResponseError = LLMResponseError


__all__ = [
    "DashScopeClient",
    "DashScopeConfigurationError",
    "DashScopeRequestError",
    "DashScopeResponseError",
]
