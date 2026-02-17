from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from womtrees.claude import detect_context, install_global_hooks, is_pid_alive


@patch("womtrees.claude.CLAUDE_SETTINGS_DIR")
@patch("womtrees.claude.CLAUDE_SETTINGS_FILE")
def test_install_global_hooks_fresh(mock_file, mock_dir, tmp_path) -> None:
    """Test installing hooks when no settings file exists."""
    settings_file = tmp_path / "settings.json"
    mock_file.__eq__ = lambda self, other: False
    mock_file.exists.return_value = False

    # Patch the actual file operations
    with (
        patch("womtrees.claude.CLAUDE_SETTINGS_DIR", tmp_path),
        patch("womtrees.claude.CLAUDE_SETTINGS_FILE", settings_file),
    ):
        install_global_hooks()

    data = json.loads(settings_file.read_text())
    assert "hooks" in data
    assert "PostToolUse" in data["hooks"]
    assert "Stop" in data["hooks"]
    # New format: each entry has a "hooks" array with handler objects
    assert any(
        any(
            "wt hook heartbeat" in handler.get("command", "")
            for handler in entry.get("hooks", [])
        )
        for entry in data["hooks"]["PostToolUse"]
    )
    assert any(
        any(
            "wt hook stop" in handler.get("command", "")
            for handler in entry.get("hooks", [])
        )
        for entry in data["hooks"]["Stop"]
    )


@patch("womtrees.claude.CLAUDE_SETTINGS_DIR")
@patch("womtrees.claude.CLAUDE_SETTINGS_FILE")
def test_install_global_hooks_existing(mock_file, mock_dir, tmp_path) -> None:
    """Test installing hooks preserves existing settings."""
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(json.dumps({"existing_key": "value", "hooks": {}}))

    with (
        patch("womtrees.claude.CLAUDE_SETTINGS_DIR", tmp_path),
        patch("womtrees.claude.CLAUDE_SETTINGS_FILE", settings_file),
    ):
        install_global_hooks()

    data = json.loads(settings_file.read_text())
    assert data["existing_key"] == "value"
    assert "PostToolUse" in data["hooks"]


@patch("womtrees.claude.CLAUDE_SETTINGS_DIR")
@patch("womtrees.claude.CLAUDE_SETTINGS_FILE")
def test_install_global_hooks_no_duplicate(mock_file, mock_dir, tmp_path) -> None:
    """Test that installing hooks twice doesn't duplicate."""
    settings_file = tmp_path / "settings.json"

    with (
        patch("womtrees.claude.CLAUDE_SETTINGS_DIR", tmp_path),
        patch("womtrees.claude.CLAUDE_SETTINGS_FILE", settings_file),
    ):
        install_global_hooks()
        install_global_hooks()

    data = json.loads(settings_file.read_text())
    # Should only have one heartbeat hook entry
    heartbeat_entries = [
        entry
        for entry in data["hooks"]["PostToolUse"]
        if any(
            "wt hook" in handler.get("command", "")
            for handler in entry.get("hooks", [])
        )
    ]
    assert len(heartbeat_entries) == 1


@patch("subprocess.run")
def test_detect_context(mock_run) -> None:
    """Test context detection with mocked environment."""

    def side_effect(args, **kwargs):
        result = MagicMock()
        if args[:2] == ["tmux", "display-message"]:
            result.stdout = "myrepo/feat-auth\n"
            result.returncode = 0
        elif args[:2] == ["tmux", "show-environment"]:
            result.stdout = "WOMTREE_WORK_ITEM_ID=42\n"
            result.returncode = 0
        elif args[:2] == ["git", "rev-parse"]:
            if "--git-common-dir" in args:
                result.stdout = "/home/user/myrepo/.git\n"
            else:
                result.stdout = "/home/user/myrepo\n"
            result.returncode = 0
        elif args[:2] == ["git", "branch"]:
            result.stdout = "feat/auth\n"
            result.returncode = 0
        else:
            result.returncode = 1
        return result

    mock_run.side_effect = side_effect

    with patch.dict("os.environ", {"TMUX_PANE": "%1"}):
        ctx = detect_context()

    assert ctx["tmux_session"] == "myrepo/feat-auth"
    assert ctx["tmux_pane"] == "%1"
    assert ctx["repo_name"] == "myrepo"
    assert ctx["repo_path"] == "/home/user/myrepo"
    assert ctx["branch"] == "feat/auth"
    assert ctx["work_item_id"] == 42


@patch("subprocess.run")
def test_detect_context_no_tmux(mock_run) -> None:
    """Test context detection outside tmux."""
    mock_run.side_effect = FileNotFoundError

    with patch.dict("os.environ", {}, clear=True):
        ctx = detect_context()

    assert ctx["tmux_session"] is None
    assert ctx["tmux_pane"] == ""


def test_is_pid_alive_current_process() -> None:
    """Test that our own PID is alive."""
    import os

    assert is_pid_alive(os.getpid()) is True


def test_is_pid_alive_dead_process() -> None:
    """Test that a very large PID is not alive."""
    assert is_pid_alive(999999999) is False
