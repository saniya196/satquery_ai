"""Persistent job storage for in-progress and finished analysis jobs."""
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_lock = threading.Lock()

VALID_TRANSITIONS = {
    "queued": {"queued", "processing", "interrupted", "failed"},
    "processing": {"processing", "completed", "failed", "interrupted"},
    "completed": {"completed"},
    "failed": {"failed"},
    "interrupted": {"interrupted"},
}


def database_path() -> Path:
    configured = os.getenv("SATQUERY_JOBS_DB") or os.getenv("SATQUERY_DB")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[2] / ".data" / "satquery.db"


def _connect() -> sqlite3.Connection:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute(
        """CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            created TEXT NOT NULL,
            updated TEXT NOT NULL,
            status TEXT NOT NULL,
            query TEXT,
            structured_query TEXT,
            aoi TEXT,
            stages TEXT,
            provider_info TEXT,
            error TEXT,
            result_ref TEXT,
            finished TEXT,
            progress TEXT,
            artifacts_ref TEXT,
            result_summary TEXT
        )"""
    )
    # Migrate if columns missing
    cols = {r[1] for r in connection.execute("PRAGMA table_info(jobs)").fetchall()}
    for c in ("progress", "artifacts_ref", "result_summary"):
        if c not in cols:
            try:
                connection.execute(f"ALTER TABLE jobs ADD COLUMN {c} TEXT")
            except Exception:
                pass
    return connection



def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _load(v):
    if v is None:
        return None
    try:
        return json.loads(v)
    except Exception:
        return v


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_job(job_id: str, query: str, structured_query: dict, aoi: dict) -> None:
    now = _now()
    with _lock:
        with _connect() as conn:
            conn.execute(
                """INSERT INTO jobs (id, created, updated, status, query, structured_query, aoi, stages, provider_info, error, result_ref, finished, progress)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                       updated=excluded.updated""",
                (job_id, now, now, "queued", query, _dump(structured_query), _dump(aoi),
                 _dump([]), None, None, None, None, _dump({"percent": 0})),
            )
            # ensure columns exist
            cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()}
            for c in ("artifacts_ref", "result_summary"):
                if c not in cols:
                    try:
                        conn.execute(f"ALTER TABLE jobs ADD COLUMN {c} TEXT")
                    except Exception:
                        pass




def _can_transition(old: str, new: str) -> bool:
    if old == new:
        return True
    allowed = VALID_TRANSITIONS.get(old, set())
    return new in allowed


def update_job(job_id: str, **kwargs) -> None:
    if not kwargs:
        return
    now = _now()
    sets = []
    params = []
    new_status = kwargs.get("status")
    if new_status is not None:
        with _lock:
            with _connect() as conn:
                row = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
                if row and not _can_transition(row["status"], new_status):
                    kwargs = dict(kwargs)
                    kwargs.pop("status", None)
                    new_status = None
    if not kwargs:
        return
    for k, v in kwargs.items():
        if k in ("stages", "provider_info", "error", "result_ref", "structured_query", "aoi", "query", "progress", "artifacts_ref"):
            sets.append(f"{k}=?")
            params.append(_dump(v) if v is not None else None)
        elif k in ("status", "finished"):
            sets.append(f"{k}=?")
            params.append(v)
    if not sets:
        return
    sets.append("updated=?")
    params.append(now)
    params.append(job_id)
    sql = f"UPDATE jobs SET {', '.join(sets)} WHERE id=?"
    with _lock:
        with _connect() as conn:
            try:
                conn.execute(sql, params)
            except Exception:
                pass


def get_job(job_id: str) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        return None
    return {
        "job_id": row["id"],
        "status": row["status"],
        "created": row["created"],
        "updated": row["updated"],
        "finished": row["finished"],
        "query": row["query"],
        "structured_query": _load(row["structured_query"]),
        "aoi": _load(row["aoi"]),
        "stages": _load(row["stages"]) or [],
        "provider_info": _load(row["provider_info"]),
        "error": _load(row["error"]),
        "result_ref": _load(row["result_ref"]),
        "progress": _load(row["progress"]) if "progress" in row.keys() else None,
    }


def list_jobs(limit: int = 100) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute("SELECT id, status, created, updated, finished FROM jobs ORDER BY created DESC LIMIT ?", (limit,)).fetchall()
    return [{"job_id": r["id"], "status": r["status"], "created": r["created"], "updated": r["updated"], "finished": r["finished"]} for r in rows]


def mark_interrupted_on_startup() -> int:
    now = _now()
    count = 0
    with _lock:
        with _connect() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                cur = conn.execute("SELECT id FROM jobs WHERE status IN ('queued','processing')")
                rows = cur.fetchall()
                for r in rows:
                    job_id = r["id"]
                    err = {"code": "interrupted", "message": "Job interrupted due to backend restart."}
                    conn.execute("UPDATE jobs SET status=?, error=?, finished=?, updated=? WHERE id=? AND status IN ('queued','processing')",
                                 ("interrupted", _dump(err), now, now, job_id))
                    count += 1
                conn.execute("COMMIT")
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
    return count

