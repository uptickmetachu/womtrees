from __future__ import annotations

import subprocess

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.events import DescendantFocus
from textual.widgets import Footer, Header, Static
from womtrees.config import get_config
from womtrees.db import (
    create_pull_request,
    get_connection,
    get_work_item,
    list_claude_sessions,
    list_pull_requests,
    list_repos,
    list_work_items,
)
from womtrees.tui.board import KanbanBoard
from womtrees.tui.card import UnmanagedCard, WorkItemCard
from womtrees.tui.column import KanbanColumn
from womtrees.tui.commands import WorkItemCommands
from womtrees.tui.dialogs import (
    AutoRebaseDialog,
    ClaudeStreamDialog,
    CreateDialog,
    DeleteDialog,
    EditDialog,
    HelpDialog,
    MergeDialog,
    RebaseDialog,
)
from womtrees.models import GitStats
from womtrees.worktree import get_current_repo, get_diff_stats, has_uncommitted_changes


class WomtreesApp(App):
    """Kanban board TUI for womtrees."""

    COMMANDS = {WorkItemCommands}
    TITLE = "womtrees"

    CSS = """
    Screen {
        layout: vertical;
    }

    #status-bar {
        dock: bottom;
        height: 3;
        padding: 0 1;
        background: $boost;
    }

    #status-keys {
        width: 100%;
    }

    #status-counts {
        width: 100%;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("question_mark", "help", "Help", show=True),
        Binding("h,left", "prev_column", "Prev col", show=False),
        Binding("l,right", "next_column", "Next col", show=False),
        Binding("j,down", "next_card", "Next card", show=False),
        Binding("k,up", "prev_card", "Prev card", show=False),
        Binding("enter", "jump", "Jump", show=True),
        Binding("s", "start_item", "Start", show=True),
        Binding("c", "create_item", "Create", show=True),
        Binding("t", "todo_item", "Todo", show=True),
        Binding("r", "review_item", "Review", show=True),
        Binding("m", "merge_item", "Merge", show=True),
        Binding("e", "edit_item", "Edit", show=True),
        Binding("d", "delete_item", "Delete", show=True),
        Binding("p", "create_pr", "PR", show=True),
        Binding("g", "toggle_grouping", "Group", show=True),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.group_by_repo = True
        self.active_column_idx = 0
        self.repo_context = get_current_repo()
        self.last_focused_card: WorkItemCard | UnmanagedCard | None = None

    def on_descendant_focus(self, event: DescendantFocus) -> None:
        """Track the last focused card for the command palette."""
        if isinstance(event.widget, (WorkItemCard, UnmanagedCard)):
            self.last_focused_card = event.widget

    def compose(self) -> ComposeResult:
        yield Header()
        yield KanbanBoard(id="board")
        with Horizontal(id="status-bar"):
            yield Static(
                "[s]tart [e]dit [r]eview [m]erge [p]r [d]elete [Enter]jump [g]roup [a]ll [?]help [q]uit",
                id="status-keys",
            )
            yield Static("", id="status-counts")
        yield Footer()

    def on_mount(self) -> None:
        self._db_path = get_config().base_dir / "womtrees.db"
        self._wal_path = self._db_path.parent / (self._db_path.name + "-wal")
        self._last_db_mtime: float = 0
        self._refresh_board()
        self.set_interval(0.5, self._check_refresh)
        self.set_interval(10, self._refresh_board)

    def _check_refresh(self) -> None:
        """Check DB/WAL file mtime; refresh only if changed."""
        mtime: float = 0
        for path in (self._db_path, self._wal_path):
            try:
                mtime = max(mtime, path.stat().st_mtime)
            except FileNotFoundError:
                continue
        if mtime and mtime != self._last_db_mtime:
            self._last_db_mtime = mtime
            self._refresh_board()

    def _refresh_board(self) -> None:
        """Reload data from SQLite and refresh the board."""
        # Save focused card identity before refresh
        focused_key = self._get_focused_card_key()

        try:
            conn = get_connection()
        except Exception:
            return

        try:
            items = list_work_items(conn)
            sessions = list_claude_sessions(conn)
            pull_requests = list_pull_requests(conn)
        finally:
            conn.close()

        # Compute git stats for review items
        git_stats: dict[int, GitStats] = {}
        for item in items:
            if item.status == "review" and item.worktree_path:
                try:
                    insertions, deletions = get_diff_stats(item.repo_path, item.branch)
                    uncommitted = has_uncommitted_changes(item.worktree_path)
                    git_stats[item.id] = GitStats(
                        uncommitted=uncommitted,
                        insertions=insertions,
                        deletions=deletions,
                    )
                except Exception:
                    pass

        board = self.query_one("#board", KanbanBoard)
        board.refresh_data(
            items, sessions, self.group_by_repo, pull_requests, git_stats=git_stats
        )

        self._update_status_bar(items, sessions)

        # Restore focus to the same card
        if focused_key is not None:
            self._restore_focus(focused_key)

    def _get_focused_card_key(self) -> tuple[str, int | str] | None:
        """Return a key identifying the currently focused card."""
        card = self._get_focused_card()
        if isinstance(card, WorkItemCard):
            return ("item", card.work_item.id)
        elif isinstance(card, UnmanagedCard):
            return ("unmanaged", card.branch)
        return None

    def _restore_focus(self, key: tuple[str, int | str]) -> None:
        """Find and focus the card matching the saved key."""
        board = self._get_board()
        for col in board.columns.values():
            for card in col.get_focusable_cards():
                if (
                    key[0] == "item"
                    and isinstance(card, WorkItemCard)
                    and card.work_item.id == key[1]
                ):
                    card.focus()
                    return
                if (
                    key[0] == "unmanaged"
                    and isinstance(card, UnmanagedCard)
                    and card.branch == key[1]
                ):
                    card.focus()
                    return

    def _update_status_bar(self, items, sessions) -> None:
        counts = {"todo": 0, "working": 0, "input": 0, "review": 0, "done": 0}
        for item in items:
            counts[item.status] = counts.get(item.status, 0) + 1

        unmanaged = sum(1 for s in sessions if s.work_item_id is None)
        repo_label = "all repos"

        status_text = (
            f"{repo_label} | "
            f"{counts['todo']} todo | "
            f"{counts['working']} working | "
            f"{counts['input']} input | "
            f"{counts['review']} review | "
            f"{counts['done']} done"
        )
        if unmanaged:
            status_text += f" | {unmanaged} unmanaged"

        self.query_one("#status-counts", Static).update(status_text)

    def _get_board(self) -> KanbanBoard:
        return self.query_one("#board", KanbanBoard)

    def _get_active_column(self) -> KanbanColumn:
        board = self._get_board()
        statuses = list(board.columns.keys())
        return board.columns[statuses[self.active_column_idx]]

    def _get_focused_card(self) -> WorkItemCard | UnmanagedCard | None:
        focused = self.focused
        if isinstance(focused, (WorkItemCard, UnmanagedCard)):
            return focused
        return None

    # -- Navigation actions --

    def action_prev_column(self) -> None:
        self._jump_to_next_column(direction=-1, focus="first")

    def action_next_column(self) -> None:
        self._jump_to_next_column(direction=1, focus="first")

    def action_next_card(self) -> None:
        col = self._get_active_column()
        cards = col.get_focusable_cards()
        focused = self._get_focused_card()
        if cards and focused in cards:
            idx = cards.index(focused)
            if idx < len(cards) - 1:
                cards[idx + 1].focus()
                return
        # At end of column or empty — jump to next column with cards
        self._jump_to_next_column(direction=1, focus="first")

    def action_prev_card(self) -> None:
        col = self._get_active_column()
        cards = col.get_focusable_cards()
        focused = self._get_focused_card()
        if cards and focused in cards:
            idx = cards.index(focused)
            if idx > 0:
                cards[idx - 1].focus()
                return
        # At start of column or empty — jump to prev column with cards
        self._jump_to_next_column(direction=-1, focus="last")

    def _jump_to_next_column(self, direction: int, focus: str) -> None:
        """Move to the next/prev column that has cards."""
        board = self._get_board()
        statuses = list(board.columns.keys())
        idx = self.active_column_idx + direction
        while 0 <= idx < len(statuses):
            cards = board.columns[statuses[idx]].get_focusable_cards()
            if cards:
                self.active_column_idx = idx
                (cards[0] if focus == "first" else cards[-1]).focus()
                return
            idx += direction

    def _focus_first_card_in_column(self) -> None:
        col = self._get_active_column()
        cards = col.get_focusable_cards()
        if cards:
            cards[0].focus()

    # -- Work item actions --

    def action_jump(self) -> None:
        """Jump to the tmux session for the focused card."""
        from womtrees import tmux
        from womtrees.cli import _maybe_resume_claude, _restore_tmux_session

        card = self._get_focused_card()
        if card is None:
            return

        # Block jumping into TODO items — they must be started first
        if isinstance(card, WorkItemCard) and card.work_item.status == "todo":
            self.notify("Start the item first before jumping in", severity="warning")
            return

        session_name = None
        work_item_id = None
        if isinstance(card, WorkItemCard):
            session_name = card.work_item.tmux_session
            work_item_id = card.work_item.id
        elif isinstance(card, UnmanagedCard) and card.sessions:
            session_name = card.sessions[0].tmux_session

        # Restore missing tmux session for managed work items
        if isinstance(card, WorkItemCard) and (
            not session_name or not tmux.session_exists(session_name)
        ):
            item = card.work_item
            if item.worktree_path or item.repo_path:
                conn = get_connection()
                try:
                    session_name = _restore_tmux_session(conn, item)
                    self.notify(f"Restored tmux session for #{item.id}")
                finally:
                    conn.close()
            else:
                self.notify("No worktree path to restore session", severity="error")
                return

        if session_name and tmux.session_exists(session_name):
            # Resume dead Claude session before attaching
            if work_item_id is not None:
                conn = get_connection()
                _maybe_resume_claude(conn, work_item_id)
                conn.close()

            with self.suspend():
                tmux.attach(session_name)

    def action_start_item(self) -> None:
        """Start a TODO work item."""
        from womtrees.services.workitem import (
            InvalidStateError,
            WorkItemNotFoundError,
            start_work_item,
        )

        card = self._get_focused_card()
        if not isinstance(card, WorkItemCard):
            return
        if card.work_item.status != "todo":
            self.notify("Can only start TODO items", severity="warning")
            return

        config = get_config()
        conn = get_connection()

        try:
            start_work_item(conn, card.work_item.id, config)
            self.notify(f"Started #{card.work_item.id}")
        except (WorkItemNotFoundError, InvalidStateError) as e:
            self.notify(str(e), severity="error")
        except Exception as e:
            self.notify(f"Failed to start: {e}", severity="error")
        finally:
            conn.close()

        self._refresh_board()

    def _get_repos_for_dialog(self) -> list[tuple[str, str]]:
        conn = get_connection()
        try:
            return list_repos(conn)
        finally:
            conn.close()

    def action_create_item(self) -> None:
        repos = self._get_repos_for_dialog()
        self.push_screen(
            CreateDialog(mode="create", repos=repos, default_repo=self.repo_context),
            self._on_create_dialog,
        )

    def action_todo_item(self) -> None:
        repos = self._get_repos_for_dialog()
        self.push_screen(
            CreateDialog(mode="todo", repos=repos, default_repo=self.repo_context),
            self._on_create_dialog,
        )

    def _on_create_dialog(self, result: dict | None) -> None:
        if result is None:
            return

        from womtrees.services.workitem import (
            create_work_item_todo,
            start_work_item,
        )

        repo_name = result["repo_name"]
        repo_path = result["repo_path"]
        conn = get_connection()
        try:
            item = create_work_item_todo(
                conn,
                repo_name,
                repo_path,
                result["branch"],
                result["prompt"],
                name=result.get("name"),
            )
        except ValueError as e:
            conn.close()
            self.notify(str(e), severity="error")
            return

        if result["mode"] == "create":
            config = get_config()
            try:
                start_work_item(conn, item.id, config)
                self.notify(f"Created and started #{item.id}")
            except Exception as e:
                self.notify(
                    f"Created TODO #{item.id}, but start failed: {e}",
                    severity="warning",
                )
        else:
            self.notify(f"Created TODO #{item.id}")

        conn.close()
        self._refresh_board()

    def action_edit_item(self) -> None:
        """Edit a work item's name and branch."""
        card = self._get_focused_card()
        if not isinstance(card, WorkItemCard):
            return

        item = card.work_item
        self.push_screen(
            EditDialog(
                item_name=item.name,
                item_branch=item.branch,
                item_prompt=item.prompt,
                show_prompt=item.status == "todo",
            ),
            lambda result: self._on_edit_dialog(result, item.id),
        )

    def _on_edit_dialog(self, result: dict | None, item_id: int) -> None:
        if result is None:
            return

        from womtrees.services.workitem import (
            DuplicateBranchError,
            InvalidStateError,
            OpenPullRequestError,
            edit_work_item,
        )

        conn = get_connection()
        item = get_work_item(conn, item_id)
        if item is None:
            conn.close()
            return

        prompt_kwargs = {}
        if "prompt" in result:
            prompt_kwargs["prompt"] = result["prompt"]

        try:
            changed = edit_work_item(
                conn,
                item,
                name=result["name"],
                branch=result["branch"],
                **prompt_kwargs,
            )
        except (DuplicateBranchError, InvalidStateError, OpenPullRequestError) as e:
            conn.close()
            self.notify(str(e), severity="error")
            return
        except Exception as e:
            conn.close()
            self.notify(f"Edit failed: {e}", severity="error")
            return

        conn.close()
        if changed:
            self.notify(f"Updated #{item_id}")
            self._refresh_board()

    def action_review_item(self) -> None:
        from womtrees.services.workitem import (
            InvalidStateError,
            WorkItemNotFoundError,
            review_work_item,
        )

        card = self._get_focused_card()
        if not isinstance(card, WorkItemCard):
            return
        if card.work_item.status not in ("working", "input"):
            self.notify("Can only review WORKING or INPUT items", severity="warning")
            return

        conn = get_connection()
        try:
            review_work_item(conn, card.work_item.id)
            self.notify(f"#{card.work_item.id} moved to review")
        except (WorkItemNotFoundError, InvalidStateError) as e:
            self.notify(str(e), severity="error")
        finally:
            conn.close()
        self._refresh_board()

    def action_merge_item(self) -> None:
        """Merge a review item's branch into the default branch."""
        card = self._get_focused_card()
        if not isinstance(card, WorkItemCard):
            return
        if card.work_item.status != "review":
            self.notify("Can only merge REVIEW items", severity="warning")
            return

        from womtrees.worktree import get_default_branch

        item = card.work_item
        target = get_default_branch(item.repo_path)
        msg = f"Merge #{item.id} ({item.branch}) into {target}?"

        self.push_screen(
            MergeDialog(msg),
            lambda confirmed: self._on_merge_confirmed(confirmed, item.id),
        )

    def _on_merge_confirmed(self, confirmed: bool, item_id: int) -> None:
        if not confirmed:
            return

        from womtrees.services.workitem import (
            InvalidStateError,
            WorkItemNotFoundError,
            merge_work_item,
        )
        from womtrees.worktree import RebaseRequiredError

        conn = get_connection()

        try:
            merge_work_item(conn, item_id)
            self.notify(f"#{item_id} merged and done")
        except RebaseRequiredError as e:
            msg = (
                f"Cannot merge #{item_id} ({e.branch}).\n"
                f"Branch is behind {e.default_branch} and needs a rebase."
            )
            self.push_screen(
                RebaseDialog(msg),
                lambda confirmed: self._on_rebase_confirmed(confirmed, item_id),
            )
        except (WorkItemNotFoundError, InvalidStateError) as e:
            self.notify(str(e), severity="error")
        except subprocess.CalledProcessError as e:
            self.notify(f"Merge failed: {e.stderr.strip()}", severity="error")
        finally:
            conn.close()

        self._refresh_board()

    def _on_rebase_confirmed(self, confirmed: bool, item_id: int) -> None:
        if not confirmed:
            return

        from womtrees.worktree import abort_rebase, rebase_branch

        conn = get_connection()
        item = get_work_item(conn, item_id)
        if item is None or not item.worktree_path:
            conn.close()
            return

        try:
            rebase_branch(item.worktree_path, item.repo_path)
        except subprocess.CalledProcessError:
            abort_rebase(item.worktree_path)
            conn.close()
            msg = (
                f"Rebase of #{item_id} ({item.branch}) failed due to conflicts.\n"
                f"Use claude -p to auto-rebase and resolve conflicts?"
            )
            self.push_screen(
                AutoRebaseDialog(msg),
                lambda confirmed: self._on_auto_rebase_confirmed(confirmed, item_id),
            )
            return

        conn.close()
        self.notify(f"#{item_id} rebased — press [m] to merge")

    def _on_auto_rebase_confirmed(self, confirmed: bool, item_id: int) -> None:
        if not confirmed:
            return

        from womtrees.worktree import get_default_branch

        conn = get_connection()
        item = get_work_item(conn, item_id)
        if item is None:
            conn.close()
            return

        if not item.worktree_path:
            conn.close()
            self.notify("No worktree path — cannot auto-rebase", severity="error")
            return

        default_branch = get_default_branch(item.repo_path)
        conn.close()

        prompt = (
            f"Rebase branch '{item.branch}' onto '{default_branch}'. "
            f"Run `git rebase {default_branch}` and resolve any merge conflicts "
            f"that arise. Continue the rebase until it completes successfully. "
            f"Do not commit anything beyond what the rebase requires."
        )

        self.push_screen(
            ClaudeStreamDialog(
                title=f"Auto-rebasing #{item_id}",
                prompt=prompt,
                cwd=item.worktree_path,
            ),
            lambda _result: self._on_auto_rebase_done(item_id),
        )

    def _on_auto_rebase_done(self, item_id: int) -> None:
        """Handle auto-rebase stream dialog dismissal."""
        self.notify(f"#{item_id} rebased — press [m] to merge")
        self._refresh_board()

    def action_delete_item(self) -> None:
        card = self._get_focused_card()
        if not isinstance(card, WorkItemCard):
            return

        item = card.work_item
        if item.status == "working":
            msg = f"Delete #{item.id} ({item.branch})?\nThis item is still WORKING — force delete?"
        else:
            msg = f"Delete #{item.id} ({item.branch}, status={item.status})?"

        self.push_screen(
            DeleteDialog(msg),
            lambda confirmed: self._on_delete_confirmed(confirmed, item.id),
        )

    def _on_delete_confirmed(self, confirmed: bool, item_id: int) -> None:
        if not confirmed:
            return

        from womtrees.services.workitem import (
            WorkItemNotFoundError,
            delete_work_item,
        )

        conn = get_connection()
        try:
            delete_work_item(conn, item_id, force=True)
            self.notify(f"Deleted #{item_id}")
        except WorkItemNotFoundError as e:
            self.notify(str(e), severity="error")
        except Exception as e:
            self.notify(f"Delete failed: {e}", severity="error")
        finally:
            conn.close()
        self._refresh_board()

    # -- PR actions --

    def action_create_pr(self) -> None:
        """Create a GitHub PR for the focused work item using Claude."""
        card = self._get_focused_card()
        if not isinstance(card, WorkItemCard):
            return
        if card.work_item.status not in ("working", "input", "review"):
            self.notify(
                "Can only create PR for working/input/review items", severity="warning"
            )
            return
        if not card.work_item.worktree_path:
            self.notify("No worktree path for this item", severity="warning")
            return

        item = card.work_item
        assert item.worktree_path is not None  # guarded above
        config = get_config()

        self.push_screen(
            ClaudeStreamDialog(
                title=f"Creating PR for #{item.id}",
                prompt=config.pr_prompt,
                cwd=item.worktree_path,
                on_result=lambda: self._detect_and_store_pr(
                    item.id, item.repo_path, item.branch
                ),
            ),
            self._on_claude_dialog_dismiss,
        )

    def _detect_and_store_pr(
        self, item_id: int, repo_path: str, branch: str
    ) -> dict | None:
        """Detect a newly-created PR and store it in the DB."""
        from womtrees.services.github import detect_pr

        pr_info = detect_pr(repo_path, branch)
        if pr_info is None:
            return None

        conn = get_connection()
        try:
            create_pull_request(
                conn,
                work_item_id=item_id,
                number=pr_info["number"],
                owner=pr_info["owner"],
                repo=pr_info["repo"],
                status=pr_info["state"],
                url=pr_info["url"],
            )
        finally:
            conn.close()

        return pr_info

    def _on_claude_dialog_dismiss(self, result: dict | None) -> None:
        """Handle ClaudeStreamDialog dismissal."""
        if result is not None:
            url = result.get("url", f"PR #{result.get('number', '?')}")
            self.notify(f"PR created: {url}")
        self._refresh_board()

    # -- Git commands (command palette) --

    def _cmd_git_push(self) -> None:
        """Push the focused item's branch to remote."""
        card = self._get_focused_card()
        if not isinstance(card, WorkItemCard):
            return
        item = card.work_item
        if not item.worktree_path:
            self.notify("No worktree path", severity="error")
            return
        try:
            subprocess.run(
                ["git", "push", "--set-upstream", "origin", item.branch],
                cwd=item.worktree_path,
                capture_output=True,
                text=True,
                check=True,
            )
            self.notify(f"Pushed {item.branch}")
        except subprocess.CalledProcessError as e:
            self.notify(f"Push failed: {e.stderr.strip()}", severity="error")

    def _cmd_git_pull(self) -> None:
        """Pull latest changes for the focused item's branch."""
        card = self._get_focused_card()
        if not isinstance(card, WorkItemCard):
            return
        item = card.work_item
        if not item.worktree_path:
            self.notify("No worktree path", severity="error")
            return
        try:
            subprocess.run(
                ["git", "pull"],
                cwd=item.worktree_path,
                capture_output=True,
                text=True,
                check=True,
            )
            self.notify(f"Pulled {item.branch}")
        except subprocess.CalledProcessError as e:
            self.notify(f"Pull failed: {e.stderr.strip()}", severity="error")
        self._refresh_board()

    def _cmd_rebase(self) -> None:
        """Rebase the focused item's branch onto default branch."""
        card = self._get_focused_card()
        if not isinstance(card, WorkItemCard):
            return
        item = card.work_item
        if item.status != "review":
            self.notify("Can only rebase REVIEW items", severity="warning")
            return

        from womtrees.worktree import get_default_branch

        target = get_default_branch(item.repo_path)
        msg = f"Rebase #{item.id} ({item.branch}) onto {target}?"
        self.push_screen(
            RebaseDialog(msg),
            lambda confirmed: self._on_rebase_confirmed(confirmed, item.id),
        )

    # -- Toggle actions --

    def action_toggle_grouping(self) -> None:
        self.group_by_repo = not self.group_by_repo
        label = "on" if self.group_by_repo else "off"
        self.notify(f"Repo grouping: {label}")
        self._refresh_board()

    def action_help(self) -> None:
        self.push_screen(HelpDialog())
