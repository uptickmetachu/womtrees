from __future__ import annotations

import sys

import click

# Restore the default excepthook so Rich (installed by Textual) doesn't
# hijack tracebacks with fancy formatting that breaks CI and log parsing.
sys.excepthook = sys.__excepthook__

from womtrees.cli.admin import board, config, sqlite_cmd  # noqa: E402
from womtrees.cli.hooks import hook  # noqa: E402
from womtrees.cli.info import (  # noqa: E402
    _maybe_resume_claude,
    _restore_tmux_session,
    attach,
    cd_cmd,
    cycle,
    list_cmd,
    sessions_cmd,
    status,
)
from womtrees.cli.items import (  # noqa: E402
    create,
    delete,
    done,
    edit,
    review,
    start,
    todo,
)
from womtrees.cli.popups import popup  # noqa: E402
from womtrees.cli.review_diff import review_diff_cmd  # noqa: E402


@click.group()
def cli() -> None:
    """Womtrees — git worktree manager with tmux and Claude Code integration."""


# Register item commands
cli.add_command(todo)
cli.add_command(create)
cli.add_command(start)
cli.add_command(review)
cli.add_command(done)
cli.add_command(delete)
cli.add_command(edit)

# Register info commands
cli.add_command(list_cmd)
cli.add_command(status)
cli.add_command(sessions_cmd)
cli.add_command(attach)
cli.add_command(cd_cmd)
cli.add_command(cycle)

# Register hook group
cli.add_command(hook)

# Register popup group
cli.add_command(popup)

# Register admin commands
cli.add_command(board)
cli.add_command(sqlite_cmd)
cli.add_command(config)

# Register review command
cli.add_command(review_diff_cmd)

# Re-export for backward compatibility (used by TUI)
__all__ = ["_maybe_resume_claude", "_restore_tmux_session", "cli"]
