from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from womtrees.config import get_config
from womtrees.models import WorkItem

SCHEMA_VERSION = 1

SCHEMA = """\
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS work_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_name TEXT NOT NULL,
    repo_path TEXT NOT NULL,
    branch TEXT NOT NULL,
    prompt TEXT,
    worktree_path TEXT,
    status TEXT NOT NULL DEFAULT 'todo',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_work_items_repo ON work_items(repo_name);
CREATE INDEX IF NOT EXISTS idx_work_items_status ON work_items(status);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_work_item(row: sqlite3.Row) -> WorkItem:
    return WorkItem(
        id=row["id"],
        repo_name=row["repo_name"],
        repo_path=row["repo_path"],
        branch=row["branch"],
        prompt=row["prompt"],
        worktree_path=row["worktree_path"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    if db_path is None:
        config = get_config()
        config.base_dir.mkdir(parents=True, exist_ok=True)
        db_path = config.base_dir / "womtrees.db"

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    cursor = conn.execute("SELECT version FROM schema_version")
    row = cursor.fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
        conn.commit()


def create_work_item(
    conn: sqlite3.Connection,
    repo_name: str,
    repo_path: str,
    branch: str,
    prompt: str | None = None,
    status: str = "todo",
) -> WorkItem:
    now = _now()
    cursor = conn.execute(
        """INSERT INTO work_items (repo_name, repo_path, branch, prompt, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (repo_name, repo_path, branch, prompt, status, now, now),
    )
    conn.commit()
    return get_work_item(conn, cursor.lastrowid)


def get_work_item(conn: sqlite3.Connection, item_id: int) -> WorkItem | None:
    cursor = conn.execute("SELECT * FROM work_items WHERE id = ?", (item_id,))
    row = cursor.fetchone()
    if row is None:
        return None
    return _row_to_work_item(row)


def list_work_items(
    conn: sqlite3.Connection,
    repo_name: str | None = None,
    status: str | None = None,
) -> list[WorkItem]:
    query = "SELECT * FROM work_items WHERE 1=1"
    params: list = []

    if repo_name is not None:
        query += " AND repo_name = ?"
        params.append(repo_name)

    if status is not None:
        query += " AND status = ?"
        params.append(status)

    query += " ORDER BY id"
    cursor = conn.execute(query, params)
    return [_row_to_work_item(row) for row in cursor.fetchall()]


def update_work_item(conn: sqlite3.Connection, item_id: int, **fields) -> WorkItem | None:
    if not fields:
        return get_work_item(conn, item_id)

    fields["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [item_id]

    conn.execute(f"UPDATE work_items SET {set_clause} WHERE id = ?", values)
    conn.commit()
    return get_work_item(conn, item_id)


def delete_work_item(conn: sqlite3.Connection, item_id: int) -> bool:
    cursor = conn.execute("DELETE FROM work_items WHERE id = ?", (item_id,))
    conn.commit()
    return cursor.rowcount > 0
