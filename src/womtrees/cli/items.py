from __future__ import annotations

import click

from womtrees.config import get_config
from womtrees.db import (
    connection,
    get_work_item,
)
from womtrees.services.workitem import (
    DuplicateBranchError,
    InvalidStateError,
    OpenPullRequestError,
    WorkItemNotFoundError,
    create_work_item_todo,
    delete_work_item,
    done_work_item,
    edit_work_item,
    review_work_item,
    start_work_item,
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
    with connection() as conn:
        try:
            item = create_work_item_todo(
                conn, repo_name, resolved_path, branch, prompt, name=name
            )
        except ValueError as e:
            raise click.ClickException(str(e))
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
    with connection() as conn:
        try:
            item = create_work_item_todo(
                conn, repo_name, resolved_path, branch, prompt, name=name
            )
        except ValueError as e:
            raise click.ClickException(str(e))

        try:
            start_work_item(conn, item.id, config)
            click.echo(f"Started #{item.id} in worktree")
        except Exception as e:
            raise click.ClickException(str(e))


@click.command()
@click.argument("item_id", type=int)
def start(item_id: int) -> None:
    """Launch a TODO work item (create worktree and start working)."""
    config = get_config()
    with connection() as conn:
        try:
            item = start_work_item(conn, item_id, config)
            click.echo(f"Started #{item.id} in tmux session '{item.tmux_session}'")
        except (WorkItemNotFoundError, InvalidStateError) as e:
            raise click.ClickException(str(e))
        except Exception as e:
            raise click.ClickException(str(e))


@click.command()
@click.argument("item_id", type=int)
def review(item_id: int) -> None:
    """Move a work item to review."""
    with connection() as conn:
        try:
            review_work_item(conn, item_id)
            click.echo(f"#{item_id} moved to review")
        except (WorkItemNotFoundError, InvalidStateError) as e:
            raise click.ClickException(str(e))


@click.command()
@click.argument("item_id", type=int)
def done(item_id: int) -> None:
    """Move a work item to done."""
    with connection() as conn:
        try:
            done_work_item(conn, item_id)
            click.echo(f"#{item_id} marked as done")
        except (WorkItemNotFoundError, InvalidStateError) as e:
            raise click.ClickException(str(e))


@click.command()
@click.argument("item_id", type=int)
@click.option("--force", is_flag=True, help="Force delete an active work item.")
def delete(item_id: int, force: bool) -> None:
    """Delete a work item and its worktree."""
    with connection() as conn:
        # Still need to fetch item for confirmation prompt
        item = get_work_item(conn, item_id)
        if item is None:
            raise click.ClickException(f"WorkItem #{item_id} not found.")

        if item.status == "working" and not force:
            raise click.ClickException(
                f"WorkItem #{item_id} is still working. Use --force to delete."
            )

        if item.status in ("working", "done", "review"):
            if not click.confirm(
                f"Delete #{item_id} ({item.branch}, status={item.status})?"
            ):
                click.echo("Aborted.")
                return

        try:
            delete_work_item(conn, item_id, force=force)
        except (WorkItemNotFoundError, InvalidStateError) as e:
            raise click.ClickException(str(e))
    click.echo(f"Deleted #{item_id}")


@click.command()
@click.argument("item_id", type=int)
@click.option("-n", "--name", default=None, help="New name for the work item.")
@click.option("-b", "--branch", default=None, help="New branch name.")
@click.option("-p", "--prompt", default=None, help="New prompt (todo items only).")
def edit(
    item_id: int, name: str | None, branch: str | None, prompt: str | None
) -> None:
    """Edit a work item's name, branch, or prompt."""
    if name is None and branch is None and prompt is None:
        raise click.ClickException("Provide --name, --branch, and/or --prompt.")

    with connection() as conn:
        item = get_work_item(conn, item_id)
        if item is None:
            raise click.ClickException(f"WorkItem #{item_id} not found.")

        kwargs: dict[str, str | None] = {}
        if name is not None:
            kwargs["name"] = name
        if branch is not None:
            kwargs["branch"] = branch
        if prompt is not None:
            kwargs["prompt"] = prompt

        try:
            changed = edit_work_item(conn, item, **kwargs)
        except (DuplicateBranchError, InvalidStateError, OpenPullRequestError) as e:
            raise click.ClickException(str(e))

    if changed:
        click.echo(f"Updated #{item_id}")
    else:
        click.echo("No changes.")
