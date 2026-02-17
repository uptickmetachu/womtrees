from __future__ import annotations

import sys

import click


@click.group()
def popup() -> None:
    """Open TUI dialogs in tmux popups."""


def _require_tmux() -> None:
    """Exit with an error if not inside a tmux session."""
    from womtrees.tmux import is_inside_tmux

    if not is_inside_tmux():
        click.echo("Error: popups require an active tmux session", err=True)
        sys.exit(1)


def _open_popup(dialog: str, repo: str | None = None) -> None:
    """Open a tmux popup running `wt board --dialog <dialog>`."""
    from womtrees.tmux import display_popup

    cmd = f"wt board --dialog {dialog}"
    if repo:
        cmd += f" --repo {repo}"

    title = "Create TODO" if dialog == "todo" else "Create & Launch"
    display_popup(cmd, width="50%", height="70%", title=title)


@popup.command()
@click.option("--repo", default=None, help="Repository path override.")
def todo(repo: str | None) -> None:
    """Open the Create TODO dialog in a tmux popup."""
    _require_tmux()
    _open_popup("todo", repo)


@popup.command()
@click.option("--repo", default=None, help="Repository path override.")
def create(repo: str | None) -> None:
    """Open the Create & Launch dialog in a tmux popup."""
    _require_tmux()
    _open_popup("create", repo)
