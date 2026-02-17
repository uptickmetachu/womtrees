from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from womtrees.cli import cli
from womtrees.db import _ensure_schema


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def db_conn(tmp_path):
    """Provide an in-memory-like DB by patching get_connection."""
    import sqlite3

    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    _ensure_schema(conn)

    def _get_conn(db_path_arg=None):
        c = sqlite3.connect(str(db_path))
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        return c

    return _get_conn, db_path


def test_help(runner):
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "womtrees" in result.output


def test_todo_not_in_repo(runner, tmp_path, db_conn):
    get_conn_fn, db_path = db_conn
    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch("womtrees.cli.utils.get_current_repo", return_value=None),
    ):
        result = runner.invoke(cli, ["todo", "test", "-b", "feat/x"])
        assert result.exit_code != 0
        assert "Not inside a git repository" in result.output


def test_todo_creates_item(runner, db_conn):
    get_conn_fn, db_path = db_conn
    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch(
            "womtrees.cli.utils.get_current_repo",
            return_value=("myrepo", "/tmp/myrepo"),
        ),
    ):
        result = runner.invoke(cli, ["todo", "do stuff", "-b", "feat/x"])
        assert result.exit_code == 0
        assert "Created TODO #1" in result.output


def test_list_empty(runner, db_conn):
    get_conn_fn, db_path = db_conn
    with (
        patch("womtrees.db.get_connection", get_conn_fn),
    ):
        result = runner.invoke(cli, ["list"])
        assert result.exit_code == 0
        assert "No work items found" in result.output


def test_list_shows_items(runner, db_conn):
    get_conn_fn, db_path = db_conn
    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch(
            "womtrees.cli.utils.get_current_repo",
            return_value=("myrepo", "/tmp/myrepo"),
        ),
    ):
        runner.invoke(cli, ["todo", "first", "-b", "feat/a"])
        runner.invoke(cli, ["todo", "second", "-b", "feat/b"])

        result = runner.invoke(cli, ["list"])
        assert result.exit_code == 0
        assert "feat/a" in result.output
        assert "feat/b" in result.output


def test_status_summary(runner, db_conn):
    get_conn_fn, db_path = db_conn
    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch(
            "womtrees.cli.utils.get_current_repo",
            return_value=("myrepo", "/tmp/myrepo"),
        ),
    ):
        runner.invoke(cli, ["todo", "-b", "feat/a"])
        runner.invoke(cli, ["todo", "-b", "feat/b"])

        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "todo: 2" in result.output


def test_status_single(runner, db_conn):
    get_conn_fn, db_path = db_conn
    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch(
            "womtrees.cli.utils.get_current_repo",
            return_value=("myrepo", "/tmp/myrepo"),
        ),
    ):
        runner.invoke(cli, ["todo", "my prompt", "-b", "feat/a"])

        result = runner.invoke(cli, ["status", "1"])
        assert result.exit_code == 0
        assert "feat/a" in result.output
        assert "my prompt" in result.output


def test_review_transition(runner, db_conn):
    get_conn_fn, db_path = db_conn
    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch(
            "womtrees.cli.utils.get_current_repo",
            return_value=("myrepo", "/tmp/myrepo"),
        ),
    ):
        runner.invoke(cli, ["todo", "-b", "feat/a"])

        # Can't review a TODO
        result = runner.invoke(cli, ["review", "1"])
        assert result.exit_code != 0
        assert "expected 'working' or 'input'" in result.output


def test_done_transition(runner, db_conn):
    get_conn_fn, db_path = db_conn
    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch(
            "womtrees.cli.utils.get_current_repo",
            return_value=("myrepo", "/tmp/myrepo"),
        ),
    ):
        runner.invoke(cli, ["todo", "-b", "feat/a"])

        # Can't mark TODO as done
        result = runner.invoke(cli, ["done", "1"])
        assert result.exit_code != 0
        assert "expected 'working' or 'input' or 'review'" in result.output


def test_delete_todo(runner, db_conn):
    get_conn_fn, db_path = db_conn
    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch(
            "womtrees.cli.utils.get_current_repo",
            return_value=("myrepo", "/tmp/myrepo"),
        ),
    ):
        runner.invoke(cli, ["todo", "-b", "feat/a"])

        result = runner.invoke(cli, ["delete", "1"])
        assert result.exit_code == 0
        assert "Deleted #1" in result.output

        result = runner.invoke(cli, ["list"])
        assert "No work items found" in result.output


def test_delete_nonexistent(runner, db_conn):
    get_conn_fn, db_path = db_conn
    with patch("womtrees.db.get_connection", get_conn_fn):
        result = runner.invoke(cli, ["delete", "999"])
        assert result.exit_code != 0
        assert "not found" in result.output


def test_config_show(runner, tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text('[worktrees]\nbase_dir = "/tmp/wt"\n')
    with patch("womtrees.cli.admin.ensure_config", return_value=config_file):
        result = runner.invoke(cli, ["config"])
        assert result.exit_code == 0
        assert "base_dir" in result.output


# Phase 2: tmux integration tests


def test_start_creates_tmux_session(runner, db_conn, tmp_path):
    """Test that wt start creates a tmux session and updates the work item."""
    get_conn_fn, db_path = db_conn

    mock_config = MagicMock()
    mock_config.base_dir = tmp_path / "worktrees"
    mock_config.tmux_split = "vertical"
    mock_config.tmux_claude_pane = "left"

    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch(
            "womtrees.cli.utils.get_current_repo",
            return_value=("myrepo", "/tmp/myrepo"),
        ),
        patch("womtrees.cli.items.get_config", return_value=mock_config),
        patch(
            "womtrees.services.workitem.create_worktree",
            return_value=tmp_path / "worktrees" / "myrepo" / "feat-x",
        ),
        patch("womtrees.tmux.is_available", return_value=True),
        patch(
            "womtrees.tmux.create_session",
            return_value=("myrepo/feat-x", "%0"),
        ) as mock_create,
        patch("womtrees.tmux.set_environment") as mock_setenv,
        patch("womtrees.tmux.split_pane", return_value="%1") as mock_split,
        patch("womtrees.tmux.swap_pane") as mock_swap,
        patch("womtrees.tmux.send_keys"),
    ):
        runner.invoke(cli, ["todo", "test prompt", "-b", "feat/x"])

        result = runner.invoke(cli, ["start", "1"])
        assert result.exit_code == 0
        assert "Started #1" in result.output
        assert "myrepo/feat-x" in result.output

        mock_create.assert_called_once()
        mock_setenv.assert_called_once_with(
            "myrepo/feat-x",
            "WOMTREE_WORK_ITEM_ID",
            "1",
        )
        mock_split.assert_called_once()
        mock_swap.assert_called_once()  # claude_pane=left triggers swap


def test_start_no_swap_when_claude_right(runner, db_conn, tmp_path):
    """Test that swap_pane is NOT called when claude_pane is 'right'."""
    get_conn_fn, db_path = db_conn

    mock_config = MagicMock()
    mock_config.base_dir = tmp_path / "worktrees"
    mock_config.tmux_split = "vertical"
    mock_config.tmux_claude_pane = "right"

    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch(
            "womtrees.cli.utils.get_current_repo",
            return_value=("myrepo", "/tmp/myrepo"),
        ),
        patch("womtrees.cli.items.get_config", return_value=mock_config),
        patch(
            "womtrees.services.workitem.create_worktree",
            return_value=tmp_path / "worktrees" / "myrepo" / "feat-x",
        ),
        patch("womtrees.tmux.is_available", return_value=True),
        patch("womtrees.tmux.create_session", return_value=("myrepo/feat-x", "%0")),
        patch("womtrees.tmux.set_environment"),
        patch("womtrees.tmux.split_pane", return_value="%1"),
        patch("womtrees.tmux.swap_pane") as mock_swap,
        patch("womtrees.tmux.send_keys"),
    ):
        runner.invoke(cli, ["todo", "-b", "feat/x"])
        result = runner.invoke(cli, ["start", "1"])
        assert result.exit_code == 0
        mock_swap.assert_not_called()


def test_start_fails_without_tmux(runner, db_conn):
    """Test that start fails gracefully when tmux is not installed."""
    get_conn_fn, db_path = db_conn

    mock_config = MagicMock()

    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch(
            "womtrees.cli.utils.get_current_repo",
            return_value=("myrepo", "/tmp/myrepo"),
        ),
        patch("womtrees.cli.items.get_config", return_value=mock_config),
        patch("womtrees.tmux.is_available", return_value=False),
    ):
        runner.invoke(cli, ["todo", "-b", "feat/x"])
        result = runner.invoke(cli, ["start", "1"])
        assert result.exit_code != 0
        assert "tmux is required" in result.output


def test_delete_kills_tmux_session(runner, db_conn, tmp_path):
    """Test that deleting a work item kills its tmux session."""
    get_conn_fn, db_path = db_conn

    mock_config = MagicMock()
    mock_config.base_dir = tmp_path / "worktrees"
    mock_config.tmux_split = "vertical"
    mock_config.tmux_claude_pane = "left"

    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch(
            "womtrees.cli.utils.get_current_repo",
            return_value=("myrepo", "/tmp/myrepo"),
        ),
        patch("womtrees.cli.items.get_config", return_value=mock_config),
        patch(
            "womtrees.services.workitem.create_worktree",
            return_value=tmp_path / "worktrees" / "myrepo" / "feat-x",
        ),
        patch("womtrees.services.workitem.remove_worktree"),
        patch("womtrees.tmux.is_available", return_value=True),
        patch("womtrees.tmux.create_session", return_value=("myrepo/feat-x", "%0")),
        patch("womtrees.tmux.set_environment"),
        patch("womtrees.tmux.split_pane", return_value="%1"),
        patch("womtrees.tmux.swap_pane"),
        patch("womtrees.tmux.send_keys"),
        patch("womtrees.tmux.session_exists", return_value=True),
        patch("womtrees.tmux.kill_session") as mock_kill,
    ):
        runner.invoke(cli, ["todo", "-b", "feat/x"])
        runner.invoke(cli, ["start", "1"])

        result = runner.invoke(cli, ["delete", "1", "--force"], input="y\n")
        assert result.exit_code == 0
        assert "Deleted #1" in result.output
        mock_kill.assert_called_once_with("myrepo/feat-x")


def test_attach_command(runner, db_conn, tmp_path):
    """Test wt attach jumps to the tmux session."""
    get_conn_fn, db_path = db_conn

    mock_config = MagicMock()
    mock_config.base_dir = tmp_path / "worktrees"
    mock_config.tmux_split = "vertical"
    mock_config.tmux_claude_pane = "left"

    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch(
            "womtrees.cli.utils.get_current_repo",
            return_value=("myrepo", "/tmp/myrepo"),
        ),
        patch("womtrees.cli.items.get_config", return_value=mock_config),
        patch(
            "womtrees.services.workitem.create_worktree",
            return_value=tmp_path / "worktrees" / "myrepo" / "feat-x",
        ),
        patch("womtrees.tmux.is_available", return_value=True),
        patch("womtrees.tmux.create_session", return_value=("myrepo/feat-x", "%0")),
        patch("womtrees.tmux.set_environment"),
        patch("womtrees.tmux.split_pane", return_value="%1"),
        patch("womtrees.tmux.swap_pane"),
        patch("womtrees.tmux.send_keys"),
        patch("womtrees.tmux.session_exists", return_value=True),
        patch("womtrees.tmux.attach") as mock_attach,
    ):
        runner.invoke(cli, ["todo", "-b", "feat/x"])
        runner.invoke(cli, ["start", "1"])

        result = runner.invoke(cli, ["attach", "1"])
        assert result.exit_code == 0
        mock_attach.assert_called_once_with("myrepo/feat-x")


def test_attach_rejects_todo_item(runner, db_conn):
    """Test that wt attach refuses to jump into a TODO work item."""
    get_conn_fn, db_path = db_conn

    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch(
            "womtrees.cli.utils.get_current_repo",
            return_value=("myrepo", "/tmp/myrepo"),
        ),
    ):
        runner.invoke(cli, ["todo", "-b", "feat/x"])

        result = runner.invoke(cli, ["attach", "1"])
        assert result.exit_code == 1
        assert "TODO" in result.output
        assert "Start it first" in result.output


def test_attach_restores_missing_session(runner, db_conn):
    """Test wt attach recreates tmux session when it no longer exists."""
    get_conn_fn, db_path = db_conn

    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch(
            "womtrees.cli.utils.get_current_repo",
            return_value=("myrepo", "/tmp/myrepo"),
        ),
        patch("womtrees.tmux.session_exists") as mock_exists,
        patch(
            "womtrees.tmux.create_session",
            return_value=("myrepo-feat-x", "%0"),
        ) as mock_create,
        patch("womtrees.tmux.set_environment") as mock_setenv,
        patch("womtrees.tmux.attach") as mock_attach,
    ):
        runner.invoke(cli, ["todo", "-b", "feat/x"])

        # Move item out of todo so attach is allowed
        from womtrees.db import update_work_item

        conn = get_conn_fn()
        update_work_item(conn, 1, status="working")
        conn.close()

        # Session doesn't exist initially, then exists after restore
        mock_exists.side_effect = [False, True]

        result = runner.invoke(cli, ["attach", "1"])
        assert result.exit_code == 0
        assert "Restored tmux session" in result.output
        mock_create.assert_called_once()
        mock_setenv.assert_called_once()
        mock_attach.assert_called_once()


def test_attach_resumes_dead_session(runner, db_conn, tmp_path):
    """Test that wt attach relaunches Claude if the process is dead."""
    get_conn_fn, db_path = db_conn

    mock_config = MagicMock()
    mock_config.base_dir = tmp_path / "worktrees"
    mock_config.tmux_split = "vertical"
    mock_config.tmux_claude_pane = "left"
    mock_config.claude_args = ""

    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch(
            "womtrees.cli.utils.get_current_repo",
            return_value=("myrepo", "/tmp/myrepo"),
        ),
        patch("womtrees.cli.items.get_config", return_value=mock_config),
        patch("womtrees.cli.info.get_config", return_value=mock_config),
        patch(
            "womtrees.services.workitem.create_worktree",
            return_value=tmp_path / "worktrees" / "myrepo" / "feat-x",
        ),
        patch("womtrees.tmux.is_available", return_value=True),
        patch("womtrees.tmux.create_session", return_value=("myrepo-feat-x", "%0")),
        patch("womtrees.tmux.set_environment"),
        patch("womtrees.tmux.split_pane", return_value="%1"),
        patch("womtrees.tmux.swap_pane"),
        patch("womtrees.tmux.send_keys") as mock_send_keys,
        patch("womtrees.tmux.session_exists", return_value=True),
        patch("womtrees.tmux.attach"),
        patch("womtrees.claude.is_pid_alive", return_value=False),
    ):
        runner.invoke(cli, ["todo", "-b", "feat/x"])
        runner.invoke(cli, ["start", "1"])

        # Update the session to have a claude_session_id and PID
        conn = get_conn_fn()
        from womtrees.db import list_claude_sessions, update_claude_session

        sessions = list_claude_sessions(conn)
        update_claude_session(
            conn,
            sessions[0].id,
            claude_session_id="test-uuid-123",
            pid=99999,
        )

        mock_send_keys.reset_mock()

        result = runner.invoke(cli, ["attach", "1"])
        assert result.exit_code == 0

        # Should have sent claude --resume to the pane
        mock_send_keys.assert_called_once()
        call_args = mock_send_keys.call_args
        assert "--resume test-uuid-123" in call_args[0][1]


def test_attach_resumes_with_continue_fallback(runner, db_conn, tmp_path):
    """Test that wt attach falls back to --continue if no session_id."""
    get_conn_fn, db_path = db_conn

    mock_config = MagicMock()
    mock_config.base_dir = tmp_path / "worktrees"
    mock_config.tmux_split = "vertical"
    mock_config.tmux_claude_pane = "left"
    mock_config.claude_args = ""

    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch(
            "womtrees.cli.utils.get_current_repo",
            return_value=("myrepo", "/tmp/myrepo"),
        ),
        patch("womtrees.cli.items.get_config", return_value=mock_config),
        patch("womtrees.cli.info.get_config", return_value=mock_config),
        patch(
            "womtrees.services.workitem.create_worktree",
            return_value=tmp_path / "worktrees" / "myrepo" / "feat-x",
        ),
        patch("womtrees.tmux.is_available", return_value=True),
        patch("womtrees.tmux.create_session", return_value=("myrepo-feat-x", "%0")),
        patch("womtrees.tmux.set_environment"),
        patch("womtrees.tmux.split_pane", return_value="%1"),
        patch("womtrees.tmux.swap_pane"),
        patch("womtrees.tmux.send_keys") as mock_send_keys,
        patch("womtrees.tmux.session_exists", return_value=True),
        patch("womtrees.tmux.attach"),
        patch("womtrees.claude.is_pid_alive", return_value=False),
    ):
        runner.invoke(cli, ["todo", "-b", "feat/x"])
        runner.invoke(cli, ["start", "1"])

        # Set a PID so resume check runs (no claude_session_id → fallback)
        conn = get_conn_fn()
        from womtrees.db import list_claude_sessions, update_claude_session

        sessions = list_claude_sessions(conn)
        update_claude_session(conn, sessions[0].id, pid=99999)

        mock_send_keys.reset_mock()

        result = runner.invoke(cli, ["attach", "1"])
        assert result.exit_code == 0

        # Should have sent claude --continue (no session_id stored)
        mock_send_keys.assert_called_once()
        call_args = mock_send_keys.call_args
        assert "--continue" in call_args[0][1]


def test_attach_skips_resume_if_alive(runner, db_conn, tmp_path):
    """Test that wt attach does NOT relaunch Claude if process is alive."""
    get_conn_fn, db_path = db_conn

    mock_config = MagicMock()
    mock_config.base_dir = tmp_path / "worktrees"
    mock_config.tmux_split = "vertical"
    mock_config.tmux_claude_pane = "left"
    mock_config.claude_args = ""

    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch(
            "womtrees.cli.utils.get_current_repo",
            return_value=("myrepo", "/tmp/myrepo"),
        ),
        patch("womtrees.cli.items.get_config", return_value=mock_config),
        patch(
            "womtrees.services.workitem.create_worktree",
            return_value=tmp_path / "worktrees" / "myrepo" / "feat-x",
        ),
        patch("womtrees.tmux.is_available", return_value=True),
        patch("womtrees.tmux.create_session", return_value=("myrepo-feat-x", "%0")),
        patch("womtrees.tmux.set_environment"),
        patch("womtrees.tmux.split_pane", return_value="%1"),
        patch("womtrees.tmux.swap_pane"),
        patch("womtrees.tmux.send_keys") as mock_send_keys,
        patch("womtrees.tmux.session_exists", return_value=True),
        patch("womtrees.tmux.attach"),
        patch("womtrees.claude.is_pid_alive", return_value=True),
    ):
        runner.invoke(cli, ["todo", "-b", "feat/x"])
        runner.invoke(cli, ["start", "1"])

        mock_send_keys.reset_mock()

        result = runner.invoke(cli, ["attach", "1"])
        assert result.exit_code == 0

        # Should NOT have sent any resume command
        mock_send_keys.assert_not_called()


def test_attach_skips_resume_if_another_session_alive(runner, db_conn, tmp_path):
    """Don't resume a dead session when another session is still running."""
    get_conn_fn, db_path = db_conn

    mock_config = MagicMock()
    mock_config.base_dir = tmp_path / "worktrees"
    mock_config.tmux_split = "vertical"
    mock_config.tmux_claude_pane = "left"
    mock_config.claude_args = ""

    def pid_alive(pid):
        # PID 11111 is dead (target), PID 22222 is alive (other session)
        return pid == 22222

    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch(
            "womtrees.cli.utils.get_current_repo",
            return_value=("myrepo", "/tmp/myrepo"),
        ),
        patch("womtrees.cli.items.get_config", return_value=mock_config),
        patch("womtrees.cli.info.get_config", return_value=mock_config),
        patch(
            "womtrees.services.workitem.create_worktree",
            return_value=tmp_path / "worktrees" / "myrepo" / "feat-x",
        ),
        patch("womtrees.tmux.is_available", return_value=True),
        patch("womtrees.tmux.create_session", return_value=("myrepo-feat-x", "%0")),
        patch("womtrees.tmux.set_environment"),
        patch("womtrees.tmux.split_pane", return_value="%1"),
        patch("womtrees.tmux.swap_pane"),
        patch("womtrees.tmux.send_keys") as mock_send_keys,
        patch("womtrees.tmux.session_exists", return_value=True),
        patch("womtrees.tmux.attach"),
        patch("womtrees.claude.is_pid_alive", side_effect=pid_alive),
    ):
        # Create two work items with sessions
        runner.invoke(cli, ["todo", "-b", "feat/x"])
        runner.invoke(cli, ["start", "1"])

        conn = get_conn_fn()
        from womtrees.db import list_claude_sessions, update_claude_session

        # First session: dead (PID 11111)
        sessions = list_claude_sessions(conn)
        update_claude_session(
            conn,
            sessions[0].id,
            claude_session_id="uuid-1",
            pid=11111,
        )

        # Create a second work item + session with a live PID
        runner.invoke(cli, ["todo", "-b", "feat/y"])
        with patch(
            "womtrees.tmux.create_session",
            return_value=("myrepo-feat-y", "%2"),
        ):
            runner.invoke(cli, ["start", "2"])
        sessions = list_claude_sessions(conn, work_item_id=2)
        update_claude_session(conn, sessions[0].id, pid=22222)

        mock_send_keys.reset_mock()

        result = runner.invoke(cli, ["attach", "1"])
        assert result.exit_code == 0

        # Should NOT resume — another session is still alive
        mock_send_keys.assert_not_called()


def test_todo_with_repo_option(runner, db_conn, tmp_path):
    """Test that -r option overrides current repo detection."""
    get_conn_fn, db_path = db_conn
    target_repo = tmp_path / "other-project"
    target_repo.mkdir()

    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch(
            "womtrees.cli.utils.get_current_repo",
            return_value=("myrepo", "/tmp/myrepo"),
        ),
    ):
        result = runner.invoke(
            cli,
            ["todo", "-b", "feat/x", "-r", str(target_repo), "some task"],
        )
        assert result.exit_code == 0
        assert "Created TODO #1" in result.output

        # Verify the item was created with the specified repo
        conn = get_conn_fn()
        from womtrees.db import get_work_item

        item = get_work_item(conn, 1)
        assert item.repo_name == "other-project"
        assert item.repo_path == str(target_repo)


def test_todo_with_repo_option_no_git_required(runner, db_conn, tmp_path):
    """Test that -r works even when not in a git repo."""
    get_conn_fn, db_path = db_conn
    target_repo = tmp_path / "standalone"
    target_repo.mkdir()

    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch("womtrees.cli.utils.get_current_repo", return_value=None),
    ):
        result = runner.invoke(
            cli,
            ["todo", "-b", "feat/y", "-r", str(target_repo), "some task"],
        )
        assert result.exit_code == 0
        assert "Created TODO #1" in result.output


def test_edit_name_only(runner, db_conn):
    """Test editing just the name of a todo item."""
    get_conn_fn, db_path = db_conn
    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch(
            "womtrees.cli.utils.get_current_repo",
            return_value=("myrepo", "/tmp/myrepo"),
        ),
    ):
        runner.invoke(cli, ["todo", "-b", "feat/x", "-n", "old name"])
        result = runner.invoke(cli, ["edit", "1", "--name", "new name"])
        assert result.exit_code == 0
        assert "Updated #1" in result.output

        conn = get_conn_fn()
        from womtrees.db import get_work_item

        item = get_work_item(conn, 1)
        assert item.name == "new name"
        assert item.branch == "feat/x"


def test_edit_branch_todo_item(runner, db_conn):
    """Test editing the branch of a todo item (no worktree)."""
    get_conn_fn, db_path = db_conn
    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch(
            "womtrees.cli.utils.get_current_repo",
            return_value=("myrepo", "/tmp/myrepo"),
        ),
    ):
        runner.invoke(cli, ["todo", "-b", "feat/old"])
        result = runner.invoke(cli, ["edit", "1", "--branch", "feat/new"])
        assert result.exit_code == 0
        assert "Updated #1" in result.output

        conn = get_conn_fn()
        from womtrees.db import get_work_item

        item = get_work_item(conn, 1)
        assert item.branch == "feat/new"


def test_edit_branch_active_item(runner, db_conn, tmp_path):
    """Test editing branch on an active item renames the git branch."""
    get_conn_fn, db_path = db_conn

    mock_config = MagicMock()
    mock_config.base_dir = tmp_path / "worktrees"
    mock_config.tmux_split = "vertical"
    mock_config.tmux_claude_pane = "right"

    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch(
            "womtrees.cli.utils.get_current_repo",
            return_value=("myrepo", "/tmp/myrepo"),
        ),
        patch("womtrees.cli.items.get_config", return_value=mock_config),
        patch(
            "womtrees.services.workitem.create_worktree",
            return_value=tmp_path / "worktrees" / "myrepo" / "feat-old",
        ),
        patch("womtrees.tmux.is_available", return_value=True),
        patch("womtrees.tmux.create_session", return_value=("myrepo/feat-old", "%0")),
        patch("womtrees.tmux.set_environment"),
        patch("womtrees.tmux.split_pane", return_value="%1"),
        patch("womtrees.tmux.send_keys"),
        patch("womtrees.tmux.session_exists", return_value=True),
        patch("womtrees.services.workitem.rename_branch") as mock_rename,
        patch(
            "womtrees.tmux.rename_session",
            return_value="myrepo-feat-new",
        ) as mock_rename_session,
    ):
        runner.invoke(cli, ["todo", "-b", "feat/old"])
        runner.invoke(cli, ["start", "1"])

        result = runner.invoke(cli, ["edit", "1", "--branch", "feat/new"])
        assert result.exit_code == 0
        assert "Updated #1" in result.output

        mock_rename.assert_called_once_with(
            str(tmp_path / "worktrees" / "myrepo" / "feat-old"),
            "feat/old",
            "feat/new",
        )
        mock_rename_session.assert_called_once()

        conn = get_conn_fn()
        from womtrees.db import get_work_item

        item = get_work_item(conn, 1)
        assert item.branch == "feat/new"
        # tmux_session must be sanitized (no slashes) to match actual tmux name
        assert "/" not in item.tmux_session
        assert item.tmux_session == "myrepo-feat-new"


def test_edit_branch_blocked_by_open_pr(runner, db_conn):
    """Test that editing branch is rejected when an open PR exists."""
    get_conn_fn, db_path = db_conn
    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch(
            "womtrees.cli.utils.get_current_repo",
            return_value=("myrepo", "/tmp/myrepo"),
        ),
    ):
        runner.invoke(cli, ["todo", "-b", "feat/x"])

        from womtrees.db import create_pull_request

        conn = get_conn_fn()
        create_pull_request(conn, 1, number=42, owner="user", repo="myrepo")

        result = runner.invoke(cli, ["edit", "1", "--branch", "feat/y"])
        assert result.exit_code != 0
        assert "open PR" in result.output


def test_edit_duplicate_branch(runner, db_conn):
    """Test that editing to a duplicate active branch is rejected."""
    get_conn_fn, db_path = db_conn
    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch(
            "womtrees.cli.utils.get_current_repo",
            return_value=("myrepo", "/tmp/myrepo"),
        ),
    ):
        runner.invoke(cli, ["todo", "-b", "feat/a"])
        runner.invoke(cli, ["todo", "-b", "feat/b"])

        result = runner.invoke(cli, ["edit", "2", "--branch", "feat/a"])
        assert result.exit_code != 0
        assert "already used" in result.output


def test_edit_no_options(runner, db_conn):
    """Test that edit requires at least --name or --branch."""
    get_conn_fn, db_path = db_conn
    with patch("womtrees.db.get_connection", get_conn_fn):
        result = runner.invoke(cli, ["edit", "1"])
        assert result.exit_code != 0
        assert "Provide --name, --branch, and/or --prompt" in result.output


def test_edit_nonexistent(runner, db_conn):
    """Test editing a non-existent item."""
    get_conn_fn, db_path = db_conn
    with patch("womtrees.db.get_connection", get_conn_fn):
        result = runner.invoke(cli, ["edit", "999", "--name", "test"])
        assert result.exit_code != 0
        assert "not found" in result.output


def test_create_with_repo_option(runner, db_conn, tmp_path):
    """Test that create command also accepts -r option."""
    get_conn_fn, db_path = db_conn
    target_repo = tmp_path / "another-project"
    target_repo.mkdir()

    mock_config = MagicMock()
    mock_config.base_dir = tmp_path / "worktrees"
    mock_config.tmux_split = "vertical"
    mock_config.tmux_claude_pane = "right"

    with (
        patch("womtrees.db.get_connection", get_conn_fn),
        patch(
            "womtrees.cli.utils.get_current_repo",
            return_value=("myrepo", "/tmp/myrepo"),
        ),
        patch("womtrees.cli.items.get_config", return_value=mock_config),
        patch(
            "womtrees.services.workitem.create_worktree",
            return_value=tmp_path / "worktrees" / "another-project" / "feat-z",
        ),
        patch("womtrees.tmux.is_available", return_value=True),
        patch(
            "womtrees.tmux.create_session",
            return_value=("another-project/feat-z", "%0"),
        ),
        patch("womtrees.tmux.set_environment"),
        patch("womtrees.tmux.split_pane", return_value="%1"),
        patch("womtrees.tmux.send_keys"),
    ):
        result = runner.invoke(cli, ["create", "-b", "feat/z", "-r", str(target_repo)])
        assert result.exit_code == 0

        conn = get_conn_fn()
        from womtrees.db import get_work_item

        item = get_work_item(conn, 1)
        assert item.repo_name == "another-project"
        assert item.repo_path == str(target_repo)


def test_cd_tree_default(runner, tmp_path):
    """Cd with no flags prints worktree toplevel."""
    mock_result = MagicMock()
    mock_result.stdout = f"{tmp_path}/my-worktree\n"
    mock_result.returncode = 0

    with patch("subprocess.run", return_value=mock_result):
        result = runner.invoke(cli, ["cd"], catch_exceptions=False)
        assert result.exit_code == 0
        assert result.output.strip() == f"{tmp_path}/my-worktree"


def test_cd_root(runner, tmp_path):
    """Cd --root prints the main repository root."""
    with patch(
        "womtrees.worktree.get_current_repo",
        return_value=("myrepo", str(tmp_path / "myrepo")),
    ):
        result = runner.invoke(cli, ["cd", "--root"], catch_exceptions=False)
        assert result.exit_code == 0
        assert result.output.strip() == str(tmp_path / "myrepo")


def test_cd_root_not_in_repo(runner):
    """Cd --root outside a git repo fails."""
    with patch("womtrees.worktree.get_current_repo", return_value=None):
        result = runner.invoke(cli, ["cd", "--root"])
        assert result.exit_code != 0
        assert "Not inside a git repository" in result.output


def test_cd_tree_not_in_repo(runner):
    """Cd --tree outside a git repo fails."""
    with patch(
        "subprocess.run",
        side_effect=subprocess.CalledProcessError(128, "git"),
    ):
        result = runner.invoke(cli, ["cd", "--tree"])
        assert result.exit_code != 0
        assert "Not inside a git repository" in result.output
