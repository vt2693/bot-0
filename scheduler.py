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
        self._running_job_ids: set[str] = set()
        # Event-driven dispatch: job_id -> next_run_at for active jobs. A single
        # dispatcher task wakes at the earliest next_run_at so due jobs start
        # promptly instead of waiting for the next 30s poll tick.
        self._timers: dict[str, float] = {}
        self._wake: asyncio.Event = asyncio.Event()
        self._dispatcher_task: asyncio.Task | None = None

    # -- Lifecycle -----------------------------------------------------------

    def start(self) -> None:
        """Open DB conn, catch up missed jobs, begin poll loop."""
        self._conn = self._get_conn()
        self._catch_up_missed_jobs()
        self._running = True
        self._refresh_timers()
        self._poll_task = asyncio.create_task(self._poll_loop())
        self._dispatcher_task = asyncio.create_task(self._dispatcher_loop())
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
        if self._dispatcher_task:
            self._dispatcher_task.cancel()
            try:
                await self._dispatcher_task
            except asyncio.CancelledError:
                pass
            self._dispatcher_task = None
        # Cancel any running job tasks
        if self._running_jobs:
            for t in list(self._running_jobs):
                t.cancel()
            _, pending = await asyncio.wait(self._running_jobs, timeout=5)
            if pending:
                logger.warning("Scheduler: %d jobs did not finish in time", len(pending))
            self._running_jobs.clear()
            self._running_job_ids.clear()
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
                    self._spawn_job(job)
            except Exception as e:
                logger.exception("Scheduler poll loop error: %s", e)
            await asyncio.sleep(POLL_INTERVAL)

    def _clean_finished_jobs(self) -> None:
        self._running_jobs = {t for t in self._running_jobs if not t.done()}

    # -- Event-driven dispatch ------------------------------------------------

    def _refresh_timers(self) -> None:
        """Load active jobs' next_run_at into the timer map (cold-boot path)."""
        self._timers = {}
        cur = self._conn.execute(
            "SELECT id, next_run_at FROM scheduled_jobs WHERE status='active'"
        )
        for r in cur:
            self._timers[r["id"]] = r["next_run_at"]
        self._wake.set()

    def _set_timer(self, job_id: str, next_run_at: float) -> None:
        self._timers[job_id] = next_run_at
        self._wake.set()

    def _clear_timer(self, job_id: str) -> None:
        self._timers.pop(job_id, None)
        self._wake.set()

    async def _dispatcher_loop(self) -> None:
        """Wake at the earliest next_run_at and spawn due jobs promptly.

        The 30s poll sweep remains as a catch-up/cleanup backstop; this loop
        removes the coarse poll granularity for timely dispatch.
        """
        while self._running:
            now = time.time()
            for jid in [jid for jid, t in self._timers.items() if t <= now]:
                job = self.get_job(jid)
                if not job or job["status"] != "active":
                    self._timers.pop(jid, None)
                elif job["next_run_at"] <= now and self._spawn_job(job):
                    self._timers.pop(jid, None)  # _fire_job re-arms via _set_timer
            self._wake.clear()
            nxt = min(self._timers.values()) if self._timers else None
            if nxt is None:
                await self._wake.wait()
            else:
                try:
                    await asyncio.wait_for(
                        self._wake.wait(), timeout=max(0.0, nxt - time.time())
                    )
                except asyncio.TimeoutError:
                    pass

    def _spawn_job(self, job: dict, manual: bool = False) -> bool:
        """Create and track a fire_job task, shared by poll loop and run_now.

        Returns True if spawned, False if the job is already running (prevents
        duplicate concurrent executions from poll+manual overlap or double taps).
        """
        if job["id"] in self._running_job_ids:
            return False
        t = asyncio.create_task(self._fire_job(job, manual=manual))
        self._running_jobs.add(t)
        self._running_job_ids.add(job["id"])
        t.add_done_callback(
            lambda _t: (self._running_jobs.discard(_t), self._running_job_ids.discard(job["id"]))
        )
        return True

    def _fetch_due_jobs(self) -> list[dict]:
        now = time.time()
        cur = self._conn.execute(
            "SELECT * FROM scheduled_jobs WHERE status='active' AND next_run_at <= ?",
            (now,),
        )
        return [self._row_to_dict(r) for r in cur.fetchall()]

    # -- Job execution -------------------------------------------------------

    @staticmethod
    def _daily_next_run(next_run_at: float, now: float | None = None) -> float:
        """Given a daily job's anchor time, return next occurrence at same HH:MM."""
        if now is None:
            now = time.time()
        lt = time.localtime(next_run_at)
        now_lt = time.localtime(now)
        target = int(time.mktime((
            now_lt.tm_year, now_lt.tm_mon, now_lt.tm_mday,
            lt.tm_hour, lt.tm_min, 0, 0, 0, -1
        )))
        return target + 86400 if target <= now else target

    async def _fire_job(self, job: dict, manual: bool = False) -> None:
        """Execute one job: LLM call -> send result -> update DB.

        When manual=True (triggered via Run Now), update last_run/last_result but
        leave next_run_at (and thus the schedule) untouched. A manual run of a
        one-time job marks it completed, since its purpose is fulfilled.
        """
        job_id = job["id"]
        chat_id = job["chat_id"]
        prompt = job["prompt"]
        scope = job.get("scope", "sched_global")
        mode = job.get("mode", "interval")

        logger.info("Job %s: started (manual=%s)", job_id[:8], manual)

        try:
            result = await asyncio.to_thread(
                self._bridge.chat_with_memory, prompt, [], scope
            )
            self._bot._send_message(chat_id, result[:4000])
            now = time.time()
            if manual:
                if mode == "once":
                    self._conn.execute(
                        "UPDATE scheduled_jobs SET last_run_at=?, status='completed', error_count=0, last_result=? WHERE id=?",
                        (now, result[:500], job_id),
                    )
                    self._bot._send_message(chat_id, f"One-time job '{prompt[:60]}' completed.")
                    self._clear_timer(job_id)
                else:
                    self._conn.execute(
                        "UPDATE scheduled_jobs SET last_run_at=?, error_count=0, last_result=? WHERE id=?",
                        (now, result[:500], job_id),
                    )
            elif mode == "once":
                self._conn.execute(
                    "UPDATE scheduled_jobs SET last_run_at=?, status='completed', error_count=0, last_result=? WHERE id=?",
                    (now, result[:500], job_id),
                )
                self._bot._send_message(chat_id, f"One-time job '{prompt[:60]}' completed.")
                self._clear_timer(job_id)
            elif mode == "daily":
                next_run = self._daily_next_run(job["next_run_at"], now)
                self._conn.execute(
                    "UPDATE scheduled_jobs SET last_run_at=?, next_run_at=?, error_count=0, last_result=? WHERE id=?",
                    (now, next_run, result[:500], job_id),
                )
                self._set_timer(job_id, next_run)
            else:  # interval
                interval = job["interval_minutes"]
                next_run = max(now, now + interval * 60)
                self._conn.execute(
                    "UPDATE scheduled_jobs SET last_run_at=?, next_run_at=?, error_count=0, last_result=? WHERE id=?",
                    (now, next_run, result[:500], job_id),
                )
                self._set_timer(job_id, next_run)
            self._conn.commit()
            logger.info("Job %s: OK (chat %s, mode=%s)", job_id[:8], chat_id, mode)
        except Exception as e:
            logger.exception("Job %s failed: %s", job_id[:8], e)
            if manual:
                self._conn.execute(
                    "UPDATE scheduled_jobs SET last_run_at=?, last_result=? WHERE id=?",
                    (time.time(), str(e)[:500], job_id),
                )
                self._conn.commit()
                self._bot._send_message(
                    chat_id, f"⚡ Manual run of '{prompt[:60]}' failed: {e}"
                )
                return
            cur = self._conn.execute(
                "SELECT error_count FROM scheduled_jobs WHERE id=?", (job_id,)
            )
            row = cur.fetchone()
            err_count = (row["error_count"] if row else 0) + 1
            if mode == "once":
                next_run = now + 300  # 5-min backoff
            elif mode == "daily":
                next_run = self._daily_next_run(job["next_run_at"])
            else:
                interval = job["interval_minutes"]
                next_run = max(now, now + interval * 60)
            if err_count >= MAX_ERRORS:
                self._conn.execute(
                    "UPDATE scheduled_jobs SET last_run_at=?, next_run_at=?, error_count=?, status='errored', last_result=? WHERE id=?",
                    (now, next_run, err_count, str(e)[:500], job_id),
                )
                self._bot._send_message(
                    chat_id,
                    f"Job '{prompt[:60]}' paused after {err_count} consecutive failures. Last error: {e}",
                )
                self._clear_timer(job_id)
            else:
                self._conn.execute(
                    "UPDATE scheduled_jobs SET last_run_at=?, next_run_at=?, error_count=?, last_result=? WHERE id=?",
                    (now, next_run, err_count, str(e)[:500], job_id),
                )
                self._set_timer(job_id, next_run)
            self._conn.commit()

    # -- Cold-boot catch-up --------------------------------------------------

    def _catch_up_missed_jobs(self) -> None:
        """Recompute next_run for jobs that fired while we were offline.

        If a job was due >2 intervals ago, skip the missed cycles and just
        push next_run forward.  If it was due within 2 intervals, let it fire
        on the next poll tick.
        Daily-mode jobs always advance to the next occurrence at the same HH:MM.
        """
        now = time.time()
        cur = self._conn.execute(
            "SELECT * FROM scheduled_jobs WHERE status='active'"
        )
        for row in cur:
            job = self._row_to_dict(row)
            mode = job.get("mode", "interval")
            if mode == "once":
                continue
            if mode == "daily":
                next_run = self._daily_next_run(job["next_run_at"], now)
                if next_run != job["next_run_at"]:
                    self._conn.execute(
                        "UPDATE scheduled_jobs SET next_run_at=? WHERE id=?",
                        (next_run, job["id"]),
                    )
                continue
            # Interval mode
            interval_s = job["interval_minutes"] * 60
            next_run = job["next_run_at"]
            if next_run + interval_s * CATCHUP_SKIP_THRESHOLD < now:
                elapsed = now - next_run
                cycles_behind = int(elapsed / interval_s)
                new_next = next_run + (cycles_behind * interval_s)
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
        self._set_timer(job_id, next_run)
        logger.info("Job %s created: chat %s, mode=%s", job_id[:8], chat_id, mode)
        return {"success": True, "id": job_id, "next_run_at": next_run}

    def remove_job(self, job_id: str) -> dict:
        cur = self._conn.execute("DELETE FROM scheduled_jobs WHERE id=?", (job_id,))
        self._conn.commit()
        if cur.rowcount:
            self._memory_store.sync()
            self._clear_timer(job_id)
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
            self._clear_timer(job_id)
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
        self._set_timer(job_id, next_run)
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

    def run_now(self, job_id: str) -> dict:
        """Fire a job immediately without disturbing its schedule.

        Returns {'success': True} or {'error': ...}. The result is delivered
        asynchronously to the job's chat by the spawned _fire_job task.
        """
        job = self.get_job(job_id)
        if not job:
            return {"error": "Job not found"}
        if not self._spawn_job(job, manual=True):
            return {"error": "Job already running"}
        return {"success": True}
