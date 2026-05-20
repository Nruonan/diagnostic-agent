import asyncio
from typing import Awaitable, TypeVar

from app.config import Settings
from app.llm import LLMClient


ResultT = TypeVar("ResultT")


class BaseAgent:
    agent_name: str = "base"

    def __init__(self, client: LLMClient, settings: Settings):
        self.client = client
        self.settings = settings

    async def with_timeout(self, operation: Awaitable[ResultT]) -> ResultT:
        return await asyncio.wait_for(operation, timeout=self.settings.agent_timeout_seconds)
