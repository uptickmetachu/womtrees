from __future__ import annotations

import click

from womtrees.db import (
    create_claude_session,
    find_claude_session,
    get_connection,
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
    """Install Claude Code hooks for automatic session tracking."""
    from womtrees.claude import install_global_hooks

    install_global_hooks()
    click.echo("Installed womtrees hooks into Claude Code settings.")


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
    conn = get_connection()
    update_claude_session(conn, session_id, state="done")
    conn.close()


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
    if not ctx["tmux_session"] or not ctx["tmux_pane"]:
        return

    # Read Claude Code's hook JSON from stdin to capture session_id
    claude_session_id = None
    if not sys.stdin.isatty():
        try:
            hook_input = json.loads(sys.stdin.read())
            claude_session_id = hook_input.get("session_id")
        except (json.JSONDecodeError, OSError):
            pass

    conn = get_connection()

    # Try to find existing session
    session = find_claude_session(conn, ctx["tmux_session"], ctx["tmux_pane"])

    if session:
        update_fields = {"state": session_state, "pid": ctx["pid"]}
        if claude_session_id:
            update_fields["claude_session_id"] = claude_session_id
        update_claude_session(conn, session.id, **update_fields)
        work_item_id = session.work_item_id
    else:
        # Create new session
        cs = create_claude_session(
            conn,
            repo_name=ctx["repo_name"] or "unknown",
            repo_path=ctx["repo_path"] or "",
            branch=ctx["branch"] or "unknown",
            tmux_session=ctx["tmux_session"],
            tmux_pane=ctx["tmux_pane"],
            pid=ctx["pid"],
            work_item_id=ctx["work_item_id"],
            state=session_state,
            claude_session_id=claude_session_id,
        )
        work_item_id = cs.work_item_id

    # Drive work item status from hooks
    if work_item_id is not None:
        item = get_work_item(conn, work_item_id)
        if item and item.status not in ("todo", "done"):
            update_work_item(conn, work_item_id, status=item_status)

    conn.close()
