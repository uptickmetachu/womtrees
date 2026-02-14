from __future__ import annotations

import click

from womtrees.cli.admin import board, config, sqlite_cmd
from womtrees.cli.hooks import hook
from womtrees.cli.info import (
    _maybe_resume_claude,
    attach,
    list_cmd,
    sessions_cmd,
    status,
)
from womtrees.cli.items import (
    _start_work_item,
    create,
    delete,
    done,
    review,
    start,
    todo,
)


@click.group()
def cli() -> None:
    """womtrees — git worktree manager with tmux and Claude Code integration."""


# Register item commands
cli.add_command(todo)
cli.add_command(create)
cli.add_command(start)
cli.add_command(review)
cli.add_command(done)
cli.add_command(delete)

# Register info commands
cli.add_command(list_cmd)
cli.add_command(status)
cli.add_command(sessions_cmd)
cli.add_command(attach)

# Register hook group
cli.add_command(hook)

# Register admin commands
cli.add_command(board)
cli.add_command(sqlite_cmd)
cli.add_command(config)

# Re-export for backward compatibility (used by TUI)
__all__ = ["cli", "_start_work_item", "_maybe_resume_claude"]
