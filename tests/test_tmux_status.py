from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from womtrees.cli import cli
from womtrees.claude import configure_tmux_status_bar
from womtrees.db import _ensure_schema, create_claude_session


def _make_conn(tmp_path: Path):
    """Create a test DB connection factory."""
    db_path = tmp_path / "test.db"

    def get_conn(db_path_arg=None):
        c = sqlite3.connect(str(db_path))
        c.row_factory = sqlite3.Row
        _ensure_schema(c)
        return c

    return get_conn


# -- wt status --tmux tests --


def test_status_tmux_no_waiting(tmp_path):
    get_conn = _make_conn(tmp_path)
    runner = CliRunner()

    with patch("womtrees.db.get_connection", get_conn):
        result = runner.invoke(cli, ["status", "--tmux"])

    assert result.exit_code == 0
    assert result.output.strip() == "wt: 0"


def test_status_tmux_one_waiting(tmp_path):
    get_conn = _make_conn(tmp_path)
    conn = get_conn()
    create_claude_session(
        conn,
        repo_name="myrepo",
        repo_path="/tmp/myrepo",
        branch="fix/auth",
        tmux_session="test",
        tmux_pane="%0",
        state="waiting",
    )
    conn.close()

    runner = CliRunner()
    with patch("womtrees.db.get_connection", get_conn):
        result = runner.invoke(cli, ["status", "--tmux"])

    assert result.exit_code == 0
    assert "1 waiting" in result.output
    assert "fix/auth" in result.output


def test_status_tmux_multiple_waiting(tmp_path):
    get_conn = _make_conn(tmp_path)
    conn = get_conn()
    for branch in ["fix/auth", "feat/api", "refactor/db"]:
        create_claude_session(
            conn,
            repo_name="myrepo",
            repo_path="/tmp/myrepo",
            branch=branch,
            tmux_session="test",
            tmux_pane=f"%{branch}",
            state="waiting",
        )
    conn.close()

    runner = CliRunner()
    with patch("womtrees.db.get_connection", get_conn):
        result = runner.invoke(cli, ["status", "--tmux"])

    assert result.exit_code == 0
    assert "3 waiting" in result.output


def test_status_tmux_ignores_working_sessions(tmp_path):
    get_conn = _make_conn(tmp_path)
    conn = get_conn()
    create_claude_session(
        conn,
        repo_name="myrepo",
        repo_path="/tmp/myrepo",
        branch="fix/auth",
        tmux_session="test",
        tmux_pane="%0",
        state="working",
    )
    conn.close()

    runner = CliRunner()
    with patch("womtrees.db.get_connection", get_conn):
        result = runner.invoke(cli, ["status", "--tmux"])

    assert result.exit_code == 0
    assert result.output.strip() == "wt: 0"


# -- configure_tmux_status_bar tests --


def test_configure_tmux_fresh(tmp_path):
    conf = tmp_path / ".tmux.conf"

    with patch("womtrees.claude.TMUX_CONF", conf), patch("subprocess.run"):
        result = configure_tmux_status_bar()

    assert result is True
    content = conf.read_text()
    assert "wt status --tmux" in content
    assert "status-interval 5" in content


def test_configure_tmux_idempotent(tmp_path):
    conf = tmp_path / ".tmux.conf"
    conf.write_text('set -g status-right "#(wt status --tmux) | %H:%M"\n')

    with patch("womtrees.claude.TMUX_CONF", conf), patch("subprocess.run"):
        result = configure_tmux_status_bar()

    assert result is False


def test_configure_tmux_preserves_existing(tmp_path):
    conf = tmp_path / ".tmux.conf"
    conf.write_text("set -g mouse on\nbind r source-file ~/.tmux.conf\n")

    with patch("womtrees.claude.TMUX_CONF", conf), patch("subprocess.run"):
        configure_tmux_status_bar()

    content = conf.read_text()
    assert "set -g mouse on" in content
    assert "bind r source-file" in content
    assert "wt status --tmux" in content


def test_configure_tmux_comments_out_existing_status_right(tmp_path):
    conf = tmp_path / ".tmux.conf"
    conf.write_text('set -g status-right "%H:%M"\nset -g status-interval 15\n')

    with patch("womtrees.claude.TMUX_CONF", conf), patch("subprocess.run"):
        configure_tmux_status_bar()

    content = conf.read_text()
    # Old settings should be commented out
    assert '# set -g status-right "%H:%M"' in content
    assert "# set -g status-interval 15" in content
    # New settings should be present
    assert 'set -g status-right "#(wt status --tmux) | %H:%M"' in content
    assert "set -g status-interval 5" in content
