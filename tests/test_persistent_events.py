import asyncio
import unittest

from app.events import WorkflowEventBus
from app.storage.postgres_store import diagnosis_sessions_table, users_table, workflow_events_table


class FakeEventStore:
    def __init__(self):
        self.events = []
        self.sessions = {}

    async def create_session(self, session_id, diagnosis_id, title, user_id=None, metadata=None):
        self.sessions[session_id] = {
            "session_id": session_id,
            "diagnosis_id": diagnosis_id,
            "title": title,
            "user_id": user_id,
            "metadata": metadata or {},
        }

    async def save_event(self, event):
        persisted = event.model_copy(update={"event_id": len(self.events) + 1})
        self.events.append(persisted)
        return persisted

    async def list_events(self, diagnosis_id, after_event_id=None):
        return [
            event
            for event in self.events
            if event.diagnosis_id == diagnosis_id and (after_event_id is None or event.event_id > after_event_id)
        ]


class PersistentWorkflowEventTests(unittest.IsolatedAsyncioTestCase):
    async def test_replays_events_from_store_after_bus_recreation(self):
        store = FakeEventStore()
        first_bus = WorkflowEventBus(store=store)
        await first_bus.publish("diag-1", "diagnosis_created", "created", stage="workflow", status="created")
        await first_bus.publish("diag-1", "diagnosis_started", "started", stage="workflow", status="running")

        second_bus = WorkflowEventBus(store=store)
        replay = []
        async for event in second_bus.subscribe("diag-1"):
            replay.append(event)
            if len(replay) == 2:
                break

        self.assertEqual([event.event for event in replay], ["diagnosis_created", "diagnosis_started"])
        self.assertEqual([event.event_id for event in replay], [1, 2])

    async def test_last_event_id_only_replays_newer_events(self):
        store = FakeEventStore()
        bus = WorkflowEventBus(store=store)
        await bus.publish("diag-1", "diagnosis_created", "created")
        await bus.publish("diag-1", "stage_started", "planning")
        await bus.publish("diag-1", "stage_completed", "done")

        replay = []
        async for event in bus.subscribe("diag-1", last_event_id=1):
            replay.append(event)
            if len(replay) == 2:
                break

        self.assertEqual([event.event for event in replay], ["stage_started", "stage_completed"])


class PostgresSchemaTests(unittest.TestCase):
    def test_session_and_event_tables_include_user_and_replay_columns(self):
        self.assertIn("user_id", users_table.c)
        self.assertIn("session_id", diagnosis_sessions_table.c)
        self.assertIn("user_id", diagnosis_sessions_table.c)
        self.assertIn("diagnosis_id", workflow_events_table.c)
        self.assertIn("event_id", workflow_events_table.c)
        self.assertIn("payload", workflow_events_table.c)


if __name__ == "__main__":
    unittest.main()
