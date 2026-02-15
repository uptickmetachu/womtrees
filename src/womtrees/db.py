from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from womtrees.config import get_config
from womtrees.models import ClaudeSession, PullRequest, WorkItem

SCHEMA_VERSION = 6

SCHEMA = """\
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS work_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_name TEXT NOT NULL,
    repo_path TEXT NOT NULL,
    branch TEXT NOT NULL,
    name TEXT,
    prompt TEXT,
    worktree_path TEXT,
    tmux_session TEXT,
    status TEXT NOT NULL DEFAULT 'todo',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_work_items_repo ON work_items(repo_name);
CREATE INDEX IF NOT EXISTS idx_work_items_status ON work_items(status);

CREATE TABLE IF NOT EXISTS claude_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_item_id INTEGER REFERENCES work_items(id),
    repo_name TEXT NOT NULL,
    repo_path TEXT NOT NULL,
    branch TEXT NOT NULL,
    tmux_session TEXT NOT NULL,
    tmux_pane TEXT NOT NULL,
    pid INTEGER,
    state TEXT NOT NULL DEFAULT 'working',
    prompt TEXT,
    claude_session_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_claude_sessions_work_item ON claude_sessions(work_item_id);
CREATE INDEX IF NOT EXISTS idx_claude_sessions_state ON claude_sessions(state);

CREATE TABLE IF NOT EXISTS pull_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_item_id INTEGER NOT NULL REFERENCES work_items(id),
    number INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    owner TEXT NOT NULL,
    repo TEXT NOT NULL,
    url TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pull_requests_work_item ON pull_requests(work_item_id);
"""

MIGRATIONS = {
    2: ["ALTER TABLE work_items ADD COLUMN tmux_session TEXT"],
    3: [
        """CREATE TABLE IF NOT EXISTS claude_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            work_item_id INTEGER REFERENCES work_items(id),
            repo_name TEXT NOT NULL,
            repo_path TEXT NOT NULL,
            branch TEXT NOT NULL,
            tmux_session TEXT NOT NULL,
            tmux_pane TEXT NOT NULL,
            pid INTEGER,
            state TEXT NOT NULL DEFAULT 'working',
            prompt TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_claude_sessions_work_item ON claude_sessions(work_item_id)",
        "CREATE INDEX IF NOT EXISTS idx_claude_sessions_state ON claude_sessions(state)",
    ],
    4: ["ALTER TABLE claude_sessions ADD COLUMN claude_session_id TEXT"],
    5: ["ALTER TABLE work_items ADD COLUMN name TEXT"],
    6: [
        """CREATE TABLE IF NOT EXISTS pull_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            work_item_id INTEGER NOT NULL REFERENCES work_items(id),
            number INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            owner TEXT NOT NULL,
            repo TEXT NOT NULL,
            url TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_pull_requests_work_item ON pull_requests(work_item_id)",
    ],
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_work_item(row: sqlite3.Row) -> WorkItem:
    return WorkItem(
        id=row["id"],
        repo_name=row["repo_name"],
        repo_path=row["repo_path"],
        branch=row["branch"],
        name=row["name"],
        prompt=row["prompt"],
        worktree_path=row["worktree_path"],
        tmux_session=row["tmux_session"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_pull_request(row: sqlite3.Row) -> PullRequest:
    return PullRequest(
        id=row["id"],
        work_item_id=row["work_item_id"],
        number=row["number"],
        status=row["status"],
        owner=row["owner"],
        repo=row["repo"],
        url=row["url"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_claude_session(row: sqlite3.Row) -> ClaudeSession:
    return ClaudeSession(
        id=row["id"],
        work_item_id=row["work_item_id"],
        repo_name=row["repo_name"],
        repo_path=row["repo_path"],
        branch=row["branch"],
        tmux_session=row["tmux_session"],
        tmux_pane=row["tmux_pane"],
        pid=row["pid"],
        state=row["state"],
        prompt=row["prompt"],
        claude_session_id=row["claude_session_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@contextmanager
def connection(
    db_path: Path | None = None,
) -> Generator[sqlite3.Connection, None, None]:
    """Context manager that opens and closes a DB connection."""
    conn = get_connection(db_path)
    try:
        yield conn
    finally:
        conn.close()


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
        conn.execute(
            "INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,)
        )
        conn.commit()
    else:
        current = row["version"]
        for version in sorted(MIGRATIONS):
            if current < version:
                for sql in MIGRATIONS[version]:
                    try:
                        conn.execute(sql)
                    except sqlite3.OperationalError:
                        pass  # Table/column already exists
                conn.execute("UPDATE schema_version SET version = ?", (version,))
                conn.commit()


# -- WorkItem CRUD --


def create_work_item(
    conn: sqlite3.Connection,
    repo_name: str,
    repo_path: str,
    branch: str,
    prompt: str | None = None,
    status: str = "todo",
    name: str | None = None,
) -> WorkItem:
    # Guard against duplicate active branches in the same repo
    cursor = conn.execute(
        "SELECT id FROM work_items WHERE repo_name = ? AND branch = ? AND status != 'done'",
        (repo_name, branch),
    )
    existing = cursor.fetchone()
    if existing:
        raise ValueError(
            f"Branch '{branch}' already has an active work item (#{existing['id']})"
        )

    now = _now()
    cursor = conn.execute(
        """INSERT INTO work_items (repo_name, repo_path, branch, name, prompt, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (repo_name, repo_path, branch, name, prompt, status, now, now),
    )
    conn.commit()
    assert cursor.lastrowid is not None
    item = get_work_item(conn, cursor.lastrowid)
    assert item is not None
    return item


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
    params: list[str] = []

    if repo_name is not None:
        query += " AND repo_name = ?"
        params.append(repo_name)

    if status is not None:
        query += " AND status = ?"
        params.append(status)

    query += " ORDER BY id"
    cursor = conn.execute(query, params)
    return [_row_to_work_item(row) for row in cursor.fetchall()]


def update_work_item(
    conn: sqlite3.Connection, item_id: int, **fields: object
) -> WorkItem | None:
    if not fields:
        return get_work_item(conn, item_id)

    fields["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [item_id]

    conn.execute(f"UPDATE work_items SET {set_clause} WHERE id = ?", values)
    conn.commit()
    return get_work_item(conn, item_id)


def delete_work_item(conn: sqlite3.Connection, item_id: int) -> bool:
    conn.execute("DELETE FROM claude_sessions WHERE work_item_id = ?", (item_id,))
    cursor = conn.execute("DELETE FROM work_items WHERE id = ?", (item_id,))
    conn.commit()
    return cursor.rowcount > 0


# -- ClaudeSession CRUD --


def create_claude_session(
    conn: sqlite3.Connection,
    repo_name: str,
    repo_path: str,
    branch: str,
    tmux_session: str,
    tmux_pane: str,
    pid: int | None = None,
    work_item_id: int | None = None,
    state: str = "working",
    prompt: str | None = None,
    claude_session_id: str | None = None,
) -> ClaudeSession:
    now = _now()
    cursor = conn.execute(
        """INSERT INTO claude_sessions
           (work_item_id, repo_name, repo_path, branch, tmux_session, tmux_pane, pid, state, prompt, claude_session_id, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            work_item_id,
            repo_name,
            repo_path,
            branch,
            tmux_session,
            tmux_pane,
            pid,
            state,
            prompt,
            claude_session_id,
            now,
            now,
        ),
    )
    conn.commit()
    assert cursor.lastrowid is not None
    session = get_claude_session(conn, cursor.lastrowid)
    assert session is not None
    return session


def get_claude_session(
    conn: sqlite3.Connection, session_id: int
) -> ClaudeSession | None:
    cursor = conn.execute("SELECT * FROM claude_sessions WHERE id = ?", (session_id,))
    row = cursor.fetchone()
    if row is None:
        return None
    return _row_to_claude_session(row)


def list_claude_sessions(
    conn: sqlite3.Connection,
    work_item_id: int | None = None,
    repo_name: str | None = None,
    state: str | None = None,
) -> list[ClaudeSession]:
    query = "SELECT * FROM claude_sessions WHERE 1=1"
    params: list[int | str] = []

    if work_item_id is not None:
        query += " AND work_item_id = ?"
        params.append(work_item_id)

    if repo_name is not None:
        query += " AND repo_name = ?"
        params.append(repo_name)

    if state is not None:
        query += " AND state = ?"
        params.append(state)

    query += " ORDER BY id"
    cursor = conn.execute(query, params)
    return [_row_to_claude_session(row) for row in cursor.fetchall()]


def update_claude_session(
    conn: sqlite3.Connection, session_id: int, **fields: object
) -> ClaudeSession | None:
    if not fields:
        return get_claude_session(conn, session_id)

    fields["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [session_id]

    conn.execute(f"UPDATE claude_sessions SET {set_clause} WHERE id = ?", values)
    conn.commit()
    return get_claude_session(conn, session_id)


def delete_claude_session(conn: sqlite3.Connection, session_id: int) -> bool:
    cursor = conn.execute("DELETE FROM claude_sessions WHERE id = ?", (session_id,))
    conn.commit()
    return cursor.rowcount > 0


def list_repos(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """Return distinct (repo_name, repo_path) pairs from work_items."""
    cursor = conn.execute(
        "SELECT DISTINCT repo_name, repo_path FROM work_items ORDER BY repo_name"
    )
    return [(row["repo_name"], row["repo_path"]) for row in cursor.fetchall()]


def find_claude_session(
    conn: sqlite3.Connection,
    tmux_session: str,
    tmux_pane: str,
) -> ClaudeSession | None:
    """Find a Claude session by tmux session and pane."""
    cursor = conn.execute(
        "SELECT * FROM claude_sessions WHERE tmux_session = ? AND tmux_pane = ? ORDER BY id DESC LIMIT 1",
        (tmux_session, tmux_pane),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return _row_to_claude_session(row)


# -- PullRequest CRUD --


def create_pull_request(
    conn: sqlite3.Connection,
    work_item_id: int,
    number: int,
    owner: str,
    repo: str,
    status: str = "open",
    url: str | None = None,
) -> PullRequest:
    now = _now()
    cursor = conn.execute(
        """INSERT INTO pull_requests
           (work_item_id, number, status, owner, repo, url, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (work_item_id, number, status, owner, repo, url, now, now),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM pull_requests WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    return _row_to_pull_request(row)


def list_pull_requests(
    conn: sqlite3.Connection,
    work_item_id: int | None = None,
) -> list[PullRequest]:
    query = "SELECT * FROM pull_requests WHERE 1=1"
    params: list[int] = []

    if work_item_id is not None:
        query += " AND work_item_id = ?"
        params.append(work_item_id)

    query += " ORDER BY id"
    cursor = conn.execute(query, params)
    return [_row_to_pull_request(row) for row in cursor.fetchall()]


def update_pull_request(
    conn: sqlite3.Connection, pr_id: int, **fields: object
) -> PullRequest | None:
    if not fields:
        row = conn.execute(
            "SELECT * FROM pull_requests WHERE id = ?", (pr_id,)
        ).fetchone()
        return _row_to_pull_request(row) if row else None

    fields["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [pr_id]

    conn.execute(f"UPDATE pull_requests SET {set_clause} WHERE id = ?", values)
    conn.commit()
    row = conn.execute("SELECT * FROM pull_requests WHERE id = ?", (pr_id,)).fetchone()
    return _row_to_pull_request(row) if row else None
