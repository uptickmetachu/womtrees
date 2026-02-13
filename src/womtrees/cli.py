from __future__ import annotations

import os
import subprocess

import click

from womtrees.config import ensure_config, get_config, CONFIG_FILE
from womtrees.db import (
    create_work_item,
    delete_work_item,
    get_connection,
    get_work_item,
    list_work_items,
    update_work_item,
)
from womtrees.worktree import create_worktree, get_current_repo, remove_worktree


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
    """Shared logic for starting a work item."""
    item = get_work_item(conn, item_id)
    if item is None:
        raise click.ClickException(f"WorkItem #{item_id} not found.")
    if item.status != "todo":
        raise click.ClickException(
            f"Cannot start #{item_id}, status is '{item.status}' (expected 'todo')."
        )

    wt_path = create_worktree(item.repo_path, item.branch, config.base_dir)
    update_work_item(conn, item_id, status="working", worktree_path=str(wt_path))
    click.echo(f"Started #{item_id}: {wt_path}")


@cli.command("list")
@click.option("--all", "show_all", is_flag=True, help="Show all repos.")
def list_cmd(show_all: bool) -> None:
    """List work items."""
    repo = get_current_repo()
    conn = get_connection()

    if show_all or repo is None:
        items = list_work_items(conn)
    else:
        items = list_work_items(conn, repo_name=repo[0])

    conn.close()

    if not items:
        click.echo("No work items found.")
        return

    # Header
    click.echo(f"{'ID':>4}  {'Status':<8}  {'Repo':<20}  {'Branch':<30}  {'Prompt'}")
    click.echo("-" * 90)

    for item in items:
        prompt_display = (item.prompt or "")[:35]
        if item.prompt and len(item.prompt) > 35:
            prompt_display += "..."
        click.echo(
            f"{item.id:>4}  {item.status:<8}  {item.repo_name:<20}  {item.branch:<30}  {prompt_display}"
        )


@cli.command()
@click.argument("item_id", type=int, required=False)
@click.option("--all", "show_all", is_flag=True, help="Show all repos.")
def status(item_id: int | None, show_all: bool) -> None:
    """Show status of work items."""
    conn = get_connection()

    if item_id is not None:
        item = get_work_item(conn, item_id)
        conn.close()
        if item is None:
            raise click.ClickException(f"WorkItem #{item_id} not found.")

        click.echo(f"WorkItem #{item.id}")
        click.echo(f"  Repo:     {item.repo_name}")
        click.echo(f"  Branch:   {item.branch}")
        click.echo(f"  Status:   {item.status}")
        click.echo(f"  Path:     {item.worktree_path or '(not created)'}")
        click.echo(f"  Prompt:   {item.prompt or '(none)'}")
        click.echo(f"  Created:  {item.created_at}")
        click.echo(f"  Updated:  {item.updated_at}")
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
@click.option("--edit", is_flag=True, help="Open config in $EDITOR.")
def config(edit: bool) -> None:
    """View or edit configuration."""
    config_path = ensure_config()

    if edit:
        editor = os.environ.get("EDITOR", "vi")
        subprocess.run([editor, str(config_path)])
    else:
        click.echo(config_path.read_text())
