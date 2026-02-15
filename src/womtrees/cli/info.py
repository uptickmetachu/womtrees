from __future__ import annotations

import subprocess

import click

from womtrees.config import get_config
from womtrees.db import (
    connection,
    get_claude_session,
    get_work_item,
    list_claude_sessions,
    list_work_items,
    update_claude_session,
    update_work_item,
)


@click.command("list")
def list_cmd() -> None:
    """List work items with Claude session info."""
    with connection() as conn:
        items = list_work_items(conn)
        if not items:
            click.echo("No work items found.")
            return
        all_sessions = list_claude_sessions(conn)

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


def _format_tmux_status(conn) -> str:
    """Format a compact status string for tmux status-right."""
    sessions = list_claude_sessions(conn, state="waiting")
    if not sessions:
        return "wt: 0"

    branches = []
    for s in sessions:
        # Use short branch name (strip common prefixes)
        branch = s.branch
        branches.append(branch)

    # Build output, truncating to fit ~60 chars
    count = len(branches)
    max_len = 50  # leave room for "wt: N waiting []"
    shown: list[str] = []
    used = 0
    for b in branches:
        entry_len = len(b) + (2 if shown else 0)  # ", " separator
        if used + entry_len > max_len:
            remaining = count - len(shown)
            shown.append(f"+{remaining}")
            break
        shown.append(b)
        used += entry_len

    return f"wt: {count} waiting [{', '.join(shown)}]"


@click.command()
@click.argument("item_id", type=int, required=False)
@click.option(
    "--tmux", "tmux_mode", is_flag=True, help="Compact output for tmux status bar."
)
def status(item_id: int | None, tmux_mode: bool) -> None:
    """Show status of work items."""
    with connection() as conn:
        if tmux_mode:
            click.echo(_format_tmux_status(conn))
            return

        if item_id is not None:
            item = get_work_item(conn, item_id)
            if item is None:
                raise click.ClickException(f"WorkItem #{item_id} not found.")

            sessions = list_claude_sessions(conn, work_item_id=item_id)

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

    with connection() as conn:
        sessions = list_claude_sessions(conn)

        # Clean up stale sessions
        for s in sessions:
            if s.pid and s.state != "done" and not is_pid_alive(s.pid):
                update_claude_session(conn, s.id, state="done")
                s = s.__class__(**{**s.__dict__, "state": "done"})

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


def _restore_tmux_session(conn, item) -> str:
    """Recreate a missing tmux session for a work item.

    Creates a new tmux session in the worktree directory, sets the
    environment variable, and updates the DB. Returns the new session name.
    """
    from womtrees import tmux
    from womtrees.worktree import sanitize_branch_name

    working_dir = item.worktree_path or item.repo_path
    session_name = f"{item.repo_name}/{sanitize_branch_name(item.branch)}"
    session_name, _pane_id = tmux.create_session(session_name, working_dir)
    tmux.set_environment(session_name, "WOMTREE_WORK_ITEM_ID", str(item.id))
    update_work_item(conn, item.id, tmux_session=session_name)
    return session_name


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
@click.argument(
    "filter",
    type=click.Choice(["input", "review", "all"], case_sensitive=False),
    default="all",
)
def cycle(filter: str) -> None:
    """Cycle through tmux sessions managed by womtrees.

    Switches to the next work item's tmux session matching FILTER.

    \b
    FILTER values:
      input   — only items waiting for user input
      review  — only items in review
      all     — all active items (excludes done)
    """
    from womtrees import tmux

    with connection() as conn:
        # Gather matching work items with live tmux sessions
        if filter == "all":
            items = [
                i
                for i in list_work_items(conn)
                if i.status != "done"
                and i.tmux_session
                and tmux.session_exists(i.tmux_session)
            ]
        else:
            items = [
                i
                for i in list_work_items(conn, status=filter)
                if i.tmux_session and tmux.session_exists(i.tmux_session)
            ]

    if not items:
        raise click.ClickException(f"No active tmux sessions matching '{filter}'.")

    # Determine current tmux session (if inside tmux)
    import os

    current_session = None
    if os.environ.get("TMUX"):
        try:
            result = subprocess.run(
                ["tmux", "display-message", "-p", "#{session_name}"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                current_session = result.stdout.strip()
        except FileNotFoundError:
            pass

    # Find the next session to switch to
    session_names = [i.tmux_session for i in items]

    if current_session in session_names:
        idx = session_names.index(current_session)
        next_session = session_names[(idx + 1) % len(session_names)]
    else:
        next_session = session_names[0]

    # Type narrowing: next_session is guaranteed non-None from the filter above
    assert next_session is not None
    tmux.attach(next_session)


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

    with connection() as conn:
        item = get_work_item(conn, item_id)

        if item is None:
            raise click.ClickException(f"WorkItem #{item_id} not found.")
        if item.status == "todo":
            raise click.ClickException(
                f"WorkItem #{item_id} is still in TODO. Start it first with: wt start {item_id}"
            )
        if not item.tmux_session or not tmux.session_exists(item.tmux_session):
            if not item.worktree_path and not item.repo_path:
                raise click.ClickException(
                    f"WorkItem #{item_id} has no tmux session and no worktree path to restore into."
                )
            session_name = _restore_tmux_session(conn, item)
            click.echo(f"Restored tmux session '{session_name}' for #{item_id}")
            # Reload item with updated tmux_session
            item = get_work_item(conn, item_id)
            assert item is not None

        # Resume dead Claude session before attaching
        _maybe_resume_claude(conn, item_id)

        # At this point tmux_session is guaranteed to exist
        assert item.tmux_session is not None
        tmux_session = item.tmux_session

        # If a specific Claude session is requested, select its pane
        if session_id is not None:
            session = get_claude_session(conn, session_id)
            if session and session.tmux_pane:
                tmux.select_pane(tmux_session, session.tmux_pane)

    tmux.attach(tmux_session)
