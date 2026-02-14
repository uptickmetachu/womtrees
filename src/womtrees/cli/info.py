from __future__ import annotations

import subprocess

import click

from womtrees.config import get_config
from womtrees.db import (
    get_claude_session,
    get_connection,
    get_work_item,
    list_claude_sessions,
    list_work_items,
    update_claude_session,
)


@click.command("list")
def list_cmd() -> None:
    """List work items with Claude session info."""
    conn = get_connection()
    items = list_work_items(conn)

    if not items:
        conn.close()
        click.echo("No work items found.")
        return

    # Gather Claude sessions per work item
    all_sessions = list_claude_sessions(conn)
    conn.close()

    sessions_by_item: dict[int | None, list] = {}
    for s in all_sessions:
        sessions_by_item.setdefault(s.work_item_id, []).append(s)

    # Header
    click.echo(
        f"{'ID':>4}  {'Status':<8}  {'Repo':<15}  {'Branch':<25}  {'Claude':<20}  {'Prompt'}"
    )
    click.echo("-" * 100)

    for item in items:
        sessions = sessions_by_item.get(item.id, [])
        if sessions:
            claude_info = ", ".join(f"C{s.id}:{s.state}" for s in sessions)
        else:
            claude_info = "-"

        prompt_display = (item.prompt or "")[:25]
        if item.prompt and len(item.prompt) > 25:
            prompt_display += "..."
        click.echo(
            f"{item.id:>4}  {item.status:<8}  {item.repo_name:<15}  {item.branch:<25}  {claude_info:<20}  {prompt_display}"
        )


@click.command()
@click.argument("item_id", type=int, required=False)
def status(item_id: int | None) -> None:
    """Show status of work items."""
    conn = get_connection()

    if item_id is not None:
        item = get_work_item(conn, item_id)
        if item is None:
            conn.close()
            raise click.ClickException(f"WorkItem #{item_id} not found.")

        sessions = list_claude_sessions(conn, work_item_id=item_id)
        conn.close()

        click.echo(f"WorkItem #{item.id}")
        click.echo(f"  Repo:     {item.repo_name}")
        click.echo(f"  Branch:   {item.branch}")
        click.echo(f"  Status:   {item.status}")
        click.echo(f"  Path:     {item.worktree_path or '(not created)'}")
        click.echo(f"  Tmux:     {item.tmux_session or '(none)'}")
        click.echo(f"  Prompt:   {item.prompt or '(none)'}")
        click.echo(f"  Created:  {item.created_at}")
        click.echo(f"  Updated:  {item.updated_at}")
        if sessions:
            click.echo("  Claude Sessions:")
            for s in sessions:
                click.echo(f"    C{s.id}: {s.state} (pane {s.tmux_pane})")
        return

    items = list_work_items(conn)

    conn.close()

    counts = {"todo": 0, "working": 0, "review": 0, "done": 0}
    for item in items:
        counts[item.status] = counts.get(item.status, 0) + 1

    total = sum(counts.values())
    click.echo(
        f"Total: {total}  |  todo: {counts['todo']}  working: {counts['working']}  review: {counts['review']}  done: {counts['done']}"
    )


@click.command("sessions")
def sessions_cmd() -> None:
    """List all Claude sessions."""
    from womtrees.claude import is_pid_alive

    conn = get_connection()
    sessions = list_claude_sessions(conn)

    # Clean up stale sessions
    for s in sessions:
        if s.pid and s.state != "done" and not is_pid_alive(s.pid):
            update_claude_session(conn, s.id, state="done")
            s = s.__class__(**{**s.__dict__, "state": "done"})

    conn.close()

    if not sessions:
        click.echo("No Claude sessions found.")
        return

    click.echo(
        f"{'Session':>8}  {'WorkItem':>8}  {'Repo':<15}  {'Branch':<25}  {'State':<10}  {'Pane'}"
    )
    click.echo("-" * 85)

    for s in sessions:
        wi_display = f"#{s.work_item_id}" if s.work_item_id else "(none)"
        click.echo(
            f"{'C' + str(s.id):>8}  {wi_display:>8}  {s.repo_name:<15}  {s.branch:<25}  {s.state:<10}  {s.tmux_pane}"
        )


def _maybe_resume_claude(conn, item_id: int) -> None:
    """If the Claude session for a work item is dead, relaunch it.

    Only resumes if ALL tracked Claude sessions are dead — avoids
    auto-launching extra sessions when you already have one running.
    """
    from womtrees import tmux
    from womtrees.claude import is_pid_alive

    sessions = list_claude_sessions(conn, work_item_id=item_id)
    if not sessions:
        return

    # Use the most recent session (including done — we resume those too)
    session = sessions[-1]

    # Check if Claude is still alive (if no PID recorded, assume alive)
    if not session.pid or is_pid_alive(session.pid):
        return

    # Only resume if every tracked session is dead — don't pile on when
    # another session is already running.
    all_sessions = list_claude_sessions(conn)
    for s in all_sessions:
        if s.pid and is_pid_alive(s.pid):
            return

    # Claude is dead — relaunch in the same pane
    config = get_config()
    claude_cmd = "claude"
    if config.claude_args:
        claude_cmd += f" {config.claude_args}"
    if session.claude_session_id:
        claude_cmd += f" --resume {session.claude_session_id}"
    else:
        claude_cmd += " --continue"

    try:
        tmux.send_keys(session.tmux_pane, claude_cmd)
    except subprocess.CalledProcessError:
        pass  # Pane may not exist


@click.command()
@click.argument("item_id", type=int)
@click.option(
    "--session",
    "session_id",
    type=int,
    default=None,
    help="Jump to a specific Claude session pane.",
)
def attach(item_id: int, session_id: int | None) -> None:
    """Attach to a work item's tmux session."""
    from womtrees import tmux

    conn = get_connection()
    item = get_work_item(conn, item_id)

    if item is None:
        conn.close()
        raise click.ClickException(f"WorkItem #{item_id} not found.")
    if not item.tmux_session:
        conn.close()
        raise click.ClickException(f"WorkItem #{item_id} has no tmux session.")
    if not tmux.session_exists(item.tmux_session):
        conn.close()
        raise click.ClickException(
            f"Tmux session '{item.tmux_session}' no longer exists."
        )

    # Resume dead Claude session before attaching
    _maybe_resume_claude(conn, item_id)

    # If a specific Claude session is requested, select its pane
    if session_id is not None:
        session = get_claude_session(conn, session_id)
        if session and session.tmux_pane:
            tmux.select_pane(item.tmux_session, session.tmux_pane)

    conn.close()
    tmux.attach(item.tmux_session)
