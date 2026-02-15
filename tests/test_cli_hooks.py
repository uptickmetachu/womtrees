from __future__ import annotations

import sqlite3
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from womtrees.cli import cli
from womtrees.db import (
    _ensure_schema,
    create_claude_session,
    create_work_item,
    get_claude_session,
    get_work_item,
    list_claude_sessions,
    update_work_item,
)


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def db_conn(tmp_path):
    db_path = tmp_path / "test.db"

    def _get_conn(db_path_arg=None):
        c = sqlite3.connect(str(db_path))
        c.row_factory = sqlite3.Row
        _ensure_schema(c)
        return c

    return _get_conn, db_path


def test_hook_heartbeat_creates_session(runner, db_conn):
    """Test that heartbeat creates a new Claude session."""
    get_conn_fn, db_path = db_conn

    mock_context = {
        "tmux_session": "myrepo/feat-auth",
        "tmux_pane": "%1",
        "repo_name": "myrepo",
        "repo_path": "/tmp/myrepo",
        "branch": "feat/auth",
        "work_item_id": None,
        "pid": 1234,
    }

    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch("womtrees.claude.detect_context", return_value=mock_context),
    ):
        result = runner.invoke(cli, ["hook", "heartbeat"])
        assert result.exit_code == 0

    # Verify session was created
    conn = get_conn_fn()
    sessions = list_claude_sessions(conn)
    assert len(sessions) == 1
    assert sessions[0].state == "working"
    assert sessions[0].tmux_session == "myrepo/feat-auth"
    assert sessions[0].tmux_pane == "%1"
    assert sessions[0].work_item_id is None


def test_hook_heartbeat_updates_existing(runner, db_conn):
    """Test that heartbeat updates an existing session."""
    get_conn_fn, db_path = db_conn

    # Pre-create a session
    conn = get_conn_fn()
    create_claude_session(
        conn,
        "myrepo",
        "/tmp/myrepo",
        "feat/auth",
        tmux_session="myrepo/feat-auth",
        tmux_pane="%1",
        state="waiting",
        pid=1234,
    )

    mock_context = {
        "tmux_session": "myrepo/feat-auth",
        "tmux_pane": "%1",
        "repo_name": "myrepo",
        "repo_path": "/tmp/myrepo",
        "branch": "feat/auth",
        "work_item_id": None,
        "pid": 1234,
    }

    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch("womtrees.claude.detect_context", return_value=mock_context),
    ):
        result = runner.invoke(cli, ["hook", "heartbeat"])
        assert result.exit_code == 0

    # Verify session was updated, not duplicated
    conn = get_conn_fn()
    sessions = list_claude_sessions(conn)
    assert len(sessions) == 1
    assert sessions[0].state == "working"


def test_hook_stop_sets_done(runner, db_conn):
    """Test that stop hook sets session to done."""
    get_conn_fn, db_path = db_conn

    mock_context = {
        "tmux_session": "myrepo/feat-auth",
        "tmux_pane": "%1",
        "repo_name": "myrepo",
        "repo_path": "/tmp/myrepo",
        "branch": "feat/auth",
        "work_item_id": None,
        "pid": 1234,
    }

    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch("womtrees.claude.detect_context", return_value=mock_context),
    ):
        result = runner.invoke(cli, ["hook", "stop"])
        assert result.exit_code == 0

    conn = get_conn_fn()
    sessions = list_claude_sessions(conn)
    assert len(sessions) == 1
    assert sessions[0].state == "done"


def test_hook_input_sets_waiting(runner, db_conn):
    """Test that input hook sets session to waiting."""
    get_conn_fn, db_path = db_conn

    mock_context = {
        "tmux_session": "myrepo/feat-auth",
        "tmux_pane": "%1",
        "repo_name": "myrepo",
        "repo_path": "/tmp/myrepo",
        "branch": "feat/auth",
        "work_item_id": None,
        "pid": 1234,
    }

    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch("womtrees.claude.detect_context", return_value=mock_context),
    ):
        result = runner.invoke(cli, ["hook", "input"])
        assert result.exit_code == 0

    conn = get_conn_fn()
    sessions = list_claude_sessions(conn)
    assert len(sessions) == 1
    assert sessions[0].state == "waiting"


def test_hook_heartbeat_with_work_item(runner, db_conn):
    """Test that heartbeat links to a work item when env var is present."""
    get_conn_fn, db_path = db_conn

    # Create a work item
    conn = get_conn_fn()
    item = create_work_item(conn, "myrepo", "/tmp/myrepo", "feat/auth")

    mock_context = {
        "tmux_session": "myrepo/feat-auth",
        "tmux_pane": "%1",
        "repo_name": "myrepo",
        "repo_path": "/tmp/myrepo",
        "branch": "feat/auth",
        "work_item_id": item.id,
        "pid": 1234,
    }

    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch("womtrees.claude.detect_context", return_value=mock_context),
    ):
        result = runner.invoke(cli, ["hook", "heartbeat"])
        assert result.exit_code == 0

    conn = get_conn_fn()
    sessions = list_claude_sessions(conn)
    assert len(sessions) == 1
    assert sessions[0].work_item_id == item.id


def test_hook_heartbeat_silent_without_tmux(runner, db_conn):
    """Test that heartbeat exits silently when not in tmux."""
    get_conn_fn, db_path = db_conn

    mock_context = {
        "tmux_session": None,
        "tmux_pane": "",
        "repo_name": None,
        "repo_path": None,
        "branch": None,
        "work_item_id": None,
        "pid": 1234,
    }

    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch("womtrees.claude.detect_context", return_value=mock_context),
    ):
        result = runner.invoke(cli, ["hook", "heartbeat"])
        assert result.exit_code == 0

    # No session should be created
    conn = get_conn_fn()
    sessions = list_claude_sessions(conn)
    assert len(sessions) == 0


def test_hook_mark_done(runner, db_conn):
    """Test marking a session as done."""
    get_conn_fn, db_path = db_conn

    conn = get_conn_fn()
    session = create_claude_session(
        conn,
        "myrepo",
        "/tmp/myrepo",
        "feat/auth",
        tmux_session="s1",
        tmux_pane="%1",
        state="working",
    )

    with patch("womtrees.db.get_connection", get_conn_fn):
        result = runner.invoke(cli, ["hook", "mark-done", str(session.id)])
        assert result.exit_code == 0

    conn = get_conn_fn()
    updated = get_claude_session(conn, session.id)
    assert updated.state == "done"


def test_sessions_command(runner, db_conn):
    """Test wt sessions lists Claude sessions."""
    get_conn_fn, db_path = db_conn

    conn = get_conn_fn()
    create_claude_session(
        conn,
        "myrepo",
        "/tmp/myrepo",
        "feat/auth",
        tmux_session="s1",
        tmux_pane="%1",
        state="working",
    )
    create_claude_session(
        conn,
        "myrepo",
        "/tmp/myrepo",
        "feat/auth",
        tmux_session="s1",
        tmux_pane="%2",
        state="waiting",
    )

    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch("womtrees.claude.is_pid_alive", return_value=True),
    ):
        result = runner.invoke(cli, ["sessions"])
        assert result.exit_code == 0
        assert "working" in result.output
        assert "waiting" in result.output


def test_sessions_empty(runner, db_conn):
    """Test wt sessions when no sessions exist."""
    get_conn_fn, db_path = db_conn

    with (
        patch("womtrees.db.get_connection", get_conn_fn),
    ):
        result = runner.invoke(cli, ["sessions"])
        assert result.exit_code == 0
        assert "No Claude sessions found" in result.output


def test_hook_install_command(runner, tmp_path):
    """Test wt hook install installs Claude Code hooks."""
    with patch("womtrees.claude.install_global_hooks") as mock_install:
        result = runner.invoke(cli, ["hook", "install"])
        assert result.exit_code == 0
        assert "Installed" in result.output
        mock_install.assert_called_once()


def test_hook_heartbeat_moves_item_to_working(runner, db_conn):
    """Test that heartbeat moves a linked work item to working status."""
    get_conn_fn, db_path = db_conn

    conn = get_conn_fn()
    item = create_work_item(conn, "myrepo", "/tmp/myrepo", "feat/auth")
    update_work_item(conn, item.id, status="input")
    create_claude_session(
        conn,
        "myrepo",
        "/tmp/myrepo",
        "feat/auth",
        tmux_session="s1",
        tmux_pane="%1",
        state="waiting",
        work_item_id=item.id,
    )

    mock_context = {
        "tmux_session": "s1",
        "tmux_pane": "%1",
        "repo_name": "myrepo",
        "repo_path": "/tmp/myrepo",
        "branch": "feat/auth",
        "work_item_id": item.id,
        "pid": 1234,
    }

    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch("womtrees.claude.detect_context", return_value=mock_context),
    ):
        result = runner.invoke(cli, ["hook", "heartbeat"])
        assert result.exit_code == 0

    conn = get_conn_fn()
    updated = get_work_item(conn, item.id)
    assert updated.status == "working"


def test_hook_input_moves_item_to_input(runner, db_conn):
    """Test that input hook moves a linked work item to input status."""
    get_conn_fn, db_path = db_conn

    conn = get_conn_fn()
    item = create_work_item(conn, "myrepo", "/tmp/myrepo", "feat/auth")
    update_work_item(conn, item.id, status="working")
    create_claude_session(
        conn,
        "myrepo",
        "/tmp/myrepo",
        "feat/auth",
        tmux_session="s1",
        tmux_pane="%1",
        state="working",
        work_item_id=item.id,
    )

    mock_context = {
        "tmux_session": "s1",
        "tmux_pane": "%1",
        "repo_name": "myrepo",
        "repo_path": "/tmp/myrepo",
        "branch": "feat/auth",
        "work_item_id": item.id,
        "pid": 1234,
    }

    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch("womtrees.claude.detect_context", return_value=mock_context),
    ):
        result = runner.invoke(cli, ["hook", "input"])
        assert result.exit_code == 0

    conn = get_conn_fn()
    updated = get_work_item(conn, item.id)
    assert updated.status == "input"


def test_hook_stop_moves_item_to_review(runner, db_conn):
    """Test that stop hook moves a linked work item to review status."""
    get_conn_fn, db_path = db_conn

    conn = get_conn_fn()
    item = create_work_item(conn, "myrepo", "/tmp/myrepo", "feat/auth")
    update_work_item(conn, item.id, status="working")
    create_claude_session(
        conn,
        "myrepo",
        "/tmp/myrepo",
        "feat/auth",
        tmux_session="s1",
        tmux_pane="%1",
        state="working",
        work_item_id=item.id,
    )

    mock_context = {
        "tmux_session": "s1",
        "tmux_pane": "%1",
        "repo_name": "myrepo",
        "repo_path": "/tmp/myrepo",
        "branch": "feat/auth",
        "work_item_id": item.id,
        "pid": 1234,
    }

    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch("womtrees.claude.detect_context", return_value=mock_context),
    ):
        result = runner.invoke(cli, ["hook", "stop"])
        assert result.exit_code == 0

    conn = get_conn_fn()
    updated = get_work_item(conn, item.id)
    assert updated.status == "review"


def test_hook_skips_todo_items(runner, db_conn):
    """Test that hooks don't transition items in TODO status."""
    get_conn_fn, db_path = db_conn

    conn = get_conn_fn()
    item = create_work_item(conn, "myrepo", "/tmp/myrepo", "feat/auth")
    # Item stays in 'todo' (default)
    create_claude_session(
        conn,
        "myrepo",
        "/tmp/myrepo",
        "feat/auth",
        tmux_session="s1",
        tmux_pane="%1",
        state="working",
        work_item_id=item.id,
    )

    mock_context = {
        "tmux_session": "s1",
        "tmux_pane": "%1",
        "repo_name": "myrepo",
        "repo_path": "/tmp/myrepo",
        "branch": "feat/auth",
        "work_item_id": item.id,
        "pid": 1234,
    }

    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch("womtrees.claude.detect_context", return_value=mock_context),
    ):
        result = runner.invoke(cli, ["hook", "stop"])
        assert result.exit_code == 0

    conn = get_conn_fn()
    updated = get_work_item(conn, item.id)
    assert updated.status == "todo"


def test_hook_skips_done_items(runner, db_conn):
    """Test that hooks don't transition items in DONE status."""
    get_conn_fn, db_path = db_conn

    conn = get_conn_fn()
    item = create_work_item(conn, "myrepo", "/tmp/myrepo", "feat/auth")
    update_work_item(conn, item.id, status="done")
    create_claude_session(
        conn,
        "myrepo",
        "/tmp/myrepo",
        "feat/auth",
        tmux_session="s1",
        tmux_pane="%1",
        state="done",
        work_item_id=item.id,
    )

    mock_context = {
        "tmux_session": "s1",
        "tmux_pane": "%1",
        "repo_name": "myrepo",
        "repo_path": "/tmp/myrepo",
        "branch": "feat/auth",
        "work_item_id": item.id,
        "pid": 1234,
    }

    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch("womtrees.claude.detect_context", return_value=mock_context),
    ):
        result = runner.invoke(cli, ["hook", "heartbeat"])
        assert result.exit_code == 0

    conn = get_conn_fn()
    updated = get_work_item(conn, item.id)
    assert updated.status == "done"


def test_hook_heartbeat_captures_session_id(runner, db_conn):
    """Test that heartbeat reads Claude session_id from stdin."""
    get_conn_fn, db_path = db_conn

    mock_context = {
        "tmux_session": "s1",
        "tmux_pane": "%1",
        "repo_name": "myrepo",
        "repo_path": "/tmp/myrepo",
        "branch": "feat/auth",
        "work_item_id": None,
        "pid": 1234,
    }

    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch("womtrees.claude.detect_context", return_value=mock_context),
    ):
        result = runner.invoke(
            cli, ["hook", "heartbeat"], input='{"session_id": "abc-123-def"}'
        )
        assert result.exit_code == 0

    conn = get_conn_fn()
    sessions = list_claude_sessions(conn)
    assert len(sessions) == 1
    assert sessions[0].claude_session_id == "abc-123-def"


def test_hook_heartbeat_updates_session_id(runner, db_conn):
    """Test that heartbeat updates claude_session_id on existing sessions."""
    get_conn_fn, db_path = db_conn

    # Pre-create a session without claude_session_id
    conn = get_conn_fn()
    create_claude_session(
        conn,
        "myrepo",
        "/tmp/myrepo",
        "feat/auth",
        tmux_session="s1",
        tmux_pane="%1",
        state="working",
        pid=1234,
    )

    mock_context = {
        "tmux_session": "s1",
        "tmux_pane": "%1",
        "repo_name": "myrepo",
        "repo_path": "/tmp/myrepo",
        "branch": "feat/auth",
        "work_item_id": None,
        "pid": 1234,
    }

    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch("womtrees.claude.detect_context", return_value=mock_context),
    ):
        result = runner.invoke(
            cli, ["hook", "heartbeat"], input='{"session_id": "new-uuid-456"}'
        )
        assert result.exit_code == 0

    conn = get_conn_fn()
    sessions = list_claude_sessions(conn)
    assert len(sessions) == 1
    assert sessions[0].claude_session_id == "new-uuid-456"


def test_hook_heartbeat_no_stdin(runner, db_conn):
    """Test that heartbeat works without stdin (no session_id captured)."""
    get_conn_fn, db_path = db_conn

    mock_context = {
        "tmux_session": "s1",
        "tmux_pane": "%1",
        "repo_name": "myrepo",
        "repo_path": "/tmp/myrepo",
        "branch": "feat/auth",
        "work_item_id": None,
        "pid": 1234,
    }

    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch("womtrees.claude.detect_context", return_value=mock_context),
    ):
        result = runner.invoke(cli, ["hook", "heartbeat"])
        assert result.exit_code == 0

    conn = get_conn_fn()
    sessions = list_claude_sessions(conn)
    assert len(sessions) == 1
    assert sessions[0].claude_session_id is None
