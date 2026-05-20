class LLMConfigurationError(RuntimeError):
    """Raised when the selected LLM provider is not configured."""


class LLMRequestError(RuntimeError):
    """Raised when the selected LLM provider cannot be reached or returns an HTTP error."""


class LLMResponseError(RuntimeError):
    """Raised when the selected LLM provider returns invalid or schema-incompatible content."""
