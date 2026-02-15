from __future__ import annotations

import click

from womtrees.db import (
    connection,
    create_claude_session,
    find_claude_session,
    get_work_item,
    update_claude_session,
    update_work_item,
)


# -- Hook subcommands (called by Claude Code hooks) --
# These must be fast: minimal imports, direct DB writes.


@click.group()
def hook() -> None:
    """Internal hook commands (called by Claude Code)."""


@hook.command()
def install() -> None:
    """Install Claude Code hooks and tmux status bar integration."""
    from womtrees.claude import configure_tmux_status_bar, install_global_hooks

    install_global_hooks()
    click.echo("Installed womtrees hooks into Claude Code settings.")

    if configure_tmux_status_bar():
        click.echo("Configured tmux status bar (wt status --tmux).")
    else:
        click.echo("Tmux status bar already configured.")


@hook.command()
def heartbeat() -> None:
    """Signal that Claude is actively working (PostToolUse)."""
    _handle_hook(session_state="working", item_status="working")


@hook.command("input")
def hook_input() -> None:
    """Signal that Claude needs user input (Notification)."""
    _handle_hook(session_state="waiting", item_status="input")


@hook.command()
def stop() -> None:
    """Signal that Claude has finished (Stop)."""
    _handle_hook(session_state="done", item_status="review")


@hook.command()
@click.argument("session_id", type=int)
def mark_done(session_id: int) -> None:
    """Mark a Claude session as done."""
    with connection() as conn:
        update_claude_session(conn, session_id, state="done")


def _handle_hook(session_state: str, item_status: str) -> None:
    """Shared logic for hook commands.

    Updates the Claude session state and, if a linked work item exists,
    transitions it to the given item_status. Reads Claude Code's hook JSON
    from stdin to capture the session_id for --resume support.
    """
    import json
    import sys

    from womtrees.claude import detect_context

    ctx = detect_context()

    # Bail silently if we can't detect tmux context
    tmux_session = ctx["tmux_session"]
    tmux_pane = ctx["tmux_pane"]
    if not tmux_session or not tmux_pane:
        return

    # Extract typed values from context
    repo_name = str(ctx["repo_name"]) if ctx["repo_name"] is not None else "unknown"
    repo_path = str(ctx["repo_path"]) if ctx["repo_path"] is not None else ""
    branch = str(ctx["branch"]) if ctx["branch"] is not None else "unknown"
    pid = int(ctx["pid"]) if ctx["pid"] is not None else None
    wi_id = int(ctx["work_item_id"]) if ctx["work_item_id"] is not None else None

    # Read Claude Code's hook JSON from stdin to capture session_id
    claude_session_id = None
    if not sys.stdin.isatty():
        try:
            hook_input = json.loads(sys.stdin.read())
            claude_session_id = hook_input.get("session_id")
        except (json.JSONDecodeError, OSError):
            pass

    with connection() as conn:
        # Try to find existing session
        session = find_claude_session(conn, str(tmux_session), str(tmux_pane))

        if session:
            update_fields: dict[str, object] = {"state": session_state, "pid": pid}
            if claude_session_id:
                update_fields["claude_session_id"] = claude_session_id
            update_claude_session(conn, session.id, **update_fields)
            work_item_id = session.work_item_id
        else:
            # Create new session
            cs = create_claude_session(
                conn,
                repo_name=repo_name,
                repo_path=repo_path,
                branch=branch,
                tmux_session=str(tmux_session),
                tmux_pane=str(tmux_pane),
                pid=pid,
                work_item_id=wi_id,
                state=session_state,
                claude_session_id=claude_session_id,
            )
            work_item_id = cs.work_item_id

        # Drive work item status from hooks
        if work_item_id is not None:
            item = get_work_item(conn, work_item_id)
            if item and item.status not in ("todo", "done"):
                update_work_item(conn, work_item_id, status=item_status)
