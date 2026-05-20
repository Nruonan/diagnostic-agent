import asyncio
from collections import defaultdict
from typing import Any, AsyncIterator, Protocol

from pydantic import BaseModel, Field

from app.schemas.common import utc_now


class WorkflowEvent(BaseModel):
    event_id: int
    diagnosis_id: str
    event: str
    message: str
    stage: str | None = None
    status: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: utc_now().isoformat())


class WorkflowEventStore(Protocol):
    async def save_event(self, event: WorkflowEvent) -> WorkflowEvent:
        raise NotImplementedError

    async def list_events(self, diagnosis_id: str, after_event_id: int | None = None) -> list[WorkflowEvent]:
        raise NotImplementedError


class WorkflowEventBus:
    def __init__(self, max_history_per_diagnosis: int = 200, store: WorkflowEventStore | None = None):
        self.max_history_per_diagnosis = max_history_per_diagnosis
        self.store = store
        self._next_event_id = 1
        self._history: dict[str, list[WorkflowEvent]] = defaultdict(list)
        self._subscribers: dict[str, set[asyncio.Queue[WorkflowEvent]]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def publish(
        self,
        diagnosis_id: str,
        event: str,
        message: str,
        stage: str | None = None,
        status: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> WorkflowEvent:
        async with self._lock:
            workflow_event = WorkflowEvent(
                event_id=self._next_event_id,
                diagnosis_id=diagnosis_id,
                event=event,
                message=message,
                stage=stage,
                status=status,
                payload=payload or {},
            )
            if self.store is not None:
                workflow_event = await self.store.save_event(workflow_event)
                self._next_event_id = max(self._next_event_id, workflow_event.event_id + 1)
            else:
                self._next_event_id += 1

            history = self._history[diagnosis_id]
            history.append(workflow_event)
            if len(history) > self.max_history_per_diagnosis:
                del history[: len(history) - self.max_history_per_diagnosis]

            subscribers = list(self._subscribers.get(diagnosis_id, set()))

        for queue in subscribers:
            try:
                queue.put_nowait(workflow_event)
            except asyncio.QueueFull:
                await self._drop_subscriber(diagnosis_id, queue)
        return workflow_event

    async def subscribe(
        self,
        diagnosis_id: str,
        last_event_id: int | None = None,
    ) -> AsyncIterator[WorkflowEvent]:
        queue: asyncio.Queue[WorkflowEvent] = asyncio.Queue(maxsize=100)
        async with self._lock:
            replay = await self._replay_events(diagnosis_id, last_event_id)
            self._subscribers[diagnosis_id].add(queue)

        try:
            for event in replay:
                yield event
            while True:
                yield await queue.get()
        finally:
            await self._drop_subscriber(diagnosis_id, queue)

    async def _drop_subscriber(self, diagnosis_id: str, queue: asyncio.Queue[WorkflowEvent]) -> None:
        async with self._lock:
            subscribers = self._subscribers.get(diagnosis_id)
            if not subscribers:
                return
            subscribers.discard(queue)
            if not subscribers:
                self._subscribers.pop(diagnosis_id, None)

    async def _replay_events(self, diagnosis_id: str, last_event_id: int | None) -> list[WorkflowEvent]:
        if self.store is not None:
            return await self.store.list_events(diagnosis_id, last_event_id)
        return [
            event
            for event in self._history.get(diagnosis_id, [])
            if last_event_id is None or event.event_id > last_event_id
        ]
