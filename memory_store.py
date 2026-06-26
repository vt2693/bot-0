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
        """Download memory.db from HF Hub via huggingface_hub."""
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
        self._conn.commit()
        self._ready = True

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
        # Backup immediately so facts survive crash/git push restarts
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
        return {"total_facts": total, "avg_trust": avg, "top_facts": [self._row(r) for r in top]}

    def status(self) -> dict:
        s = self.stats()
        return {"ready": self.ready, "db_path": self.db_path, "fact_count": s["total_facts"], "avg_trust": s["avg_trust"], "top_facts": s["top_facts"]}

    def close(self) -> None:
        if self._conn:
            self._backup_to_hub()
            self._conn.close()
            self._conn = None
            self._ready = False

    def sync(self) -> None:
        """Explicit backup call (e.g. from a periodic timer)."""
        self._backup_to_hub()
