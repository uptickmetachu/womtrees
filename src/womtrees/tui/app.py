from __future__ import annotations

import subprocess

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer, Header, Static

from womtrees.config import get_config
from womtrees.db import (
    create_work_item,
    delete_work_item,
    get_connection,
    get_work_item,
    list_claude_sessions,
    list_work_items,
    update_work_item,
)
from womtrees.tui.board import KanbanBoard
from womtrees.tui.card import UnmanagedCard, WorkItemCard
from womtrees.tui.column import KanbanColumn
from womtrees.tui.dialogs import CreateDialog, DeleteDialog, HelpDialog
from womtrees.worktree import get_current_repo


class WomtreesApp(App):
    """Kanban board TUI for womtrees."""

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
        Binding("shift+d", "done_item", "Done", show=True),
        Binding("d", "delete_item", "Delete", show=True),
        Binding("g", "toggle_grouping", "Group", show=True),
        Binding("a", "toggle_all", "All", show=True),
    ]

    def __init__(self, show_all: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        self.show_all = show_all
        self.group_by_repo = True
        self.active_column_idx = 0
        self.repo_context = get_current_repo()

    def compose(self) -> ComposeResult:
        yield Header()
        yield KanbanBoard(id="board")
        with Horizontal(id="status-bar"):
            yield Static(
                "[s]tart [d]elete [r]eview [D]one [Enter]jump [g]roup [a]ll [?]help [q]uit",
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
            if self.show_all or self.repo_context is None:
                items = list_work_items(conn)
                sessions = list_claude_sessions(conn)
            else:
                repo_name = self.repo_context[0]
                items = list_work_items(conn, repo_name=repo_name)
                sessions = list_claude_sessions(conn, repo_name=repo_name)
        finally:
            conn.close()

        board = self.query_one("#board", KanbanBoard)
        board.refresh_data(items, sessions, self.group_by_repo)

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
                if key[0] == "item" and isinstance(card, WorkItemCard) and card.work_item.id == key[1]:
                    card.focus()
                    return
                if key[0] == "unmanaged" and isinstance(card, UnmanagedCard) and card.branch == key[1]:
                    card.focus()
                    return

    def _update_status_bar(self, items, sessions) -> None:
        counts = {"todo": 0, "working": 0, "input": 0, "review": 0, "done": 0}
        for item in items:
            counts[item.status] = counts.get(item.status, 0) + 1

        unmanaged = sum(1 for s in sessions if s.work_item_id is None)
        repo_label = self.repo_context[0] if self.repo_context and not self.show_all else "all repos"

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
        if self.active_column_idx > 0:
            self.active_column_idx -= 1
            self._focus_first_card_in_column()

    def action_next_column(self) -> None:
        if self.active_column_idx < 4:
            self.active_column_idx += 1
            self._focus_first_card_in_column()

    def action_next_card(self) -> None:
        col = self._get_active_column()
        cards = col.get_focusable_cards()
        if not cards:
            return
        focused = self._get_focused_card()
        if focused in cards:
            idx = cards.index(focused)
            if idx < len(cards) - 1:
                cards[idx + 1].focus()
        else:
            cards[0].focus()

    def action_prev_card(self) -> None:
        col = self._get_active_column()
        cards = col.get_focusable_cards()
        if not cards:
            return
        focused = self._get_focused_card()
        if focused in cards:
            idx = cards.index(focused)
            if idx > 0:
                cards[idx - 1].focus()
        else:
            cards[-1].focus()

    def _focus_first_card_in_column(self) -> None:
        col = self._get_active_column()
        cards = col.get_focusable_cards()
        if cards:
            cards[0].focus()

    # -- Work item actions --

    def action_jump(self) -> None:
        """Jump to the tmux session for the focused card."""
        from womtrees import tmux
        from womtrees.cli import _maybe_resume_claude

        card = self._get_focused_card()
        if card is None:
            return

        session_name = None
        work_item_id = None
        if isinstance(card, WorkItemCard) and card.work_item.tmux_session:
            session_name = card.work_item.tmux_session
            work_item_id = card.work_item.id
        elif isinstance(card, UnmanagedCard) and card.sessions:
            session_name = card.sessions[0].tmux_session

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
        card = self._get_focused_card()
        if not isinstance(card, WorkItemCard):
            return
        if card.work_item.status != "todo":
            self.notify("Can only start TODO items", severity="warning")
            return

        from womtrees.worktree import create_worktree, sanitize_branch_name
        from womtrees import tmux

        config = get_config()
        conn = get_connection()
        item = card.work_item

        try:
            wt_path = create_worktree(item.repo_path, item.branch, config.base_dir)
            session_name = f"{item.repo_name}/{sanitize_branch_name(item.branch)}"
            session_name, shell_pane_id = tmux.create_session(session_name, str(wt_path))
            tmux.set_environment(session_name, "WOMTREE_WORK_ITEM_ID", str(item.id))
            claude_pane_id = tmux.split_pane(session_name, config.tmux_split, str(wt_path))
            if config.tmux_claude_pane in ("left", "top"):
                tmux.swap_pane(session_name)

            claude_cmd = "claude"
            if config.claude_args:
                claude_cmd += f" {config.claude_args}"
            if item.prompt:
                escaped = item.prompt.replace("'", "'\\''")
                claude_cmd += f" '{escaped}'"
            tmux.send_keys(claude_pane_id, claude_cmd)

            from womtrees.db import create_claude_session
            create_claude_session(
                conn, item.repo_name, item.repo_path, item.branch,
                tmux_session=session_name,
                tmux_pane=claude_pane_id,
                work_item_id=item.id,
                prompt=item.prompt,
            )

            update_work_item(conn, item.id, status="working", worktree_path=str(wt_path), tmux_session=session_name)
            self.notify(f"Started #{item.id}")
        except Exception as e:
            self.notify(f"Failed to start: {e}", severity="error")
        finally:
            conn.close()

        self._refresh_board()

    def action_create_item(self) -> None:
        self.push_screen(CreateDialog(mode="create"), self._on_create_dialog)

    def action_todo_item(self) -> None:
        self.push_screen(CreateDialog(mode="todo"), self._on_create_dialog)

    def _on_create_dialog(self, result: dict | None) -> None:
        if result is None:
            return

        if self.repo_context is None:
            self.notify("Not in a git repository", severity="error")
            return

        repo_name, repo_path = self.repo_context
        conn = get_connection()
        item = create_work_item(conn, repo_name, repo_path, result["branch"], result["prompt"])

        if result["mode"] == "create":
            config = get_config()
            try:
                from womtrees.cli import _start_work_item
                _start_work_item(conn, item.id, config)
                self.notify(f"Created and started #{item.id}")
            except Exception as e:
                self.notify(f"Created TODO #{item.id}, but start failed: {e}", severity="warning")
        else:
            self.notify(f"Created TODO #{item.id}")

        conn.close()
        self._refresh_board()

    def action_review_item(self) -> None:
        card = self._get_focused_card()
        if not isinstance(card, WorkItemCard):
            return
        if card.work_item.status not in ("working", "input"):
            self.notify("Can only review WORKING or INPUT items", severity="warning")
            return

        conn = get_connection()
        update_work_item(conn, card.work_item.id, status="review")
        conn.close()
        self.notify(f"#{card.work_item.id} moved to review")
        self._refresh_board()

    def action_done_item(self) -> None:
        card = self._get_focused_card()
        if not isinstance(card, WorkItemCard):
            return
        if card.work_item.status not in ("working", "input", "review"):
            self.notify("Can only mark active items as done", severity="warning")
            return

        conn = get_connection()
        update_work_item(conn, card.work_item.id, status="done")
        conn.close()
        self.notify(f"#{card.work_item.id} marked as done")
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

        self.push_screen(DeleteDialog(msg), lambda confirmed: self._on_delete_confirmed(confirmed, item.id))

    def _on_delete_confirmed(self, confirmed: bool, item_id: int) -> None:
        if not confirmed:
            return

        from womtrees import tmux
        from womtrees.worktree import remove_worktree

        conn = get_connection()
        item = get_work_item(conn, item_id)
        if item is None:
            conn.close()
            return

        if item.tmux_session and tmux.session_exists(item.tmux_session):
            tmux.kill_session(item.tmux_session)

        if item.worktree_path:
            try:
                remove_worktree(item.worktree_path)
            except subprocess.CalledProcessError:
                pass

        delete_work_item(conn, item_id)
        conn.close()
        self.notify(f"Deleted #{item_id}")
        self._refresh_board()

    # -- Toggle actions --

    def action_toggle_grouping(self) -> None:
        self.group_by_repo = not self.group_by_repo
        label = "on" if self.group_by_repo else "off"
        self.notify(f"Repo grouping: {label}")
        self._refresh_board()

    def action_toggle_all(self) -> None:
        self.show_all = not self.show_all
        label = "all repos" if self.show_all else "current repo"
        self.notify(f"Showing: {label}")
        self._refresh_board()

    def action_help(self) -> None:
        self.push_screen(HelpDialog())
