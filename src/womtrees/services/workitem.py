"""Work item editing operations that coordinate across DB, git, and tmux."""

from __future__ import annotations

import sqlite3

from womtrees.db import (
    list_claude_sessions,
    list_pull_requests,
    update_claude_session,
    update_work_item,
)
from womtrees.models import WorkItem
from womtrees.worktree import rename_branch, sanitize_branch_name


class DuplicateBranchError(Exception):
    """Raised when the target branch is already used by another active work item."""

    def __init__(self, branch: str, existing_item_id: int) -> None:
        self.branch = branch
        self.existing_item_id = existing_item_id
        super().__init__(
            f"Branch '{branch}' is already used by active WorkItem #{existing_item_id}."
        )


class OpenPullRequestError(Exception):
    """Raised when trying to rename a branch that has an open pull request."""

    def __init__(self, item_id: int, pr_number: int) -> None:
        self.item_id = item_id
        self.pr_number = pr_number
        super().__init__(
            f"Cannot rename branch: WorkItem #{item_id} has open PR #{pr_number}."
        )


def edit_work_item(
    conn: sqlite3.Connection,
    item: WorkItem,
    *,
    name: str | None = None,
    branch: str | None = None,
) -> bool:
    """Edit a work item's name and/or branch.

    Handles git branch rename, tmux session rename, and claude session updates.

    Returns True if any updates were applied, False otherwise.
    Raises DuplicateBranchError if the branch is already in use.
    Raises OpenPullRequestError if the item has an open PR.
    Raises subprocess.CalledProcessError if git or tmux operations fail.
    """
    updates: dict[str, str] = {}

    if branch is not None and branch != item.branch:
        # Block branch rename when an open PR exists
        open_prs = [
            pr
            for pr in list_pull_requests(conn, work_item_id=item.id)
            if pr.status == "open"
        ]
        if open_prs:
            raise OpenPullRequestError(item.id, open_prs[0].number)

        # Check for duplicate active branches
        row = conn.execute(
            "SELECT id FROM work_items WHERE repo_name = ? AND branch = ? AND status != 'done' AND id != ?",
            (item.repo_name, branch, item.id),
        ).fetchone()
        if row:
            raise DuplicateBranchError(branch, row["id"])

        # Rename the git branch if worktree exists
        if item.worktree_path:
            rename_branch(item.worktree_path, item.branch, branch)

        # Rename tmux session if it exists
        if item.tmux_session:
            from womtrees import tmux

            raw_name = f"{item.repo_name}/{sanitize_branch_name(branch)}"
            new_session_name = tmux.sanitize_session_name(raw_name)
            if tmux.session_exists(item.tmux_session):
                new_session_name = tmux.rename_session(
                    item.tmux_session, new_session_name
                )
            updates["tmux_session"] = new_session_name

            # Update claude_sessions so hook lookups still work
            for cs in list_claude_sessions(conn, work_item_id=item.id):
                update_claude_session(
                    conn, cs.id, tmux_session=new_session_name, branch=branch
                )

        updates["branch"] = branch

    if name is not None and name != item.name:
        updates["name"] = name

    if updates:
        update_work_item(conn, item.id, **updates)
        return True

    return False
