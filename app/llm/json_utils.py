import json
import re
from typing import Any

from app.llm.errors import LLMResponseError


def parse_json_content(content: str, provider: str) -> dict[str, Any]:
    normalized = content.strip()
    fenced_match = re.search(r"```(?:json)?\s*(.*?)```", normalized, re.DOTALL | re.IGNORECASE)
    if fenced_match:
        normalized = fenced_match.group(1).strip()

    try:
        data = json.loads(normalized)
    except json.JSONDecodeError as exc:
        raise LLMResponseError(f"{provider} response is not valid JSON: {content[:800]}") from exc
    if not isinstance(data, dict):
        raise LLMResponseError(f"{provider} response JSON must be an object")
    return data


def openai_compatible_content(response_data: dict[str, Any], provider: str) -> str:
    try:
        message = response_data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMResponseError(f"Unexpected {provider} response shape: {response_data}") from exc

    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content
    if isinstance(content, list):
        text_parts = [part.get("text", "") for part in content if isinstance(part, dict)]
        joined = "\n".join(part for part in text_parts if part)
        if joined.strip():
            return joined
    raise LLMResponseError(f"{provider} response content is empty")
