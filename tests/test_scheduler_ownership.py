import asyncio
import tempfile
import unittest
from pathlib import Path

from memory_store import MemoryStore
from scheduler import SchedulerEngine


class StubBridge:
    async def chat_with_memory(self, *args, **kwargs):
        return "ok"


class StubBot:
    def _send_message(self, *_args, **_kwargs):
        pass


class SchedulerOwnershipCharacterizationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self._tmp.name) / "memory.db")
        self.store = MemoryStore(self.db_path)
        self.scheduler = SchedulerEngine(self.db_path, StubBridge(), StubBot(), self.store)
        self.scheduler.start()

    async def asyncTearDown(self):
        await self.scheduler.stop()
        self.store.close()
        self._tmp.cleanup()

    async def test_new_jobs_use_chat_owned_scheduler_scope(self):
        result = self.scheduler.add_job(101, "User A task", 15)
        self.assertTrue(result.get("success"))

        job = self.scheduler.get_job(result["id"])

        self.assertEqual(job["chat_id"], 101)
        self.assertEqual(job["scope"], "101")

    async def test_job_controls_require_owner_chat_id(self):
        result = self.scheduler.add_job(101, "User A task", 15)
        job_id = result["id"]

        self.assertEqual(self.scheduler.pause_job(job_id, chat_id=202).get("error"), "Job not found or not owned by chat")
        self.assertEqual(self.scheduler.run_now(job_id, chat_id=202).get("error"), "Job not found or not owned by chat")
        self.assertEqual(self.scheduler.remove_job(job_id, chat_id=202).get("error"), "Job not found or not owned by chat")

        self.assertEqual(self.scheduler.pause_job(job_id, chat_id=101).get("success"), True)
        self.assertEqual(self.scheduler.resume_job(job_id, chat_id=101).get("success"), True)
        self.assertEqual(self.scheduler.remove_job(job_id, chat_id=101).get("success"), True)


if __name__ == "__main__":
    unittest.main()
