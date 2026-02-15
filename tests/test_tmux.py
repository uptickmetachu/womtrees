from __future__ import annotations

from unittest.mock import MagicMock, patch, call

from womtrees.tmux import (
    attach,
    create_session,
    is_available,
    kill_session,
    rename_session,
    sanitize_session_name,
    send_keys,
    session_exists,
    set_environment,
    split_pane,
    swap_pane,
)


def test_sanitize_session_name():
    assert sanitize_session_name("repo/branch") == "repo-branch"
    assert sanitize_session_name("repo.name:branch") == "repo-name-branch"
    assert sanitize_session_name("simple") == "simple"
    assert sanitize_session_name("my repo/feat") == "my-repo-feat"


@patch("womtrees.tmux._run")
@patch("womtrees.tmux.session_exists", return_value=False)
def test_create_session(mock_exists, mock_run):
    mock_run.return_value = MagicMock(stdout="%0\n")
    name, pane_id = create_session("repo/branch", "/tmp/wt")
    assert name == "repo-branch"
    assert pane_id == "%0"
    mock_run.assert_called_once_with(
        [
            "tmux",
            "new-session",
            "-d",
            "-s",
            "repo-branch",
            "-c",
            "/tmp/wt",
            "-P",
            "-F",
            "#{pane_id}",
        ]
    )


@patch("womtrees.tmux._run")
@patch("womtrees.tmux.session_exists", side_effect=[True, False])
def test_create_session_name_conflict(mock_exists, mock_run):
    mock_run.return_value = MagicMock(stdout="%5\n")
    name, pane_id = create_session("repo/branch", "/tmp/wt")
    assert name == "repo-branch-2"
    assert pane_id == "%5"


@patch("womtrees.tmux._run")
def test_split_pane_vertical(mock_run):
    mock_run.return_value = MagicMock(stdout="%1\n")
    pane_id = split_pane("mysession", "vertical", "/tmp/wt")
    assert pane_id == "%1"
    mock_run.assert_called_once_with(
        [
            "tmux",
            "split-window",
            "-h",
            "-t",
            "mysession",
            "-c",
            "/tmp/wt",
            "-P",
            "-F",
            "#{pane_id}",
        ]
    )


@patch("womtrees.tmux._run")
def test_split_pane_horizontal(mock_run):
    mock_run.return_value = MagicMock(stdout="%2\n")
    pane_id = split_pane("mysession", "horizontal", "/tmp/wt")
    assert pane_id == "%2"
    mock_run.assert_called_once_with(
        [
            "tmux",
            "split-window",
            "-v",
            "-t",
            "mysession",
            "-c",
            "/tmp/wt",
            "-P",
            "-F",
            "#{pane_id}",
        ]
    )


@patch("womtrees.tmux._run")
def test_swap_pane(mock_run):
    swap_pane("mysession")
    mock_run.assert_called_once_with(["tmux", "swap-pane", "-t", "mysession", "-U"])


@patch("womtrees.tmux._run")
def test_send_keys(mock_run):
    send_keys("mysession:0.1", "echo hello")
    mock_run.assert_called_once_with(
        ["tmux", "send-keys", "-t", "mysession:0.1", "echo hello", "Enter"]
    )


@patch("womtrees.tmux._run")
def test_kill_session(mock_run):
    kill_session("mysession")
    mock_run.assert_called_once_with(
        ["tmux", "kill-session", "-t", "mysession"], check=False
    )


@patch("womtrees.tmux._run")
def test_session_exists_true(mock_run):
    mock_run.return_value = MagicMock(returncode=0)
    assert session_exists("mysession") is True


@patch("womtrees.tmux._run")
def test_session_exists_false(mock_run):
    mock_run.return_value = MagicMock(returncode=1)
    assert session_exists("mysession") is False


@patch("womtrees.tmux._run")
def test_set_environment(mock_run):
    set_environment("mysession", "WOMTREE_WORK_ITEM_ID", "42")
    mock_run.assert_called_once_with(
        ["tmux", "set-environment", "-t", "mysession", "WOMTREE_WORK_ITEM_ID", "42"]
    )


@patch.dict("os.environ", {"TMUX": "/tmp/tmux-1000/default,12345,0"})
@patch("subprocess.run")
def test_attach_inside_tmux(mock_run):
    attach("mysession")
    mock_run.assert_called_once_with(["tmux", "switch-client", "-t", "mysession"])


@patch.dict("os.environ", {}, clear=True)
@patch("subprocess.run")
def test_attach_outside_tmux(mock_run):
    attach("mysession")
    mock_run.assert_called_once_with(["tmux", "attach-session", "-t", "mysession"])


@patch("womtrees.tmux._run")
def test_is_available_true(mock_run):
    assert is_available() is True


@patch("womtrees.tmux._run", side_effect=FileNotFoundError)
def test_is_available_false(mock_run):
    assert is_available() is False


@patch("womtrees.tmux._run")
@patch("womtrees.tmux.session_exists", return_value=False)
def test_rename_session(mock_exists, mock_run):
    result = rename_session("old-session", "repo/new-branch")
    assert result == "repo-new-branch"
    mock_run.assert_called_once_with(
        ["tmux", "rename-session", "-t", "old-session", "repo-new-branch"]
    )


@patch("womtrees.tmux._run")
@patch("womtrees.tmux.session_exists", side_effect=[True, False])
def test_rename_session_name_conflict(mock_exists, mock_run):
    """Rename appends -2 when target name already exists."""
    result = rename_session("old-session", "repo/branch")
    assert result == "repo-branch-2"
    mock_run.assert_called_once_with(
        ["tmux", "rename-session", "-t", "old-session", "repo-branch-2"]
    )
