from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from womtrees.cli import cli
from womtrees.db import get_connection, _ensure_schema


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
    _ensure_schema(conn)

    def _get_conn(db_path_arg=None):
        c = sqlite3.connect(str(db_path))
        c.row_factory = sqlite3.Row
        _ensure_schema(c)
        return c

    return _get_conn, db_path


@pytest.fixture
def git_repo(tmp_path):
    repo = tmp_path / "myrepo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--allow-empty", "-m", "init"],
        check=True,
        capture_output=True,
    )
    return repo


def test_help(runner):
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "womtrees" in result.output


def test_todo_not_in_repo(runner, tmp_path, db_conn):
    get_conn_fn, db_path = db_conn
    with patch("womtrees.cli.get_connection", get_conn_fn), \
         patch("womtrees.cli.get_current_repo", return_value=None):
        result = runner.invoke(cli, ["todo", "-b", "feat/x", "-p", "test"])
        assert result.exit_code != 0
        assert "Not inside a git repository" in result.output


def test_todo_creates_item(runner, db_conn):
    get_conn_fn, db_path = db_conn
    with patch("womtrees.cli.get_connection", get_conn_fn), \
         patch("womtrees.cli.get_current_repo", return_value=("myrepo", "/tmp/myrepo")):
        result = runner.invoke(cli, ["todo", "-b", "feat/x", "-p", "do stuff"])
        assert result.exit_code == 0
        assert "Created TODO #1" in result.output


def test_list_empty(runner, db_conn):
    get_conn_fn, db_path = db_conn
    with patch("womtrees.cli.get_connection", get_conn_fn), \
         patch("womtrees.cli.get_current_repo", return_value=("myrepo", "/tmp/myrepo")):
        result = runner.invoke(cli, ["list"])
        assert result.exit_code == 0
        assert "No work items found" in result.output


def test_list_shows_items(runner, db_conn):
    get_conn_fn, db_path = db_conn
    with patch("womtrees.cli.get_connection", get_conn_fn), \
         patch("womtrees.cli.get_current_repo", return_value=("myrepo", "/tmp/myrepo")):
        runner.invoke(cli, ["todo", "-b", "feat/a", "-p", "first"])
        runner.invoke(cli, ["todo", "-b", "feat/b", "-p", "second"])

        result = runner.invoke(cli, ["list"])
        assert result.exit_code == 0
        assert "feat/a" in result.output
        assert "feat/b" in result.output


def test_status_summary(runner, db_conn):
    get_conn_fn, db_path = db_conn
    with patch("womtrees.cli.get_connection", get_conn_fn), \
         patch("womtrees.cli.get_current_repo", return_value=("myrepo", "/tmp/myrepo")):
        runner.invoke(cli, ["todo", "-b", "feat/a"])
        runner.invoke(cli, ["todo", "-b", "feat/b"])

        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "todo: 2" in result.output


def test_status_single(runner, db_conn):
    get_conn_fn, db_path = db_conn
    with patch("womtrees.cli.get_connection", get_conn_fn), \
         patch("womtrees.cli.get_current_repo", return_value=("myrepo", "/tmp/myrepo")):
        runner.invoke(cli, ["todo", "-b", "feat/a", "-p", "my prompt"])

        result = runner.invoke(cli, ["status", "1"])
        assert result.exit_code == 0
        assert "feat/a" in result.output
        assert "my prompt" in result.output


def test_review_transition(runner, db_conn):
    get_conn_fn, db_path = db_conn
    with patch("womtrees.cli.get_connection", get_conn_fn), \
         patch("womtrees.cli.get_current_repo", return_value=("myrepo", "/tmp/myrepo")):
        runner.invoke(cli, ["todo", "-b", "feat/a"])

        # Can't review a TODO
        result = runner.invoke(cli, ["review", "1"])
        assert result.exit_code != 0
        assert "expected 'working'" in result.output


def test_done_transition(runner, db_conn):
    get_conn_fn, db_path = db_conn
    with patch("womtrees.cli.get_connection", get_conn_fn), \
         patch("womtrees.cli.get_current_repo", return_value=("myrepo", "/tmp/myrepo")):
        runner.invoke(cli, ["todo", "-b", "feat/a"])

        # Can't mark TODO as done
        result = runner.invoke(cli, ["done", "1"])
        assert result.exit_code != 0
        assert "expected 'review'" in result.output


def test_delete_todo(runner, db_conn):
    get_conn_fn, db_path = db_conn
    with patch("womtrees.cli.get_connection", get_conn_fn), \
         patch("womtrees.cli.get_current_repo", return_value=("myrepo", "/tmp/myrepo")):
        runner.invoke(cli, ["todo", "-b", "feat/a"])

        result = runner.invoke(cli, ["delete", "1"])
        assert result.exit_code == 0
        assert "Deleted #1" in result.output

        result = runner.invoke(cli, ["list"])
        assert "No work items found" in result.output


def test_delete_nonexistent(runner, db_conn):
    get_conn_fn, db_path = db_conn
    with patch("womtrees.cli.get_connection", get_conn_fn):
        result = runner.invoke(cli, ["delete", "999"])
        assert result.exit_code != 0
        assert "not found" in result.output


def test_config_show(runner, tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text('[worktrees]\nbase_dir = "/tmp/wt"\n')
    with patch("womtrees.cli.ensure_config", return_value=config_file):
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

    with patch("womtrees.cli.get_connection", get_conn_fn), \
         patch("womtrees.cli.get_current_repo", return_value=("myrepo", "/tmp/myrepo")), \
         patch("womtrees.cli.get_config", return_value=mock_config), \
         patch("womtrees.cli.create_worktree", return_value=tmp_path / "worktrees" / "myrepo" / "feat-x"), \
         patch("womtrees.tmux.is_available", return_value=True), \
         patch("womtrees.tmux.create_session", return_value=("myrepo/feat-x", "%0")) as mock_create, \
         patch("womtrees.tmux.set_environment") as mock_setenv, \
         patch("womtrees.tmux.split_pane", return_value="%1") as mock_split, \
         patch("womtrees.tmux.swap_pane") as mock_swap, \
         patch("womtrees.tmux.send_keys"):
        runner.invoke(cli, ["todo", "-b", "feat/x", "-p", "test prompt"])

        result = runner.invoke(cli, ["start", "1"])
        assert result.exit_code == 0
        assert "Started #1" in result.output
        assert "myrepo/feat-x" in result.output

        mock_create.assert_called_once()
        mock_setenv.assert_called_once_with("myrepo/feat-x", "WOMTREE_WORK_ITEM_ID", "1")
        mock_split.assert_called_once()
        mock_swap.assert_called_once()  # claude_pane=left triggers swap


def test_start_no_swap_when_claude_right(runner, db_conn, tmp_path):
    """Test that swap_pane is NOT called when claude_pane is 'right'."""
    get_conn_fn, db_path = db_conn

    mock_config = MagicMock()
    mock_config.base_dir = tmp_path / "worktrees"
    mock_config.tmux_split = "vertical"
    mock_config.tmux_claude_pane = "right"

    with patch("womtrees.cli.get_connection", get_conn_fn), \
         patch("womtrees.cli.get_current_repo", return_value=("myrepo", "/tmp/myrepo")), \
         patch("womtrees.cli.get_config", return_value=mock_config), \
         patch("womtrees.cli.create_worktree", return_value=tmp_path / "worktrees" / "myrepo" / "feat-x"), \
         patch("womtrees.tmux.is_available", return_value=True), \
         patch("womtrees.tmux.create_session", return_value=("myrepo/feat-x", "%0")), \
         patch("womtrees.tmux.set_environment"), \
         patch("womtrees.tmux.split_pane", return_value="%1"), \
         patch("womtrees.tmux.swap_pane") as mock_swap, \
         patch("womtrees.tmux.send_keys"):
        runner.invoke(cli, ["todo", "-b", "feat/x"])
        result = runner.invoke(cli, ["start", "1"])
        assert result.exit_code == 0
        mock_swap.assert_not_called()


def test_start_fails_without_tmux(runner, db_conn):
    """Test that start fails gracefully when tmux is not installed."""
    get_conn_fn, db_path = db_conn

    mock_config = MagicMock()

    with patch("womtrees.cli.get_connection", get_conn_fn), \
         patch("womtrees.cli.get_current_repo", return_value=("myrepo", "/tmp/myrepo")), \
         patch("womtrees.cli.get_config", return_value=mock_config), \
         patch("womtrees.tmux.is_available", return_value=False):
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

    with patch("womtrees.cli.get_connection", get_conn_fn), \
         patch("womtrees.cli.get_current_repo", return_value=("myrepo", "/tmp/myrepo")), \
         patch("womtrees.cli.get_config", return_value=mock_config), \
         patch("womtrees.cli.create_worktree", return_value=tmp_path / "worktrees" / "myrepo" / "feat-x"), \
         patch("womtrees.cli.remove_worktree"), \
         patch("womtrees.tmux.is_available", return_value=True), \
         patch("womtrees.tmux.create_session", return_value=("myrepo/feat-x", "%0")), \
         patch("womtrees.tmux.set_environment"), \
         patch("womtrees.tmux.split_pane", return_value="%1"), \
         patch("womtrees.tmux.swap_pane"), \
         patch("womtrees.tmux.send_keys"), \
         patch("womtrees.tmux.session_exists", return_value=True), \
         patch("womtrees.tmux.kill_session") as mock_kill:
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

    with patch("womtrees.cli.get_connection", get_conn_fn), \
         patch("womtrees.cli.get_current_repo", return_value=("myrepo", "/tmp/myrepo")), \
         patch("womtrees.cli.get_config", return_value=mock_config), \
         patch("womtrees.cli.create_worktree", return_value=tmp_path / "worktrees" / "myrepo" / "feat-x"), \
         patch("womtrees.tmux.is_available", return_value=True), \
         patch("womtrees.tmux.create_session", return_value=("myrepo/feat-x", "%0")), \
         patch("womtrees.tmux.set_environment"), \
         patch("womtrees.tmux.split_pane", return_value="%1"), \
         patch("womtrees.tmux.swap_pane"), \
         patch("womtrees.tmux.send_keys"), \
         patch("womtrees.tmux.session_exists", return_value=True), \
         patch("womtrees.tmux.attach") as mock_attach:
        runner.invoke(cli, ["todo", "-b", "feat/x"])
        runner.invoke(cli, ["start", "1"])

        result = runner.invoke(cli, ["attach", "1"])
        assert result.exit_code == 0
        mock_attach.assert_called_once_with("myrepo/feat-x")


def test_attach_no_session(runner, db_conn):
    """Test wt attach fails when work item has no tmux session."""
    get_conn_fn, db_path = db_conn

    with patch("womtrees.cli.get_connection", get_conn_fn), \
         patch("womtrees.cli.get_current_repo", return_value=("myrepo", "/tmp/myrepo")):
        runner.invoke(cli, ["todo", "-b", "feat/x"])

        result = runner.invoke(cli, ["attach", "1"])
        assert result.exit_code != 0
        assert "no tmux session" in result.output
