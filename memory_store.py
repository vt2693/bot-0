import json
import time
import os
import sqlite3
import logging
import threading
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class MemoryStore:
    def __init__(self, db_path: str):
        self.db_path = db_path or ":memory:"
        self._lock = threading.Lock()
        self._ready = False
        self._conn: Optional[sqlite3.Connection] = None
        self._restore_backup()
        self._init_db()

    @property
    def ready(self) -> bool:
        return self._ready

    @staticmethod
    def _space_id() -> str:
        return os.getenv("MEMORY_SPACE_ID", "") or os.getenv("SPACE_ID", "") or "vt2693/bot-0"

    @staticmethod
    def _token() -> str:
        return os.getenv("HF_TOKEN", "") or os.getenv("HUGGINGFACE_TOKEN", "")

    def _restore_backup(self) -> None:
        """Download memory.db from HF Hub via huggingface_hub when explicitly enabled."""
        if os.getenv("MEMORY_RESTORE_ON_STARTUP", "false").lower() not in ("true", "1", "yes"):
            logger.info("Memory: startup restore disabled")
            return
        dbp = Path(self.db_path)
        if dbp.exists() and dbp.stat().st_size > 0:
            logger.info("Memory: existing db %s (%d bytes)", dbp, dbp.stat().st_size)
            return
        space = self._space_id()
        token = self._token()
        if not token or "/" not in space:
            return
        try:
            from huggingface_hub import hf_hub_download
            path = hf_hub_download(repo_id=space, repo_type="space", filename="data/memory.db", token=token)
            if path and Path(path).stat().st_size > 0:
                import shutil
                shutil.copy2(path, str(dbp))
                logger.info("Memory: restored %d bytes from HF Hub", Path(path).stat().st_size)
        except Exception:
            logger.info("Memory: no backup on HF Hub yet")

    def _backup_to_hub(self) -> None:
        """Upload memory.db snapshot to HF Hub via huggingface_hub."""
        try:
            db = Path(self.db_path)
            if not db.exists() or db.stat().st_size == 0:
                return
            space = self._space_id()
            token = self._token()
            if not token or "/" not in space:
                return
            # VACUUM INTO temp for consistent snapshot
            import tempfile
            tmpname = tempfile.mktemp(suffix=".db")
            try:
                with self._lock:
                    self._conn.execute(f"VACUUM INTO '{tmpname}'")
                # Upload via huggingface_hub
                from huggingface_hub import HfApi
                api = HfApi()
                api.upload_file(
                    path_or_fileobj=tmpname,
                    path_in_repo="data/memory.db",
                    repo_id=space,
                    repo_type="space",
                    token=token,
                    revision="memory-backups",
                )
                logger.info("Memory: backed up %d bytes to HF Hub", db.stat().st_size)
            finally:
                try: os.unlink(tmpname)
                except: pass
        except Exception as e:
            logger.error("Memory backup failed: %s", e)

    def _init_db(self) -> None:
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scope TEXT NOT NULL DEFAULT 'global',
                content TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}',
                trust_score REAL NOT NULL DEFAULT 0.5,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                access_count INTEGER NOT NULL DEFAULT 0
            )
        """)
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_facts_scope ON facts(scope)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_facts_created ON facts(created_at)")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS skills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                problem TEXT NOT NULL,
                procedure TEXT NOT NULL,
                evidence TEXT DEFAULT '',
                failure_pattern TEXT DEFAULT '',
                tags TEXT DEFAULT '[]',
                scope TEXT NOT NULL DEFAULT 'global',
                status TEXT NOT NULL DEFAULT 'unverified',
                access_count INTEGER DEFAULT 0,
                injection_count INTEGER DEFAULT 0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_skills_scope ON skills(scope)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_skills_status ON skills(status)")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_jobs (
                id TEXT PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                prompt TEXT NOT NULL,
                interval_minutes REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at REAL NOT NULL,
                last_run_at REAL,
                next_run_at REAL NOT NULL,
                last_result TEXT,
                error_count INTEGER DEFAULT 0,
                scope TEXT DEFAULT 'sched_global'
            )
        """)
        self._conn.commit()
        self._ready = True

    def open_conn(self) -> sqlite3.Connection:
        """Return a fresh connection to the same DB (for SchedulerEngine)."""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _row(self, row: sqlite3.Row) -> dict:
        return {
            "id": row["id"], "scope": row["scope"], "content": row["content"],
            "metadata": json.loads(row["metadata"] or "{}"),
            "trust_score": row["trust_score"], "created_at": row["created_at"],
            "updated_at": row["updated_at"], "access_count": row["access_count"],
        }

    def add(self, content: str, scope: str = "global", metadata: dict | None = None) -> int:
        content = (content or "").strip()[:1000]
        if not content:
            return -1
        now = time.time()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO facts(scope,content,metadata,created_at,updated_at) VALUES(?,?,?,?,?)",
                (scope or "global", content, json.dumps(metadata or {}), now, now),
            )
            self._conn.commit()
            rowid = int(cur.lastrowid)
        # Backup immediately for deployments that opt into HF Hub restore.
        self._backup_to_hub()
        return rowid

    def search(self, query: str, scope: str | None = "global", limit: int = 5) -> list[dict]:
        q = f"%{(query or '').strip()}%"
        if not query:
            return self._recent_facts(scope, limit)
        if scope:
            sql = "SELECT * FROM facts WHERE scope=? AND content LIKE ? ORDER BY created_at DESC LIMIT ?"
            params = (scope, q, limit)
        else:
            sql = "SELECT * FROM facts WHERE content LIKE ? ORDER BY created_at DESC LIMIT ?"
            params = (q, limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
            ids = [r["id"] for r in rows]
            if ids:
                self._conn.execute(f"UPDATE facts SET access_count=access_count+1 WHERE id IN ({','.join('?' for _ in ids)})", ids)
                self._conn.commit()
        return [self._row(r) for r in rows]

    def _recent_facts(self, scope: str | None, limit: int) -> list[dict]:
        if scope:
            sql = "SELECT * FROM facts WHERE scope=? ORDER BY created_at DESC LIMIT ?"
            params = (scope, limit)
        else:
            sql = "SELECT * FROM facts ORDER BY created_at DESC LIMIT ?"
            params = (limit,)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [self._row(r) for r in rows]

    def get_relevant(self, query: str, scope: str = "global", limit: int = 5) -> list[dict]:
        words = [w for w in (query or "").lower().split() if len(w) > 3]
        results = []
        for w in words[:4]:
            results.extend(self.search(w, scope, limit))
        seen, out = set(), []
        for r in results:
            if r["id"] not in seen:
                seen.add(r["id"]); out.append(r)
        return out[:limit] or self._recent_facts(scope, limit)

    def probe(self, entity: str, scope: str = "global") -> dict:
        return {"entity": entity, "results": self.search(entity, scope, 5)}

    def reason(self, query: str, scope: str = "global", limit: int = 5) -> dict:
        return {"query": query, "results": self.get_relevant(query, scope, limit)}

    def add_feedback(self, content: str, feedback: str, scope: str = "global") -> bool:
        delta = 0.05 if "good" in (feedback or "").lower() or "+" in (feedback or "") else -0.10
        with self._lock:
            cur = self._conn.execute(
                "UPDATE facts SET trust_score=max(0,min(1,trust_score+?)), updated_at=? WHERE scope=? AND content LIKE ?",
                (delta, time.time(), scope, f"%{content[:120]}%"),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def clear(self, scope: str | None = "global") -> None:
        with self._lock:
            if scope:
                self._conn.execute("DELETE FROM facts WHERE scope=?", (scope,))
            else:
                self._conn.execute("DELETE FROM facts")
            self._conn.commit()
        self._backup_to_hub()

    def cleanup_low_trust(self) -> int:
        with self._lock:
            cur = self._conn.execute("DELETE FROM facts WHERE trust_score < 0.2")
            self._conn.commit()
            return cur.rowcount

    def stats(self) -> dict:
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
            avg = self._conn.execute("SELECT COALESCE(AVG(trust_score),0) FROM facts").fetchone()[0]
            top = self._conn.execute("SELECT * FROM facts ORDER BY created_at DESC LIMIT 10").fetchall()
            skill_count = self._conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
            active_skills = self._conn.execute("SELECT COUNT(*) FROM skills WHERE status='active'").fetchone()[0]
            unverified_skills = self._conn.execute("SELECT COUNT(*) FROM skills WHERE status='unverified'").fetchone()[0]
            inactive_skills = self._conn.execute("SELECT COUNT(*) FROM skills WHERE status='inactive'").fetchone()[0]
        return {"total_facts": total, "avg_trust": avg, "top_facts": [self._row(r) for r in top], "skill_count": skill_count, "active_skills": active_skills, "unverified_skills": unverified_skills, "inactive_skills": inactive_skills}

    def status(self) -> dict:
        s = self.stats()
        return {"ready": self.ready, "db_path": self.db_path, "fact_count": s["total_facts"], "avg_trust": s["avg_trust"], "top_facts": s["top_facts"], "skill_count": s["skill_count"], "active_skills": s["active_skills"], "unverified_skills": s["unverified_skills"], "inactive_skills": s["inactive_skills"]}

    def close(self) -> None:
        if self._conn:
            self._backup_to_hub()
            self._conn.close()
            self._conn = None
            self._ready = False

    def sync(self) -> None:
        """Explicit backup call (e.g. from a periodic timer)."""
        self._backup_to_hub()

    # -- Skills -------------------------------------------------------------------

    def _skill_row(self, row: sqlite3.Row) -> dict:
        return {
            "id": row["id"], "title": row["title"], "problem": row["problem"],
            "procedure": row["procedure"], "evidence": row["evidence"],
            "failure_pattern": row["failure_pattern"],
            "tags": json.loads(row["tags"] or "[]"),
            "scope": row["scope"], "status": row["status"],
            "access_count": row["access_count"],
            "injection_count": row["injection_count"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    def skill_add(self, title: str, problem: str, procedure: str,
                  failure_pattern: str = "", tags: list | None = None,
                  scope: str = "global") -> dict:
        """Add a skill. Upserts on normalized title match."""
        title = (title or "").strip()[:300]
        if not title or not procedure:
            return {"id": -1, "error": "title and procedure required"}
        norm = title.lower().strip()
        now = time.time()
        with self._lock:
            existing = self._conn.execute(
                "SELECT id FROM skills WHERE LOWER(TRIM(title))=?", (norm,)
            ).fetchone()
            if existing:
                self._conn.execute(
                    "UPDATE skills SET access_count=access_count+1, updated_at=? WHERE id=?",
                    (now, existing["id"]),
                )
                self._conn.commit()
                return {"id": existing["id"], "error": ""}
            cur = self._conn.execute(
                "INSERT INTO skills(title,problem,procedure,evidence,failure_pattern,tags,scope,created_at,updated_at)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (title, problem, procedure, "", failure_pattern,
                 json.dumps(tags or []), scope, now, now),
            )
            self._conn.commit()
            rowid = int(cur.lastrowid)
        self._backup_to_hub()
        return {"id": rowid, "error": ""}

    def skill_search(self, query: str, scope: str | None = "global",
                     limit: int = 5) -> list[dict]:
        """LIKE-based token match on title + problem + tags. Excludes inactive."""
        words = [w for w in (query or "").lower().split() if len(w) > 2]
        if not words:
            return [s for s in self.skill_list(scope) if s["status"] != "inactive"][:limit]
        results = []
        with self._lock:
            for word in words[:5]:
                q = f"%{word}%"
                if scope:
                    sql = ("SELECT * FROM skills WHERE scope=? AND status!='inactive' "
                           "AND (LOWER(title) LIKE ? OR LOWER(problem) LIKE ? OR LOWER(tags) LIKE ?) "
                           "ORDER BY access_count DESC, created_at DESC LIMIT ?")
                    params = (scope, q, q, q, limit)
                else:
                    sql = ("SELECT * FROM skills WHERE status!='inactive' "
                           "AND (LOWER(title) LIKE ? OR LOWER(problem) LIKE ? OR LOWER(tags) LIKE ?) "
                           "ORDER BY access_count DESC, created_at DESC LIMIT ?")
                    params = (q, q, q, limit)
                results.extend(self._conn.execute(sql, params).fetchall())
        seen, out = set(), []
        for r in results:
            if r["id"] not in seen:
                seen.add(r["id"])
                out.append(self._skill_row(r))
        return out[:limit]

    def skill_list(self, scope: str | None = "global") -> list[dict]:
        if scope:
            sql = "SELECT * FROM skills WHERE scope=? ORDER BY created_at DESC"
            params = (scope,)
        else:
            sql = "SELECT * FROM skills ORDER BY created_at DESC"
            params = ()
        with self._lock:
            return [self._skill_row(r)
                    for r in self._conn.execute(sql, params).fetchall()]

    def skill_get(self, skill_id: int) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM skills WHERE id=?", (skill_id,)
            ).fetchone()
            return self._skill_row(row) if row else None

    def skill_update(self, skill_id: int, **fields) -> bool:
        allowed = {"title", "problem", "procedure", "failure_pattern",
                   "tags", "status"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if "tags" in updates and not isinstance(updates["tags"], str):
            updates["tags"] = json.dumps(updates["tags"] or [])
        if not updates:
            return False
        now = time.time()
        updates["updated_at"] = now
        sets = ", ".join(f"{k}=?" for k in updates)
        vals = list(updates.values()) + [skill_id]
        with self._lock:
            self._conn.execute(
                f"UPDATE skills SET {sets} WHERE id=?", vals
            )
            self._conn.commit()
            rc = self._conn.execute(
                "SELECT changes()"
            ).fetchone()[0]
        if rc:
            self._backup_to_hub()
        return rc > 0

    def skill_remove(self, skill_id: int) -> bool:
        with self._lock:
            self._conn.execute("DELETE FROM skills WHERE id=?", (skill_id,))
            self._conn.commit()
            rc = self._conn.execute("SELECT changes()").fetchone()[0]
        if rc:
            self._backup_to_hub()
        return rc > 0

    def skill_inject(self, query: str, scope: str = "global",
                     limit: int = 3) -> list[dict]:
        """Search + increment injection_count. For injection pipeline."""
        with self._lock:
            self._conn.execute(
                "UPDATE skills SET status='inactive' "
                "WHERE status!='inactive' AND injection_count>=3 AND access_count=0"
            )
            self._conn.commit()
        skills = self.skill_search(query, scope, limit)
        if skills:
            ids = [s["id"] for s in skills]
            now = time.time()
            with self._lock:
                self._conn.execute(
                    f"UPDATE skills SET injection_count=injection_count+1, "
                    f"updated_at=? WHERE id IN "
                    f"({','.join('?' for _ in ids)})",
                    [now] + ids,
                )
                self._conn.commit()
        return skills

    def skill_record_usage(self, skill_id: int) -> bool:
        with self._lock:
            self._conn.execute(
                "UPDATE skills SET access_count=access_count+1, "
                "status='active', updated_at=? WHERE id=?",
                (time.time(), skill_id),
            )
            self._conn.commit()
            return self._conn.execute(
                "SELECT changes()"
            ).fetchone()[0] > 0
