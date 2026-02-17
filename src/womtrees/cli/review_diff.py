"""CLI command for launching the diff review TUI."""

from __future__ import annotations

import click


@click.command("review-diff")
@click.argument("item_id", required=False, type=int)
@click.option("--uncommitted", is_flag=True, help="Compare HEAD vs working tree")
@click.option("--base", "base_ref", default=None, help="Custom base ref")
def review_diff_cmd(
    item_id: int | None,
    uncommitted: bool,
    base_ref: str | None,
) -> None:
    """Launch the diff review TUI.

    Optionally pass a work item ID. If omitted, auto-detects from worktree context.
    """
    import os

    from womtrees.diff import compute_diff

    tmux_pane: str | None = None

    if item_id is not None:
        from womtrees.db import get_connection, get_work_item

        conn = get_connection()
        item = get_work_item(conn, item_id)
        conn.close()
        if item is None:
            click.echo(f"Work item #{item_id} not found.", err=True)
            raise SystemExit(1)
        repo_path = item.worktree_path or item.repo_path
    else:
        # Use cwd so HEAD resolves to the worktree's branch, not the main repo's
        repo_path = os.getcwd()

    assert repo_path is not None

    diff_result = compute_diff(
        repo_path,
        base_ref=base_ref,
        uncommitted=uncommitted,
    )

    # Lazy import Textual (per CLAUDE.md rule)
    from womtrees.tui.diff_app import DiffApp

    app = DiffApp(
        diff_result=diff_result,
        repo_path=repo_path,
        base_ref=base_ref,
        tmux_pane=tmux_pane,
    )
    app.run()
