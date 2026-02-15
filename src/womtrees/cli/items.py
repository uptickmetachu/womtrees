from __future__ import annotations

import subprocess

import click

from womtrees.config import get_config
from womtrees.db import (
    create_claude_session,
    create_work_item,
    delete_work_item,
    get_connection,
    get_work_item,
    update_work_item,
)
from womtrees.services.workitem import (
    DuplicateBranchError,
    OpenPullRequestError,
    edit_work_item,
)
from womtrees.worktree import (
    create_worktree,
    remove_worktree,
    sanitize_branch_name,
)

from womtrees.cli.utils import (
    _generate_name,
    _read_prompt,
    _resolve_repo,
    _slugify,
)


@click.command()
@click.argument("prompt", required=False, default=None)
@click.option("-b", "--branch", default=None, help="Branch name for the worktree.")
@click.option(
    "-n", "--name", default=None, help="Human-readable name for the work item."
)
@click.option(
    "-r",
    "--repo",
    "repo_path",
    default=None,
    help="Target repo path (default: current git repo).",
)
def todo(
    prompt: str | None, branch: str | None, name: str | None, repo_path: str | None
) -> None:
    """Create a TODO work item (queued for later).

    PROMPT is the task description. Can also be piped via stdin.
    If --branch is omitted, a branch name is auto-generated from the prompt.
    """
    prompt = _read_prompt(prompt)
    if not prompt and not branch:
        raise click.ClickException(
            "Provide a prompt (positional arg or stdin) or --branch."
        )

    config = get_config()

    if name is None and prompt:
        name = _generate_name(prompt)
    if branch is None:
        slug = _slugify(name) if name else "task"
        branch = f"{config.branch_prefix}/{slug}"

    repo_name, resolved_path = _resolve_repo(repo_path)
    conn = get_connection()
    try:
        item = create_work_item(
            conn, repo_name, resolved_path, branch, prompt, status="todo", name=name
        )
    except ValueError as e:
        conn.close()
        raise click.ClickException(str(e))
    conn.close()
    click.echo(f"Created TODO #{item.id}: {branch}")


@click.command()
@click.argument("prompt", required=False, default=None)
@click.option("-b", "--branch", default=None, help="Branch name for the worktree.")
@click.option(
    "-n", "--name", default=None, help="Human-readable name for the work item."
)
@click.option(
    "-r",
    "--repo",
    "repo_path",
    default=None,
    help="Target repo path (default: current git repo).",
)
def create(
    prompt: str | None, branch: str | None, name: str | None, repo_path: str | None
) -> None:
    """Create a work item and immediately launch it.

    PROMPT is the task description. Can also be piped via stdin.
    If --branch is omitted, a branch name is auto-generated from the prompt.
    """
    prompt = _read_prompt(prompt)
    if not prompt and not branch:
        raise click.ClickException(
            "Provide a prompt (positional arg or stdin) or --branch."
        )

    config = get_config()

    if name is None and prompt:
        name = _generate_name(prompt)
    if branch is None:
        slug = _slugify(name) if name else "task"
        branch = f"{config.branch_prefix}/{slug}"

    repo_name, resolved_path = _resolve_repo(repo_path)
    conn = get_connection()

    try:
        item = create_work_item(
            conn, repo_name, resolved_path, branch, prompt, status="todo", name=name
        )
    except ValueError as e:
        conn.close()
        raise click.ClickException(str(e))
    _start_work_item(conn, item.id, config)
    conn.close()


@click.command()
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
        raise click.ClickException(
            "tmux is required. Install it with: brew install tmux"
        )

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
            conn,
            item_id,
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


@click.command()
@click.argument("item_id", type=int)
def review(item_id: int) -> None:
    """Move a work item to review."""
    conn = get_connection()
    item = get_work_item(conn, item_id)
    if item is None:
        conn.close()
        raise click.ClickException(f"WorkItem #{item_id} not found.")
    if item.status not in ("working", "input"):
        conn.close()
        raise click.ClickException(
            f"Cannot review #{item_id}, status is '{item.status}' (expected 'working' or 'input')."
        )

    update_work_item(conn, item_id, status="review")
    conn.close()
    click.echo(f"#{item_id} moved to review")


@click.command()
@click.argument("item_id", type=int)
def done(item_id: int) -> None:
    """Move a work item to done."""
    conn = get_connection()
    item = get_work_item(conn, item_id)
    if item is None:
        conn.close()
        raise click.ClickException(f"WorkItem #{item_id} not found.")
    if item.status not in ("working", "input", "review"):
        conn.close()
        raise click.ClickException(
            f"Cannot mark #{item_id} done, status is '{item.status}' (expected 'working', 'input', or 'review')."
        )

    update_work_item(conn, item_id, status="done")
    conn.close()
    click.echo(f"#{item_id} marked as done")


@click.command()
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
        if not click.confirm(
            f"Delete #{item_id} ({item.branch}, status={item.status})?"
        ):
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


@click.command()
@click.argument("item_id", type=int)
@click.option("-n", "--name", default=None, help="New name for the work item.")
@click.option("-b", "--branch", default=None, help="New branch name.")
def edit(item_id: int, name: str | None, branch: str | None) -> None:
    """Edit a work item's name or branch."""
    if name is None and branch is None:
        raise click.ClickException("Provide --name and/or --branch.")

    conn = get_connection()
    item = get_work_item(conn, item_id)
    if item is None:
        conn.close()
        raise click.ClickException(f"WorkItem #{item_id} not found.")

    try:
        changed = edit_work_item(conn, item, name=name, branch=branch)
    except (DuplicateBranchError, OpenPullRequestError) as e:
        conn.close()
        raise click.ClickException(str(e))

    conn.close()
    if changed:
        click.echo(f"Updated #{item_id}")
    else:
        click.echo("No changes.")
