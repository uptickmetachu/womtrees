from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from womtrees.cli import cli
from womtrees.db import (
    _ensure_schema,
    create_claude_session,
    create_work_item,
    update_work_item,
)


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def db_conn(tmp_path):
    db_path = tmp_path / "test.db"

    init_conn = sqlite3.connect(str(db_path))
    init_conn.row_factory = sqlite3.Row
    init_conn.execute("PRAGMA foreign_keys=ON")
    _ensure_schema(init_conn)
    init_conn.close()

    def _get_conn(db_path_arg=None):
        c = sqlite3.connect(str(db_path))
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        return c

    return _get_conn, db_path


# -- play_notification tests --


def test_play_notification_uses_review_sound_by_default():
    """Test that play_notification defaults to review sound."""
    mock_config = MagicMock()
    mock_config.sound_enabled = True
    mock_config.sound_review = "notification"
    mock_config.sound_input = "triplet"

    with (
        patch("womtrees.config.get_config", return_value=mock_config),
        patch("womtrees.sound.sys") as mock_sys,
        patch("womtrees.sound.shutil") as mock_shutil,
        patch("womtrees.sound.subprocess") as mock_subprocess,
    ):
        mock_sys.platform = "darwin"
        mock_shutil.which.return_value = "/usr/bin/afplay"

        from womtrees.sound import play_notification

        play_notification()
        mock_subprocess.Popen.assert_called_once()
        args = mock_subprocess.Popen.call_args[0][0]
        assert args[0] == "/usr/bin/afplay"
        assert args[1].endswith("notification.wav")


def test_play_notification_uses_input_sound():
    """Test that play_notification uses input sound when state=input."""
    mock_config = MagicMock()
    mock_config.sound_enabled = True
    mock_config.sound_review = "notification"
    mock_config.sound_input = "triplet"

    with (
        patch("womtrees.config.get_config", return_value=mock_config),
        patch("womtrees.sound.sys") as mock_sys,
        patch("womtrees.sound.shutil") as mock_shutil,
        patch("womtrees.sound.subprocess") as mock_subprocess,
    ):
        mock_sys.platform = "darwin"
        mock_shutil.which.return_value = "/usr/bin/afplay"

        from womtrees.sound import play_notification

        play_notification(state="input")
        mock_subprocess.Popen.assert_called_once()
        args = mock_subprocess.Popen.call_args[0][0]
        assert args[1].endswith("triplet.wav")


def test_play_notification_custom_path(tmp_path):
    """Test that play_notification accepts a file path as sound."""
    custom_wav = tmp_path / "custom.wav"
    custom_wav.write_bytes(b"RIFF")

    mock_config = MagicMock()
    mock_config.sound_enabled = True
    mock_config.sound_review = str(custom_wav)
    mock_config.sound_input = "triplet"

    with (
        patch("womtrees.config.get_config", return_value=mock_config),
        patch("womtrees.sound.sys") as mock_sys,
        patch("womtrees.sound.shutil") as mock_shutil,
        patch("womtrees.sound.subprocess") as mock_subprocess,
    ):
        mock_sys.platform = "darwin"
        mock_shutil.which.return_value = "/usr/bin/afplay"

        from womtrees.sound import play_notification

        play_notification(state="review")
        mock_subprocess.Popen.assert_called_once()
        args = mock_subprocess.Popen.call_args[0][0]
        assert args[1] == str(custom_wav)


def test_play_notification_respects_disabled_config():
    """Test that play_notification does nothing when sound is disabled."""
    mock_config = MagicMock()
    mock_config.sound_enabled = False

    with (
        patch("womtrees.config.get_config", return_value=mock_config),
        patch("womtrees.sound.subprocess") as mock_subprocess,
    ):
        from womtrees.sound import play_notification

        play_notification()
        mock_subprocess.Popen.assert_not_called()


def test_play_notification_silent_on_missing_player():
    """Test that play_notification fails silently with no audio player."""
    mock_config = MagicMock()
    mock_config.sound_enabled = True
    mock_config.sound_review = "notification"

    with (
        patch("womtrees.config.get_config", return_value=mock_config),
        patch("womtrees.sound.shutil") as mock_shutil,
        patch("womtrees.sound.subprocess") as mock_subprocess,
    ):
        mock_shutil.which.return_value = None

        from womtrees.sound import play_notification

        play_notification()
        mock_subprocess.Popen.assert_not_called()


def test_play_notification_silent_on_invalid_path():
    """Test that play_notification fails silently with a bad path."""
    mock_config = MagicMock()
    mock_config.sound_enabled = True
    mock_config.sound_review = "/nonexistent/path/sound.wav"

    with (
        patch("womtrees.config.get_config", return_value=mock_config),
        patch("womtrees.sound.subprocess") as mock_subprocess,
    ):
        from womtrees.sound import play_notification

        play_notification(state="review")
        mock_subprocess.Popen.assert_not_called()


# -- Config tests --


def test_config_sound_enabled_default():
    """Test that sound_enabled defaults to True."""
    from womtrees.config import Config

    with patch("womtrees.config.CONFIG_FILE") as mock_file:
        mock_file.exists.return_value = False
        config = Config.load()
        assert config.sound_enabled is True
        assert config.sound_input == "triplet"
        assert config.sound_review == "notification"


def test_config_sound_enabled_false(tmp_path):
    """Test that sound_enabled reads from config."""
    config_file = tmp_path / "config.toml"
    config_file.write_text("[notifications]\nsound = false\n")

    from womtrees.config import Config

    with patch("womtrees.config.CONFIG_FILE", config_file):
        config = Config.load()
        assert config.sound_enabled is False


def test_config_custom_sounds(tmp_path):
    """Test that custom sound names are read from config."""
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        '[notifications]\nsound = true\ninput_sound = "warble"\n'
        'review_sound = "nudge"\n'
    )

    from womtrees.config import Config

    with patch("womtrees.config.CONFIG_FILE", config_file):
        config = Config.load()
        assert config.sound_input == "warble"
        assert config.sound_review == "nudge"


# -- Hook integration tests --


def test_hook_input_plays_sound_with_state(runner, db_conn):
    """Test that input hook plays notification with state=input."""
    get_conn_fn, _db_path = db_conn

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
        patch("womtrees.sound.play_notification") as mock_play,
    ):
        result = runner.invoke(cli, ["hook", "input"])
        assert result.exit_code == 0
        mock_play.assert_called_once_with(state="input")


def test_hook_stop_plays_sound_with_state(runner, db_conn):
    """Test that stop hook plays notification with state=review."""
    get_conn_fn, _db_path = db_conn

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
        patch("womtrees.sound.play_notification") as mock_play,
    ):
        result = runner.invoke(cli, ["hook", "stop"])
        assert result.exit_code == 0
        mock_play.assert_called_once_with(state="review")


def test_hook_heartbeat_does_not_play_sound(runner, db_conn):
    """Test that heartbeat hook does NOT play notification sound."""
    get_conn_fn, _db_path = db_conn

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
        patch("womtrees.sound.play_notification") as mock_play,
    ):
        result = runner.invoke(cli, ["hook", "heartbeat"])
        assert result.exit_code == 0
        mock_play.assert_not_called()


def test_hook_no_sound_when_status_unchanged(runner, db_conn):
    """Test that no sound plays when item is already in input status."""
    get_conn_fn, _db_path = db_conn

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
        patch("womtrees.sound.play_notification") as mock_play,
    ):
        result = runner.invoke(cli, ["hook", "input"])
        assert result.exit_code == 0
        mock_play.assert_not_called()
