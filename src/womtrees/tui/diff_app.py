"""Standalone Textual app for the diff viewer."""

from __future__ import annotations

from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer, Header, Static, Tree

from womtrees.diff import DiffResult, ReviewComment
from womtrees.tui.diff_view import DiffView


class DiffApp(App[None]):
    """Two-panel diff viewer: file tree + unified diff."""

    TITLE = "womtrees review-diff"

    CSS = """
    #diff-layout {
        height: 1fr;
    }

    #file-tree {
        width: 25;
        border-right: solid $accent;
    }

    #diff-view {
        width: 1fr;
    }

    #diff-status {
        dock: bottom;
        height: 1;
        padding: 0 1;
        background: $boost;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("question_mark", "help", "Help", show=True),
        Binding("tab", "toggle_focus", "Toggle focus", show=False),
        Binding("shift+j", "next_file", "Next file", show=False),
        Binding("shift+k", "prev_file", "Prev file", show=False),
        Binding(
            "ctrl+s", "submit_clipboard", "Submit (clipboard)", show=True, priority=True
        ),
        Binding("shift+s", "submit_claude", "Submit + Claude", show=True),
        Binding("m", "cycle_mode", "Cycle mode", show=True),
    ]

    def __init__(
        self,
        diff_result: DiffResult,
        repo_path: str,
        base_ref: str | None = None,
        tmux_pane: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._diff = diff_result
        self._repo_path = repo_path
        self._base_ref = base_ref
        self._tmux_pane = tmux_pane
        self._comments: list[ReviewComment] = []
        self._current_file_idx: int = 0
        self._uncommitted_mode: bool = diff_result.target_ref == "working tree"

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="diff-layout"):
            yield Tree("Files", id="file-tree")
            yield DiffView(id="diff-view")
        yield Static("", id="diff-status")
        yield Footer()

    def on_mount(self) -> None:
        tree = self.query_one("#file-tree", Tree)
        for i, df in enumerate(self._diff.files):
            tree.root.add_leaf(df.path, data=str(i))
        tree.root.expand()

        if self._diff.files:
            self._load_file(0)

        self._update_status()

    def on_tree_node_selected(self, event: Tree.NodeSelected[str]) -> None:
        if event.node.data is not None:
            idx = int(event.node.data)
            self._load_file(idx)

    def _load_file(self, idx: int) -> None:
        if 0 <= idx < len(self._diff.files):
            self._current_file_idx = idx
            diff_view = self.query_one("#diff-view", DiffView)
            diff_view.load_file(self._diff.files[idx])
            file_comments = [
                c for c in self._comments if c.file == self._diff.files[idx].path
            ]
            diff_view.set_comments(file_comments)
            self._update_status()

    def _update_status(self) -> None:
        if not self._diff.files:
            status_text = "No files changed"
        else:
            f = self._diff.files[self._current_file_idx]
            diff_view = self.query_one("#diff-view", DiffView)
            pos = diff_view.cursor + 1
            total = len(f.lines)
            status_text = (
                f"{len(self._diff.files)} files changed | "
                f"{len(self._comments)} comments | "
                f"{f.path}:{pos}/{total} | "
                f"{self._diff.base_ref}..{self._diff.target_ref}"
            )
        self.query_one("#diff-status", Static).update(status_text)

    # -- File navigation --

    def action_next_file(self) -> None:
        if self._current_file_idx < len(self._diff.files) - 1:
            self._load_file(self._current_file_idx + 1)

    def action_prev_file(self) -> None:
        if self._current_file_idx > 0:
            self._load_file(self._current_file_idx - 1)

    def action_toggle_focus(self) -> None:
        tree = self.query_one("#file-tree", Tree)
        diff_view = self.query_one("#diff-view", DiffView)
        if self.focused is tree or (self.focused and tree in self.focused.ancestors):
            diff_view.focus()
        else:
            tree.focus()

    # -- Comment handling --

    def on_diff_view_comment_requested(self, event: DiffView.CommentRequested) -> None:
        from womtrees.tui.comment_input import CommentInputDialog

        context = f"{event.file}:{event.start_line}"
        if event.start_line != event.end_line:
            context = f"{event.file}:{event.start_line}-{event.end_line}"

        self.push_screen(
            CommentInputDialog(context=context),
            lambda text: self._on_comment_submitted(
                text, event.file, event.start_line, event.end_line
            ),
        )

    def _on_comment_submitted(
        self,
        text: str | None,
        file: str,
        start: int,
        end: int,
    ) -> None:
        if text is None:
            return
        self._comments.append(
            ReviewComment(file=file, start_line=start, end_line=end, comment_text=text)
        )
        self._refresh_comments()

    def on_diff_view_undo_comment(self, event: DiffView.UndoComment) -> None:
        if self._comments:
            self._comments.pop()
            self._refresh_comments()
            self.notify("Removed last comment")

    def on_diff_view_delete_comment_at_cursor(
        self, event: DiffView.DeleteCommentAtCursor
    ) -> None:
        if not self._diff.files:
            return
        current_file = self._diff.files[self._current_file_idx].path
        diff_view = self.query_one("#diff-view", DiffView)
        cursor = diff_view.cursor

        for i, c in enumerate(self._comments):
            if c.file == current_file and c.start_line <= cursor <= c.end_line:
                self._comments.pop(i)
                self._refresh_comments()
                self.notify("Deleted comment")
                return

    def on_diff_view_navigate_comment(self, event: DiffView.NavigateComment) -> None:
        if not self._diff.files or not self._comments:
            return
        current_file = self._diff.files[self._current_file_idx].path
        file_comments = [c for c in self._comments if c.file == current_file]
        if not file_comments:
            return

        diff_view = self.query_one("#diff-view", DiffView)
        cursor = diff_view.cursor

        if event.direction == 1:
            # Find next comment after cursor
            for c in file_comments:
                if c.start_line > cursor:
                    diff_view._cursor_pos = c.start_line
                    diff_view._render_diff()
                    diff_view._scroll_to_cursor()
                    self._update_status()
                    return
            # Wrap around
            diff_view._cursor_pos = file_comments[0].start_line
            diff_view._render_diff()
            diff_view._scroll_to_cursor()
        else:
            # Find prev comment before cursor
            for c in reversed(file_comments):
                if c.start_line < cursor:
                    diff_view._cursor_pos = c.start_line
                    diff_view._render_diff()
                    diff_view._scroll_to_cursor()
                    self._update_status()
                    return
            # Wrap around
            diff_view._cursor_pos = file_comments[-1].start_line
            diff_view._render_diff()
            diff_view._scroll_to_cursor()

        self._update_status()

    def _refresh_comments(self) -> None:
        """Re-render comments for the current file."""
        if not self._diff.files:
            return
        diff_view = self.query_one("#diff-view", DiffView)
        current_file = self._diff.files[self._current_file_idx].path
        file_comments = [c for c in self._comments if c.file == current_file]
        diff_view.set_comments(file_comments)
        self._update_status()
        self._update_tree_markers()

    def _update_tree_markers(self) -> None:
        """Update file tree to show comment markers."""
        tree = self.query_one("#file-tree", Tree)
        commented_files = {c.file for c in self._comments}
        for node in tree.root.children:
            if node.data is not None:
                idx = int(node.data)
                path = self._diff.files[idx].path
                marker = "\u25cf " if path in commented_files else ""
                node.set_label(f"{marker}{path}")

    # -- Mode cycling --

    def action_cycle_mode(self) -> None:
        """Toggle between uncommitted changes and branch diff."""
        from womtrees.diff import compute_diff

        self._uncommitted_mode = not self._uncommitted_mode

        self._diff = compute_diff(
            self._repo_path,
            base_ref=self._base_ref,
            uncommitted=self._uncommitted_mode,
        )

        self._current_file_idx = 0
        self._reload_tree()

        if self._diff.files:
            self._load_file(0)
        else:
            self.query_one("#diff-view", DiffView).clear()

        self._update_status()
        label = "uncommitted" if self._uncommitted_mode else "branch"
        self.notify(f"Mode: {label} ({len(self._diff.files)} files)")

    def _reload_tree(self) -> None:
        """Rebuild the file tree from current diff."""
        tree = self.query_one("#file-tree", Tree)
        tree.root.remove_children()
        for i, df in enumerate(self._diff.files):
            tree.root.add_leaf(df.path, data=str(i))
        tree.root.expand()
        self._update_tree_markers()

    # -- Submission --

    def action_submit_clipboard(self) -> None:
        if not self._comments:
            self.notify("No comments to submit", severity="warning")
            return

        from womtrees.review import copy_to_clipboard, format_comments

        md = format_comments(self._comments)
        copy_to_clipboard(md)
        self.notify(f"Copied {len(self._comments)} comments to clipboard")

    def action_submit_claude(self) -> None:
        if not self._comments:
            self.notify("No comments to submit", severity="warning")
            return

        from womtrees.review import copy_to_clipboard, format_comments, send_to_claude

        md = format_comments(self._comments)
        copy_to_clipboard(md)
        self.notify(f"Copied {len(self._comments)} comments to clipboard")

        if self._tmux_pane:
            send_to_claude(self._tmux_pane, md)
            self.notify("Sent to Claude")
            self.exit()
        else:
            self.notify("No active Claude session — clipboard only", severity="warning")

    def action_help(self) -> None:
        self.notify(
            "j/k: navigate | J/K: files | ]/[: hunks | m: cycle mode | "
            "v: select | c: comment | u: undo | x: delete | "
            "n/N: nav comments | ctrl+s: submit | S: submit+Claude | q: quit"
        )
