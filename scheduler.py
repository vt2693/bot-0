import os
import sys
import time
import json
import uuid
import asyncio
import sqlite3
import logging

logger = logging.getLogger(__name__)

MAX_JOBS_PER_CHAT = 20
POLL_INTERVAL = 30  # seconds between polls
MAX_ERRORS = 3      # consecutive errors before auto-pause
CATCHUP_SKIP_THRESHOLD = 2  # skip missed cycles if >2 intervals behind


class SchedulerEngine:
    """Lightweight in-process scheduler using SQLite persistence.

    Runs an async poll loop that checks for due jobs every POLL_INTERVAL s.
    Jobs are stored in the 'scheduled_jobs' table inside memory.db and are
    included in remote storage backups when memory backup/restore is explicitly used.
    """

    def __init__(self, db_path: str, bridge, bot, memory_store):
        self._db_path = db_path
        self._bridge = bridge
        self._bot = bot
        self._memory_store = memory_store
        self._conn: sqlite3.Connection | None = None
        self._running = False
        self._poll_task: asyncio.Task | None = None
        self._running_jobs: set[asyncio.Task] = set()

    # -- Lifecycle -----------------------------------------------------------

    def start(self) -> None:
        """Open DB conn, catch up missed jobs, begin poll loop."""
        self._conn = self._get_conn()
        self._catch_up_missed_jobs()
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("Scheduler started, polling every %ds", POLL_INTERVAL)

    async def stop(self) -> None:
        """Shut down poll loop and cancel any in-flight job executions."""
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None
        # Cancel any running job tasks
        if self._running_jobs:
            for t in list(self._running_jobs):
                t.cancel()
            _, pending = await asyncio.wait(self._running_jobs, timeout=5)
            if pending:
                logger.warning("Scheduler: %d jobs did not finish in time", len(pending))
            self._running_jobs.clear()
        if self._conn:
            self._conn.close()
            self._conn = None
        logger.info("Scheduler stopped")

    # -- DB helpers ----------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        return dict(row)

    # -- Poll loop -----------------------------------------------------------

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                self._clean_finished_jobs()
                due = self._fetch_due_jobs()
                for job in due:
                    t = asyncio.create_task(self._fire_job(job))
                    self._running_jobs.add(t)
                    t.add_done_callback(self._running_jobs.discard)
            except Exception as e:
                logger.exception("Scheduler poll loop error: %s", e)
            await asyncio.sleep(POLL_INTERVAL)

    def _clean_finished_jobs(self) -> None:
        self._running_jobs = {t for t in self._running_jobs if not t.done()}

    def _fetch_due_jobs(self) -> list[dict]:
        now = time.time()
        cur = self._conn.execute(
            "SELECT * FROM scheduled_jobs WHERE status='active' AND next_run_at <= ?",
            (now,),
        )
        return [self._row_to_dict(r) for r in cur.fetchall()]

    # -- Job execution -------------------------------------------------------

    async def _fire_job(self, job: dict) -> None:
        """Execute one job: LLM call -> send result -> update DB."""
        job_id = job["id"]
        chat_id = job["chat_id"]
        prompt = job["prompt"]
        scope = job.get("scope", "sched_global")
        mode = job.get("mode", "interval")
        now = time.time()
        interval = job["interval_minutes"]

        try:
            result = await asyncio.to_thread(
                self._bridge.chat_with_memory, prompt, [], scope
            )
            self._bot._send_message(chat_id, result[:4000])
            now = time.time()
            if mode == "once":
                self._conn.execute(
                    "UPDATE scheduled_jobs SET last_run_at=?, status='completed', error_count=0, last_result=? WHERE id=?",
                    (now, result[:500], job_id),
                )
                self._bot._send_message(chat_id, f"One-time job '{prompt[:60]}' completed.")
            else:
                next_run = max(now, now + interval * 60)
                self._conn.execute(
                    "UPDATE scheduled_jobs SET last_run_at=?, next_run_at=?, error_count=0, last_result=? WHERE id=?",
                    (now, next_run, result[:500], job_id),
                )
            self._conn.commit()
            logger.info("Job %s: OK (chat %s, mode=%s)", job_id[:8], chat_id, mode)
        except Exception as e:
            logger.exception("Job %s failed: %s", job_id[:8], e)
            cur = self._conn.execute(
                "SELECT error_count FROM scheduled_jobs WHERE id=?", (job_id,)
            )
            row = cur.fetchone()
            err_count = (row["error_count"] if row else 0) + 1
            # 5-min backoff for once mode (interval=0 would give now+0=now)
            next_run = now + 300 if mode == "once" else max(now, now + interval * 60)
            if err_count >= MAX_ERRORS:
                self._conn.execute(
                    "UPDATE scheduled_jobs SET last_run_at=?, next_run_at=?, error_count=?, status='errored', last_result=? WHERE id=?",
                    (now, next_run, err_count, str(e)[:500], job_id),
                )
                self._bot._send_message(
                    chat_id,
                    f"Job '{prompt[:60]}' paused after {err_count} consecutive failures. Last error: {e}",
                )
            else:
                self._conn.execute(
                    "UPDATE scheduled_jobs SET last_run_at=?, next_run_at=?, error_count=?, last_result=? WHERE id=?",
                    (now, next_run, err_count, str(e)[:500], job_id),
                )
            self._conn.commit()

    # -- Cold-boot catch-up --------------------------------------------------

    def _catch_up_missed_jobs(self) -> None:
        """Recompute next_run for jobs that fired while we were offline.

        If a job was due >2 intervals ago, skip the missed cycles and just
        push next_run forward.  If it was due within 2 intervals, let it fire
        on the next poll tick.
        """
        now = time.time()
        cur = self._conn.execute(
            "SELECT * FROM scheduled_jobs WHERE status='active'"
        )
        for row in cur:
            job = self._row_to_dict(row)
            mode = job.get("mode", "interval")
            if mode == "once":
                continue  # skip once-mode (interval=0 would ZeroDivisionError)
            interval_s = job["interval_minutes"] * 60
            next_run = job["next_run_at"]
            # How many intervals behind?
            if next_run + interval_s * CATCHUP_SKIP_THRESHOLD < now:
                # Way behind — skip to current cycle
                elapsed = now - next_run
                cycles_behind = int(elapsed / interval_s)
                new_next = next_run + (cycles_behind * interval_s)
                # Advance one more so it's >= now
                while new_next < now:
                    new_next += interval_s
                self._conn.execute(
                    "UPDATE scheduled_jobs SET next_run_at=? WHERE id=?",
                    (new_next, job["id"]),
                )
                logger.info(
                    "Job %s was %d cycles behind, skipping to next run at %.0f",
                    job["id"][:8], cycles_behind, new_next,
                )
            # else: within threshold, fires on next poll tick naturally
        self._conn.commit()

    # -- CRUD ----------------------------------------------------------------

    def add_job(self, chat_id: int, prompt: str, interval_minutes: float,
                 mode: str = "interval", absolute_epoch: float | None = None) -> dict:
        """Create a new scheduled job. Returns {'success': True, 'id': ...} or {'error': ...}."""
        prompt = (prompt or "").strip()
        if not prompt:
            return {"error": "Prompt cannot be empty"}
        if mode == "interval" and interval_minutes < 1:
            return {"error": "Interval must be at least 1 minute"}

        # Enforce per-chat limit
        cur = self._conn.execute(
            "SELECT COUNT(*) AS cnt FROM scheduled_jobs WHERE chat_id=? AND status IN ('active','paused')",
            (chat_id,),
        )
        count = cur.fetchone()["cnt"]
        if count >= MAX_JOBS_PER_CHAT:
            return {"error": f"Max {MAX_JOBS_PER_CHAT} jobs per chat reached"}

        job_id = uuid.uuid4().hex[:12]
        now = time.time()
        if mode in ("once", "daily"):
            if absolute_epoch is None:
                return {"error": "absolute_epoch required for once/daily mode"}
            next_run = absolute_epoch
        else:
            next_run = now + interval_minutes * 60
        self._conn.execute(
            "INSERT INTO scheduled_jobs(id,chat_id,prompt,interval_minutes,mode,status,created_at,next_run_at,scope) VALUES(?,?,?,?,?,'active',?,?,'sched_global')",
            (job_id, chat_id, prompt, interval_minutes, mode, now, next_run),
        )
        self._conn.commit()
        self._memory_store.sync()
        logger.info("Job %s created: chat %s, mode=%s", job_id[:8], chat_id, mode)
        return {"success": True, "id": job_id, "next_run_at": next_run}

    def remove_job(self, job_id: str) -> dict:
        cur = self._conn.execute("DELETE FROM scheduled_jobs WHERE id=?", (job_id,))
        self._conn.commit()
        if cur.rowcount:
            self._memory_store.sync()
            return {"success": True}
        return {"error": "Job not found"}

    def pause_job(self, job_id: str) -> dict:
        cur = self._conn.execute(
            "UPDATE scheduled_jobs SET status='paused' WHERE id=? AND status='active'",
            (job_id,),
        )
        self._conn.commit()
        if cur.rowcount:
            self._memory_store.sync()
            return {"success": True}
        return {"error": "Job not found or already paused"}

    def resume_job(self, job_id: str) -> dict:
        now = time.time()
        cur = self._conn.execute(
            "SELECT interval_minutes FROM scheduled_jobs WHERE id=? AND status='paused'",
            (job_id,),
        )
        row = cur.fetchone()
        if not row:
            return {"error": "Job not found or not paused"}
        next_run = now + row["interval_minutes"] * 60
        self._conn.execute(
            "UPDATE scheduled_jobs SET status='active', next_run_at=?, error_count=0 WHERE id=?",
            (next_run, job_id),
        )
        self._conn.commit()
        self._memory_store.sync()
        return {"success": True, "next_run_at": next_run}

    def list_jobs(self, chat_id: int) -> list[dict]:
        cur = self._conn.execute(
            "SELECT * FROM scheduled_jobs WHERE chat_id=? ORDER BY created_at DESC",
            (chat_id,),
        )
        return [self._row_to_dict(r) for r in cur.fetchall()]

    def get_job(self, job_id: str) -> dict | None:
        cur = self._conn.execute(
            "SELECT * FROM scheduled_jobs WHERE id=?", (job_id,)
        )
        row = cur.fetchone()
        return self._row_to_dict(row) if row else None
