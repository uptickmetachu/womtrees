from __future__ import annotations

import os
import subprocess

import click

from womtrees.config import ensure_config, get_config, CONFIG_FILE
from womtrees.db import (
    create_claude_session,
    create_work_item,
    delete_work_item,
    find_claude_session,
    get_connection,
    get_work_item,
    list_claude_sessions,
    list_work_items,
    update_claude_session,
    update_work_item,
)
from womtrees.worktree import create_worktree, get_current_repo, remove_worktree, sanitize_branch_name


@click.group()
def cli() -> None:
    """womtrees — git worktree manager with tmux and Claude Code integration."""


@cli.command()
@click.option("-b", "--branch", required=True, help="Branch name for the worktree.")
@click.option("-p", "--prompt", default=None, help="Task description / Claude prompt.")
def todo(branch: str, prompt: str | None) -> None:
    """Create a TODO work item (queued for later)."""
    repo = get_current_repo()
    if repo is None:
        raise click.ClickException("Not inside a git repository.")

    repo_name, repo_path = repo
    conn = get_connection()
    item = create_work_item(conn, repo_name, repo_path, branch, prompt, status="todo")
    conn.close()
    click.echo(f"Created TODO #{item.id}: {branch}")


@cli.command()
@click.option("-b", "--branch", required=True, help="Branch name for the worktree.")
@click.option("-p", "--prompt", default=None, help="Task description / Claude prompt.")
def create(branch: str, prompt: str | None) -> None:
    """Create a work item and immediately launch it."""
    repo = get_current_repo()
    if repo is None:
        raise click.ClickException("Not inside a git repository.")

    repo_name, repo_path = repo
    config = get_config()
    conn = get_connection()

    item = create_work_item(conn, repo_name, repo_path, branch, prompt, status="todo")
    _start_work_item(conn, item.id, config)
    conn.close()


@cli.command()
@click.argument("item_id", type=int)
def start(item_id: int) -> None:
    """Launch a TODO work item (create worktree and start working)."""
    config = get_config()
    conn = get_connection()
    _start_work_item(conn, item_id, config)
    conn.close()


def _start_work_item(conn, item_id: int, config) -> None:
    """Shared logic for starting a work item: create worktree + tmux session + Claude."""
    from womtrees import tmux

    item = get_work_item(conn, item_id)
    if item is None:
        raise click.ClickException(f"WorkItem #{item_id} not found.")
    if item.status != "todo":
        raise click.ClickException(
            f"Cannot start #{item_id}, status is '{item.status}' (expected 'todo')."
        )

    if not tmux.is_available():
        raise click.ClickException("tmux is required. Install it with: brew install tmux")

    # Create worktree
    wt_path = create_worktree(item.repo_path, item.branch, config.base_dir)

    # Persist worktree_path immediately so delete can clean up on failure
    update_work_item(conn, item_id, worktree_path=str(wt_path))

    try:
        # Create tmux session
        session_name = f"{item.repo_name}/{sanitize_branch_name(item.branch)}"
        session_name, shell_pane_id = tmux.create_session(session_name, str(wt_path))

        # Set environment variable for Claude hook detection
        tmux.set_environment(session_name, "WOMTREE_WORK_ITEM_ID", str(item_id))

        # Split pane: creates a second pane for Claude
        claude_pane_id = tmux.split_pane(session_name, config.tmux_split, str(wt_path))

        # If Claude pane should be on the left/top, swap so it comes first visually
        if config.tmux_claude_pane in ("left", "top"):
            tmux.swap_pane(session_name)

        # Launch Claude using the pane ID (immune to base-index settings)
        claude_cmd = "claude"
        if config.claude_args:
            claude_cmd += f" {config.claude_args}"
        if item.prompt:
            escaped_prompt = item.prompt.replace("'", "'\\''")
            claude_cmd += f" '{escaped_prompt}'"
        tmux.send_keys(claude_pane_id, claude_cmd)

        # Create a ClaudeSession record
        create_claude_session(
            conn,
            repo_name=item.repo_name,
            repo_path=item.repo_path,
            branch=item.branch,
            tmux_session=session_name,
            tmux_pane=claude_pane_id,
            work_item_id=item_id,
            state="working",
            prompt=item.prompt,
        )

        update_work_item(
            conn, item_id,
            status="working",
            tmux_session=session_name,
        )
        click.echo(f"Started #{item_id} in tmux session '{session_name}'")
    except Exception:
        # Clean up on failure: remove worktree and kill tmux session if created
        try:
            remove_worktree(wt_path)
        except Exception:
            pass
        try:
            tmux.kill_session(session_name)
        except Exception:
            pass
        update_work_item(conn, item_id, worktree_path=None)
        raise


@cli.command("list")
@click.option("--all", "show_all", is_flag=True, help="Show all repos.")
def list_cmd(show_all: bool) -> None:
    """List work items with Claude session info."""
    repo = get_current_repo()
    conn = get_connection()

    if show_all or repo is None:
        items = list_work_items(conn)
    else:
        items = list_work_items(conn, repo_name=repo[0])

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
    click.echo(f"{'ID':>4}  {'Status':<8}  {'Repo':<15}  {'Branch':<25}  {'Claude':<20}  {'Prompt'}")
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


@cli.command()
@click.argument("item_id", type=int, required=False)
@click.option("--all", "show_all", is_flag=True, help="Show all repos.")
def status(item_id: int | None, show_all: bool) -> None:
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
            click.echo(f"  Claude Sessions:")
            for s in sessions:
                click.echo(f"    C{s.id}: {s.state} (pane {s.tmux_pane})")
        return

    repo = get_current_repo()
    if show_all or repo is None:
        items = list_work_items(conn)
    else:
        items = list_work_items(conn, repo_name=repo[0])

    conn.close()

    counts = {"todo": 0, "working": 0, "review": 0, "done": 0}
    for item in items:
        counts[item.status] = counts.get(item.status, 0) + 1

    total = sum(counts.values())
    click.echo(f"Total: {total}  |  todo: {counts['todo']}  working: {counts['working']}  review: {counts['review']}  done: {counts['done']}")


@cli.command()
@click.argument("item_id", type=int)
@click.option("--force", is_flag=True, help="Force delete an active work item.")
def delete(item_id: int, force: bool) -> None:
    """Delete a work item and its worktree."""
    from womtrees import tmux

    conn = get_connection()
    item = get_work_item(conn, item_id)
    if item is None:
        conn.close()
        raise click.ClickException(f"WorkItem #{item_id} not found.")

    if item.status == "working" and not force:
        conn.close()
        raise click.ClickException(
            f"WorkItem #{item_id} is still working. Use --force to delete."
        )

    if item.status in ("working", "done", "review"):
        if not click.confirm(f"Delete #{item_id} ({item.branch}, status={item.status})?"):
            conn.close()
            click.echo("Aborted.")
            return

    # Kill tmux session if it exists
    if item.tmux_session and tmux.session_exists(item.tmux_session):
        tmux.kill_session(item.tmux_session)

    if item.worktree_path:
        try:
            remove_worktree(item.worktree_path)
        except subprocess.CalledProcessError:
            click.echo(f"Warning: Failed to remove worktree at {item.worktree_path}")

    delete_work_item(conn, item_id)
    conn.close()
    click.echo(f"Deleted #{item_id}")


@cli.command()
@click.argument("item_id", type=int)
@click.option("--session", "session_id", type=int, default=None, help="Jump to a specific Claude session pane.")
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
        raise click.ClickException(f"Tmux session '{item.tmux_session}' no longer exists.")

    # If a specific Claude session is requested, select its pane
    if session_id is not None:
        from womtrees.db import get_claude_session
        session = get_claude_session(conn, session_id)
        if session and session.tmux_pane:
            tmux.select_pane(item.tmux_session, session.tmux_pane)

    conn.close()
    tmux.attach(item.tmux_session)


@cli.command()
@click.argument("item_id", type=int)
def review(item_id: int) -> None:
    """Move a work item to review."""
    conn = get_connection()
    item = get_work_item(conn, item_id)
    if item is None:
        conn.close()
        raise click.ClickException(f"WorkItem #{item_id} not found.")
    if item.status != "working":
        conn.close()
        raise click.ClickException(
            f"Cannot review #{item_id}, status is '{item.status}' (expected 'working')."
        )

    update_work_item(conn, item_id, status="review")
    conn.close()
    click.echo(f"#{item_id} moved to review")


@cli.command()
@click.argument("item_id", type=int)
def done(item_id: int) -> None:
    """Move a work item to done."""
    conn = get_connection()
    item = get_work_item(conn, item_id)
    if item is None:
        conn.close()
        raise click.ClickException(f"WorkItem #{item_id} not found.")
    if item.status != "review":
        conn.close()
        raise click.ClickException(
            f"Cannot mark #{item_id} done, status is '{item.status}' (expected 'review')."
        )

    update_work_item(conn, item_id, status="done")
    conn.close()
    click.echo(f"#{item_id} marked as done")


@cli.command()
@click.option("--all", "show_all", is_flag=True, help="Show all repos.")
def board(show_all: bool) -> None:
    """Open the kanban board TUI."""
    from womtrees.tui.app import WomtreesApp
    app = WomtreesApp(show_all=show_all)
    app.run()


@cli.command("sqlite")
def sqlite_cmd() -> None:
    """Open the womtrees database in sqlite3."""
    config = get_config()
    db_path = config.base_dir / "womtrees.db"
    subprocess.run(["sqlite3", str(db_path)])


@cli.command()
@click.option("--edit", is_flag=True, help="Open config in $EDITOR.")
def config(edit: bool) -> None:
    """View or edit configuration."""
    config_path = ensure_config()

    if edit:
        editor = os.environ.get("EDITOR", "vi")
        subprocess.run([editor, str(config_path)])
    else:
        click.echo(config_path.read_text())




@cli.command("sessions")
@click.option("--all", "show_all", is_flag=True, help="Show all repos.")
def sessions_cmd(show_all: bool) -> None:
    """List all Claude sessions."""
    from womtrees.claude import is_pid_alive

    repo = get_current_repo()
    conn = get_connection()

    if show_all or repo is None:
        sessions = list_claude_sessions(conn)
    else:
        sessions = list_claude_sessions(conn, repo_name=repo[0])

    # Clean up stale sessions
    for s in sessions:
        if s.pid and s.state != "done" and not is_pid_alive(s.pid):
            update_claude_session(conn, s.id, state="done")
            s = s.__class__(**{**s.__dict__, "state": "done"})

    conn.close()

    if not sessions:
        click.echo("No Claude sessions found.")
        return

    click.echo(f"{'Session':>8}  {'WorkItem':>8}  {'Repo':<15}  {'Branch':<25}  {'State':<10}  {'Pane'}")
    click.echo("-" * 85)

    for s in sessions:
        wi_display = f"#{s.work_item_id}" if s.work_item_id else "(none)"
        click.echo(
            f"{'C' + str(s.id):>8}  {wi_display:>8}  {s.repo_name:<15}  {s.branch:<25}  {s.state:<10}  {s.tmux_pane}"
        )


# -- Hook subcommands (called by Claude Code hooks) --
# These must be fast: minimal imports, direct DB writes.


@cli.group()
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
    """Signal that Claude is actively working."""
    _handle_hook("working")


@hook.command()
def stop() -> None:
    """Signal that Claude has stopped (waiting for input)."""
    _handle_hook("waiting")


@hook.command()
@click.argument("session_id", type=int)
def mark_done(session_id: int) -> None:
    """Mark a Claude session as done."""
    conn = get_connection()
    update_claude_session(conn, session_id, state="done")
    conn.close()


def _handle_hook(state: str) -> None:
    """Shared logic for heartbeat and stop hooks."""
    from womtrees.claude import detect_context

    ctx = detect_context()

    # Bail silently if we can't detect tmux context
    if not ctx["tmux_session"] or not ctx["tmux_pane"]:
        return

    conn = get_connection()

    # Try to find existing session
    session = find_claude_session(conn, ctx["tmux_session"], ctx["tmux_pane"])

    if session:
        update_claude_session(conn, session.id, state=state, pid=ctx["pid"])
    else:
        # Create new session
        create_claude_session(
            conn,
            repo_name=ctx["repo_name"] or "unknown",
            repo_path=ctx["repo_path"] or "",
            branch=ctx["branch"] or "unknown",
            tmux_session=ctx["tmux_session"],
            tmux_pane=ctx["tmux_pane"],
            pid=ctx["pid"],
            work_item_id=ctx["work_item_id"],
            state=state,
        )

    conn.close()
