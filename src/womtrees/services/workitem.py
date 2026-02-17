"""Work item lifecycle operations that coordinate across DB, git, and tmux."""

from __future__ import annotations

import sqlite3
import subprocess

from womtrees.config import Config, LayoutConfig
from womtrees.db import (
    create_claude_session,
    get_work_item,
    list_claude_sessions,
    list_pull_requests,
    update_claude_session,
    update_work_item,
)
from womtrees.db import (
    create_work_item as db_create_work_item,
)
from womtrees.db import (
    delete_work_item as db_delete_work_item,
)
from womtrees.models import WorkItem
from womtrees.worktree import (
    create_worktree,
    load_womtrees_config,
    remove_worktree,
    rename_branch,
    sanitize_branch_name,
)

_SENTINEL = object()  # distinguishes "not provided" from None for prompt editing


# -- Exceptions --


class WorkItemNotFoundError(Exception):
    """Raised when a work item ID does not exist."""

    def __init__(self, item_id: int) -> None:
        self.item_id = item_id
        super().__init__(f"WorkItem #{item_id} not found.")


class InvalidStateError(Exception):
    """Raised when a work item is in the wrong state for the requested transition."""

    def __init__(
        self,
        item_id: int,
        current: str,
        expected: str | tuple[str, ...],
    ) -> None:
        self.item_id = item_id
        self.current = current
        self.expected = expected if isinstance(expected, tuple) else (expected,)
        exp = " or ".join(f"'{s}'" for s in self.expected)
        super().__init__(
            f"Cannot transition #{item_id}: status is '{current}' (expected {exp}).",
        )


class DuplicateBranchError(Exception):
    """Raised when the target branch is already used by another active work item."""

    def __init__(self, branch: str, existing_item_id: int) -> None:
        self.branch = branch
        self.existing_item_id = existing_item_id
        super().__init__(
            f"Branch '{branch}' is already used by "
            f"active WorkItem #{existing_item_id}.",
        )


class OpenPullRequestError(Exception):
    """Raised when trying to rename a branch that has an open pull request."""

    def __init__(self, item_id: int, pr_number: int) -> None:
        self.item_id = item_id
        self.pr_number = pr_number
        super().__init__(
            f"Cannot rename branch: WorkItem #{item_id} has open PR #{pr_number}.",
        )


# -- Service functions --


def _get_item_or_raise(conn: sqlite3.Connection, item_id: int) -> WorkItem:
    """Fetch a work item or raise WorkItemNotFoundError."""
    item = get_work_item(conn, item_id)
    if item is None:
        raise WorkItemNotFoundError(item_id)
    return item


def create_work_item_todo(
    conn: sqlite3.Connection,
    repo_name: str,
    repo_path: str,
    branch: str,
    prompt: str | None = None,
    name: str | None = None,
) -> WorkItem:
    """Create a TODO work item (queued for later).

    Raises ValueError if the branch already has an active work item.
    """
    return db_create_work_item(
        conn,
        repo_name,
        repo_path,
        branch,
        prompt,
        status="todo",
        name=name,
    )


def resolve_layout(repo_path: str, config: Config) -> LayoutConfig:
    """Resolve layout: .womtrees.toml → config default → 'standard'.

    Raises ValueError if the resolved layout name is not found in config.
    """
    project_config = load_womtrees_config(repo_path)
    layout_name = (project_config or {}).get("layout", config.default_layout)
    if layout_name not in config.layouts:
        raise ValueError(f"Layout '{layout_name}' not found in config.")
    return config.layouts[layout_name]


def _build_claude_cmd(config: Config, item: WorkItem) -> str:
    """Build the claude CLI command string for a work item."""
    claude_cmd = "claude"
    if config.claude_args:
        claude_cmd += f" {config.claude_args}"
    if item.prompt:
        escaped_prompt = item.prompt.replace("'", "'\\''")
        claude_cmd += f" '{escaped_prompt}'"
    return claude_cmd


def start_work_item(conn: sqlite3.Connection, item_id: int, config: Config) -> WorkItem:
    """Start a TODO work item: create worktree + tmux session + Claude.

    Returns the updated WorkItem.
    Raises WorkItemNotFoundError if the item doesn't exist.
    Raises InvalidStateError if the item isn't in 'todo' state.
    """
    from womtrees import tmux

    item = _get_item_or_raise(conn, item_id)
    if item.status != "todo":
        raise InvalidStateError(item_id, item.status, "todo")

    if not tmux.is_available():
        raise RuntimeError("tmux is required. Install it with: brew install tmux")

    # Resolve layout
    layout = resolve_layout(item.repo_path, config)

    # Create worktree
    wt_path = create_worktree(item.repo_path, item.branch, config.base_dir)

    # Persist worktree_path immediately so delete can clean up on failure
    update_work_item(conn, item_id, worktree_path=str(wt_path))

    try:
        # Create tmux session (first window + first pane come for free)
        session_name = f"{item.repo_name}/{sanitize_branch_name(item.branch)}"
        session_env = {
            "WOMTREE_WORK_ITEM_ID": str(item_id),
            "WOMTREE_NAME": item.name or "",
            "WOMTREE_BRANCH": item.branch,
        }
        session_name, first_pane_id = tmux.create_session(
            session_name, str(wt_path), env=session_env
        )

        claude_pane_id: str | None = None

        for win_idx, window in enumerate(layout.windows):
            if win_idx == 0:
                # First window already exists; rename it
                # Target via pane ID — respects user's base-index setting
                tmux.rename_window(first_pane_id, window.name)
                current_pane_id = first_pane_id
            else:
                current_pane_id = tmux.new_window(
                    session_name, window.name, str(wt_path)
                )

            # Create additional panes (first pane already exists)
            pane_ids = [current_pane_id]
            for _ in window.panes[1:]:
                pane_id = tmux.split_pane(session_name, "vertical", str(wt_path))
                pane_ids.append(pane_id)

            # Apply layout after all panes in window are created
            window_target = f"{session_name}:{window.name}"
            tmux.select_layout(window_target, window.layout)

            # Send commands to each pane
            for pane_cfg, pane_id in zip(window.panes, pane_ids):
                if pane_cfg.claude:
                    claude_pane_id = pane_id
                    tmux.send_keys(pane_id, _build_claude_cmd(config, item))
                elif pane_cfg.command:
                    tmux.send_keys(pane_id, pane_cfg.command)

        assert claude_pane_id is not None  # guaranteed by layout validation

        # Select the first window so it's active on attach
        if len(layout.windows) > 1:
            tmux.select_window(first_pane_id)

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

        updated = update_work_item(
            conn,
            item_id,
            status="working",
            worktree_path=str(wt_path),
            tmux_session=session_name,
        )
        return updated  # type: ignore[return-value]
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


def review_work_item(conn: sqlite3.Connection, item_id: int) -> WorkItem:
    """Move a work item to review.

    Raises WorkItemNotFoundError, InvalidStateError.
    """
    item = _get_item_or_raise(conn, item_id)
    if item.status not in ("working", "input"):
        raise InvalidStateError(item_id, item.status, ("working", "input"))
    updated = update_work_item(conn, item_id, status="review")
    return updated  # type: ignore[return-value]


def done_work_item(conn: sqlite3.Connection, item_id: int) -> WorkItem:
    """Mark a work item as done.

    Raises WorkItemNotFoundError, InvalidStateError.
    """
    item = _get_item_or_raise(conn, item_id)
    if item.status not in ("working", "input", "review"):
        raise InvalidStateError(item_id, item.status, ("working", "input", "review"))
    updated = update_work_item(conn, item_id, status="done")
    return updated  # type: ignore[return-value]


def delete_work_item(
    conn: sqlite3.Connection,
    item_id: int,
    *,
    force: bool = False,
) -> str | None:
    """Delete a work item and clean up its worktree/tmux session.

    Returns a warning string if teardown scripts failed, None otherwise.
    Raises WorkItemNotFoundError if the item doesn't exist.
    Raises InvalidStateError if the item is 'working' and force=False.
    """
    from womtrees import tmux

    item = _get_item_or_raise(conn, item_id)

    if item.status == "working" and not force:
        raise InvalidStateError(
            item_id,
            item.status,
            ("todo", "input", "review", "done"),
        )

    # Kill tmux session if it exists
    if item.tmux_session and tmux.session_exists(item.tmux_session):
        tmux.kill_session(item.tmux_session)

    warning: str | None = None
    if item.worktree_path:
        try:
            warning = remove_worktree(item.worktree_path, branch=item.branch)
        except subprocess.CalledProcessError:
            pass  # Best effort

    db_delete_work_item(conn, item_id)
    return warning


def merge_work_item(
    conn: sqlite3.Connection,
    item_id: int,
) -> tuple[WorkItem, str | None]:
    """Merge a review item's branch and mark as done.

    Performs: merge branch, kill tmux, remove worktree, delete branch, mark done.
    Returns (updated WorkItem, teardown warning or None).
    Raises WorkItemNotFoundError, InvalidStateError.
    Re-raises RebaseRequiredError, subprocess.CalledProcessError from worktree.
    """
    from womtrees import tmux
    from womtrees.worktree import merge_branch

    item = _get_item_or_raise(conn, item_id)
    if item.status != "review":
        raise InvalidStateError(item_id, item.status, "review")

    # This may raise RebaseRequiredError or CalledProcessError
    merge_branch(item.repo_path, item.branch)

    # Clean up tmux session
    if item.tmux_session and tmux.session_exists(item.tmux_session):
        tmux.kill_session(item.tmux_session)

    # Clean up worktree
    warning: str | None = None
    if item.worktree_path:
        try:
            warning = remove_worktree(item.worktree_path, branch=item.branch)
        except subprocess.CalledProcessError:
            pass

    # Delete the branch after merge
    try:
        subprocess.run(
            ["git", "-C", item.repo_path, "branch", "-d", item.branch],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError:
        pass

    updated = update_work_item(conn, item_id, status="done")
    return updated, warning  # type: ignore[return-value]


def edit_work_item(
    conn: sqlite3.Connection,
    item: WorkItem,
    *,
    name: str | None = None,
    branch: str | None = None,
    prompt: str | None | object = _SENTINEL,
) -> bool:
    """Edit a work item's name, branch, and/or prompt.

    Handles git branch rename, tmux session rename, and claude session updates.
    Prompt editing is only allowed for items in 'todo' status.

    Returns True if any updates were applied, False otherwise.
    Raises DuplicateBranchError if the branch is already in use.
    Raises OpenPullRequestError if the item has an open PR.
    Raises InvalidStateError if prompt edit is attempted on a non-todo item.
    Raises subprocess.CalledProcessError if git or tmux operations fail.
    """
    updates: dict[str, str | None] = {}

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
            "SELECT id FROM work_items"
            " WHERE repo_name = ? AND branch = ?"
            " AND status != 'done' AND id != ?",
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
                    item.tmux_session,
                    new_session_name,
                )
                tmux.set_environment(new_session_name, "WOMTREE_BRANCH", branch)
            updates["tmux_session"] = new_session_name

            # Update claude_sessions so hook lookups still work
            for cs in list_claude_sessions(conn, work_item_id=item.id):
                update_claude_session(
                    conn,
                    cs.id,
                    tmux_session=new_session_name,
                    branch=branch,
                )

        updates["branch"] = branch

    if name is not None and name != item.name:
        # Update tmux environment if session exists
        if item.tmux_session:
            from womtrees import tmux

            session = updates.get("tmux_session", item.tmux_session)
            if session and tmux.session_exists(session):
                tmux.set_environment(session, "WOMTREE_NAME", name)
        updates["name"] = name

    if prompt is not _SENTINEL and prompt != item.prompt:
        if item.status != "todo":
            raise InvalidStateError(item.id, item.status, "edit prompt")
        updates["prompt"] = prompt  # type: ignore[assignment]  # guarded by sentinel check

    if updates:
        update_work_item(conn, item.id, **updates)
        return True

    return False
