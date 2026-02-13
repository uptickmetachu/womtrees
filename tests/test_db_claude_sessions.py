from __future__ import annotations

import sqlite3

from womtrees.db import (
    _ensure_schema,
    create_claude_session,
    create_work_item,
    delete_claude_session,
    find_claude_session,
    get_claude_session,
    list_claude_sessions,
    update_claude_session,
)


def _in_memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    return conn


def test_create_and_get_session():
    conn = _in_memory_conn()
    session = create_claude_session(
        conn, "myrepo", "/tmp/myrepo", "feat/auth",
        tmux_session="myrepo/feat-auth", tmux_pane="%1",
        pid=1234, state="working",
    )
    assert session.id == 1
    assert session.repo_name == "myrepo"
    assert session.tmux_session == "myrepo/feat-auth"
    assert session.state == "working"
    assert session.work_item_id is None

    fetched = get_claude_session(conn, 1)
    assert fetched is not None
    assert fetched.id == session.id


def test_create_session_with_work_item():
    conn = _in_memory_conn()
    item = create_work_item(conn, "myrepo", "/tmp/myrepo", "feat/auth")
    session = create_claude_session(
        conn, "myrepo", "/tmp/myrepo", "feat/auth",
        tmux_session="myrepo/feat-auth", tmux_pane="%1",
        work_item_id=item.id,
    )
    assert session.work_item_id == item.id


def test_list_sessions_by_work_item():
    conn = _in_memory_conn()
    item = create_work_item(conn, "myrepo", "/tmp/myrepo", "feat/auth")
    create_claude_session(
        conn, "myrepo", "/tmp/myrepo", "feat/auth",
        tmux_session="s1", tmux_pane="%1", work_item_id=item.id,
    )
    create_claude_session(
        conn, "myrepo", "/tmp/myrepo", "feat/auth",
        tmux_session="s1", tmux_pane="%2", work_item_id=item.id,
    )
    create_claude_session(
        conn, "other", "/tmp/other", "main",
        tmux_session="s2", tmux_pane="%1",
    )

    sessions = list_claude_sessions(conn, work_item_id=item.id)
    assert len(sessions) == 2


def test_list_sessions_by_repo():
    conn = _in_memory_conn()
    create_claude_session(
        conn, "myrepo", "/tmp/myrepo", "feat/auth",
        tmux_session="s1", tmux_pane="%1",
    )
    create_claude_session(
        conn, "other", "/tmp/other", "main",
        tmux_session="s2", tmux_pane="%1",
    )

    sessions = list_claude_sessions(conn, repo_name="myrepo")
    assert len(sessions) == 1
    assert sessions[0].repo_name == "myrepo"


def test_list_sessions_by_state():
    conn = _in_memory_conn()
    create_claude_session(
        conn, "myrepo", "/tmp/myrepo", "feat/auth",
        tmux_session="s1", tmux_pane="%1", state="working",
    )
    create_claude_session(
        conn, "myrepo", "/tmp/myrepo", "feat/auth",
        tmux_session="s1", tmux_pane="%2", state="waiting",
    )

    sessions = list_claude_sessions(conn, state="waiting")
    assert len(sessions) == 1
    assert sessions[0].state == "waiting"


def test_update_session():
    conn = _in_memory_conn()
    session = create_claude_session(
        conn, "myrepo", "/tmp/myrepo", "feat/auth",
        tmux_session="s1", tmux_pane="%1", state="working",
    )

    updated = update_claude_session(conn, session.id, state="waiting")
    assert updated is not None
    assert updated.state == "waiting"
    assert updated.updated_at > session.updated_at


def test_delete_session():
    conn = _in_memory_conn()
    session = create_claude_session(
        conn, "myrepo", "/tmp/myrepo", "feat/auth",
        tmux_session="s1", tmux_pane="%1",
    )
    assert delete_claude_session(conn, session.id) is True
    assert get_claude_session(conn, session.id) is None


def test_find_session():
    conn = _in_memory_conn()
    create_claude_session(
        conn, "myrepo", "/tmp/myrepo", "feat/auth",
        tmux_session="myrepo/feat-auth", tmux_pane="%1", state="working",
    )
    create_claude_session(
        conn, "myrepo", "/tmp/myrepo", "feat/auth",
        tmux_session="myrepo/feat-auth", tmux_pane="%2", state="waiting",
    )

    found = find_claude_session(conn, "myrepo/feat-auth", "%1")
    assert found is not None
    assert found.tmux_pane == "%1"

    not_found = find_claude_session(conn, "myrepo/feat-auth", "%99")
    assert not_found is None


def test_find_session_ignores_done():
    conn = _in_memory_conn()
    create_claude_session(
        conn, "myrepo", "/tmp/myrepo", "feat/auth",
        tmux_session="s1", tmux_pane="%1", state="done",
    )

    found = find_claude_session(conn, "s1", "%1")
    assert found is None
