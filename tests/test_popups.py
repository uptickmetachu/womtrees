from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner

from womtrees.cli import cli
from womtrees.tmux import display_popup, is_inside_tmux


# -- tmux.display_popup tests --


@patch("subprocess.run")
def test_display_popup_basic(mock_run) -> None:
    display_popup("wt board --dialog todo")
    mock_run.assert_called_once_with(
        [
            "tmux",
            "display-popup",
            "-E",
            "-w",
            "80%",
            "-h",
            "70%",
            "wt board --dialog todo",
        ],
    )


@patch("subprocess.run")
def test_display_popup_with_title(mock_run) -> None:
    display_popup("wt board --dialog create", title="Create & Launch")
    mock_run.assert_called_once_with(
        [
            "tmux",
            "display-popup",
            "-E",
            "-w",
            "80%",
            "-h",
            "70%",
            "-T",
            "Create & Launch",
            "wt board --dialog create",
        ],
    )


@patch("subprocess.run")
def test_display_popup_custom_size(mock_run) -> None:
    display_popup("wt board", width="50%", height="40%")
    mock_run.assert_called_once_with(
        [
            "tmux",
            "display-popup",
            "-E",
            "-w",
            "50%",
            "-h",
            "40%",
            "wt board",
        ],
    )


# -- tmux.is_inside_tmux tests --


@patch.dict("os.environ", {"TMUX": "/tmp/tmux-1000/default,12345,0"})
def test_is_inside_tmux_true() -> None:
    assert is_inside_tmux() is True


@patch.dict("os.environ", {}, clear=True)
def test_is_inside_tmux_false() -> None:
    assert is_inside_tmux() is False


# -- CLI popup command tests --


def test_popup_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["popup", "--help"])
    assert result.exit_code == 0
    assert "tmux popups" in result.output.lower()


@patch.dict("os.environ", {}, clear=True)
def test_popup_todo_outside_tmux() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["popup", "todo"])
    assert result.exit_code != 0
    assert "popups require an active tmux session" in result.output


@patch.dict("os.environ", {"TMUX": "/tmp/tmux-1000/default,12345,0"})
@patch("womtrees.tmux.display_popup")
def test_popup_todo_calls_display_popup(mock_popup) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["popup", "todo"])
    assert result.exit_code == 0
    mock_popup.assert_called_once_with(
        "wt board --dialog todo",
        width="50%",
        height="70%",
        title="Create TODO",
    )


@patch.dict("os.environ", {"TMUX": "/tmp/tmux-1000/default,12345,0"})
@patch("womtrees.tmux.display_popup")
def test_popup_create_calls_display_popup(mock_popup) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["popup", "create"])
    assert result.exit_code == 0
    mock_popup.assert_called_once_with(
        "wt board --dialog create",
        width="50%",
        height="70%",
        title="Create & Launch",
    )


@patch.dict("os.environ", {"TMUX": "/tmp/tmux-1000/default,12345,0"})
@patch("womtrees.tmux.display_popup")
def test_popup_todo_with_repo(mock_popup) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["popup", "todo", "--repo", "/tmp/myrepo"])
    assert result.exit_code == 0
    mock_popup.assert_called_once_with(
        "wt board --dialog todo --repo /tmp/myrepo",
        width="50%",
        height="70%",
        title="Create TODO",
    )


# -- board --dialog flag tests --


def test_board_dialog_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["board", "--help"])
    assert result.exit_code == 0
    assert "--dialog" in result.output
