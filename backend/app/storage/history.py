"""SQLite persistence for finished analysis jobs, using only the standard library."""
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Optional


def database_path() -> Path:
    configured = os.getenv("SATQUERY_DB")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[2] / ".data" / "satquery.db"


def _connect() -> sqlite3.Connection:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """CREATE TABLE IF NOT EXISTS history (
            id TEXT PRIMARY KEY,
            created TEXT NOT NULL,
            query TEXT NOT NULL,
            structured_query TEXT NOT NULL,
            aoi TEXT NOT NULL,
            status TEXT NOT NULL,
            result TEXT
        )"""
    )
    return connection


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def save_history_job(job_id: str, created: str, query: str, structured_query: dict,
                     aoi: dict, status: str, result: Optional[dict]) -> None:
    with _connect() as connection:
        connection.execute(
            """INSERT INTO history (id, created, query, structured_query, aoi, status, result)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   created=excluded.created, query=excluded.query,
                   structured_query=excluded.structured_query, aoi=excluded.aoi,
                   status=excluded.status, result=excluded.result""",
            (job_id, created, query, _dump(structured_query), _dump(aoi), status,
             _dump(result) if result is not None else None),
        )


def list_history() -> list[dict]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT id, created, query, structured_query, status FROM history ORDER BY created DESC, id DESC"
        ).fetchall()
    return [
        {"id": row["id"], "created": row["created"], "query": row["query"],
         "status": row["status"], "operation": json.loads(row["structured_query"]).get("operation")}
        for row in rows
    ]


def get_history(job_id: str) -> Optional[dict]:
    with _connect() as connection:
        row = connection.execute("SELECT * FROM history WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "created": row["created"],
        "query": row["query"],
        "structured_query": json.loads(row["structured_query"]),
        "aoi": json.loads(row["aoi"]),
        "status": row["status"],
        "result": json.loads(row["result"]) if row["result"] is not None else None,
    }


def delete_history(job_id: str) -> bool:
    with _connect() as connection:
        cursor = connection.execute("DELETE FROM history WHERE id = ?", (job_id,))
        return cursor.rowcount > 0