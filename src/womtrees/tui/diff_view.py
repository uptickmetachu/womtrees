"""Custom diff viewer widget with vim navigation and visual selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rich.text import Text
from textual.binding import Binding
from textual.message import Message
from textual.widgets import RichLog

from womtrees.diff import DiffFile, DiffLine, ReviewComment

# Background colors for diff line types — subtle tints that don't wash out syntax
_BG_ADDED = "#0d2611"
_BG_REMOVED = "#2d0f0f"
_BG_HUNK = "#1c1c1c"
_BG_SELECTION = "#3a3a3a"
_BG_COMMENT = "#2a2210"
_BG_CURSOR = "#444444"

# Gutter styling
_GUTTER_STYLE = "dim"
_PREFIX_ADDED = "bold green"
_PREFIX_REMOVED = "bold red"
_HUNK_STYLE = "bold cyan"


class DiffView(RichLog):
    """Scrollable diff viewer with vim-style navigation."""

    BINDINGS = [
        Binding("j,down", "cursor_down", "Down", show=False),
        Binding("k,up", "cursor_up", "Up", show=False),
        Binding("g", "cursor_top", "Top", show=False),
        Binding("shift+g", "cursor_bottom", "Bottom", show=False),
        Binding("ctrl+d", "page_down", "Page down", show=False),
        Binding("ctrl+u", "page_up", "Page up", show=False),
        Binding("bracketright", "next_hunk", "Next hunk", show=False),
        Binding("bracketleft", "prev_hunk", "Prev hunk", show=False),
        Binding("v", "toggle_selection", "Select", show=False),
        Binding("escape", "cancel_selection", "Cancel", show=False),
        Binding("c", "comment", "Comment", show=False),
        Binding("n", "next_comment", "Next comment", show=False),
        Binding("shift+n", "prev_comment", "Prev comment", show=False),
        Binding("u", "undo_comment", "Undo comment", show=False),
        Binding("x", "delete_comment_at_cursor", "Delete comment", show=False),
    ]

    # -- Custom messages posted to parent app --

    @dataclass
    class CommentRequested(Message):
        """User pressed 'c' — wants to add a comment."""

        file: str
        start_line: int
        end_line: int

    @dataclass
    class NavigateComment(Message):
        """User pressed n/N to navigate comments."""

        direction: int  # 1 = next, -1 = prev

    class UndoComment(Message):
        """User pressed 'u' to undo last comment."""

    class DeleteCommentAtCursor(Message):
        """User pressed 'x' to delete comment at cursor."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._diff_file: DiffFile | None = None
        self._cursor_pos: int = 0
        self._selection_anchor: int | None = None  # None = no selection
        self._file_comments: list[ReviewComment] = []

    @property
    def cursor(self) -> int:
        return self._cursor_pos

    @property
    def selection_range(self) -> tuple[int, int] | None:
        """Return (start, end) if selection active, else None."""
        if self._selection_anchor is None:
            return None
        lo = min(self._selection_anchor, self._cursor_pos)
        hi = max(self._selection_anchor, self._cursor_pos)
        return (lo, hi)

    def load_file(self, diff_file: DiffFile) -> None:
        """Load a new file's diff into the view."""
        self._diff_file = diff_file
        self._cursor_pos = 0
        self._selection_anchor = None
        self._render_diff()

    def set_comments(self, comments: list[ReviewComment]) -> None:
        """Update comments and re-render."""
        self._file_comments = comments
        self._render_diff()

    def _render_diff(self) -> None:
        """Render all diff lines with cursor, selection, and comment highlighting."""
        self.clear()
        if not self._diff_file:
            return

        sel = self.selection_range
        commented_lines = self._get_commented_lines()

        for idx, line in enumerate(self._diff_file.lines):
            rendered = self._build_line(idx, line, sel, commented_lines)
            self.write(rendered)

        # Show inline comments
        self._write_inline_comments()

    def _get_commented_lines(self) -> set[int]:
        """Get set of line indices that have comments."""
        lines: set[int] = set()
        if not self._diff_file:
            return lines
        for comment in self._file_comments:
            if comment.file == self._diff_file.path:
                for i in range(comment.start_line, comment.end_line + 1):
                    lines.add(i)
        return lines

    def _build_line(
        self,
        idx: int,
        line: DiffLine,
        sel_range: tuple[int, int] | None,
        commented_lines: set[int],
    ) -> Text:
        """Build a Rich Text for a single diff line."""
        text = Text()

        # Comment marker
        if idx in commented_lines:
            text.append("\u25cf ", style="yellow")
        else:
            text.append("  ")

        # Hunk header — styled differently, no gutter
        if line.kind == "hunk_header":
            text.append(line.plain_text, style=_HUNK_STYLE)
            bg = _BG_HUNK
        else:
            # Gutter: line numbers
            old_no = f"{line.old_line_no:>4}" if line.old_line_no else "    "
            new_no = f"{line.new_line_no:>4}" if line.new_line_no else "    "
            text.append(f"{old_no} {new_no} ", style=_GUTTER_STYLE)

            # Prefix (+/-/space)
            if line.kind == "added":
                text.append("+", style=_PREFIX_ADDED)
            elif line.kind == "removed":
                text.append("-", style=_PREFIX_REMOVED)
            else:
                text.append(" ")

            # Syntax-highlighted code
            text.append_text(Text.from_ansi(line.highlighted))

            bg = None
            if line.kind == "added":
                bg = _BG_ADDED
            elif line.kind == "removed":
                bg = _BG_REMOVED

        # Selection overrides
        if sel_range and sel_range[0] <= idx <= sel_range[1]:
            bg = _BG_SELECTION

        # Comment background (unless selected)
        if idx in commented_lines and bg != _BG_SELECTION:
            bg = _BG_COMMENT

        # Cursor line highlight — pad to full width so background fills the row
        if idx == self._cursor_pos:
            bg = bg or _BG_CURSOR
            pad = max(0, self.size.width - text.cell_len)
            if pad:
                text.append(" " * pad)
            text.stylize(f"on {bg} bold underline")
        elif bg:
            pad = max(0, self.size.width - text.cell_len)
            if pad:
                text.append(" " * pad)
            text.stylize(f"on {bg}")

        return text

    def _write_inline_comments(self) -> None:
        """Render inline comment text below commented lines."""
        if not self._diff_file:
            return
        for comment in self._file_comments:
            if comment.file == self._diff_file.path:
                label = f"          \u2502 {comment.comment_text}"
                text = Text(label, style="dim italic")
                self.write(text)

    def _line_count(self) -> int:
        if not self._diff_file:
            return 0
        return len(self._diff_file.lines)

    def _move_cursor(self, delta: int) -> None:
        count = self._line_count()
        if count == 0:
            return
        self._cursor_pos = max(0, min(count - 1, self._cursor_pos + delta))
        self._render_diff()
        self._scroll_to_cursor()

    def _scroll_to_cursor(self) -> None:
        """Scroll so the cursor line is visible."""
        self.scroll_to(y=max(0, self._cursor_pos - 5), animate=False)

    # -- Navigation actions --

    def action_cursor_down(self) -> None:
        self._move_cursor(1)

    def action_cursor_up(self) -> None:
        self._move_cursor(-1)

    def action_cursor_top(self) -> None:
        self._cursor_pos = 0
        self._render_diff()
        self._scroll_to_cursor()

    def action_cursor_bottom(self) -> None:
        count = self._line_count()
        if count > 0:
            self._cursor_pos = count - 1
            self._render_diff()
            self._scroll_to_cursor()

    def action_page_down(self) -> None:
        self._move_cursor(self.size.height // 2)

    def action_page_up(self) -> None:
        self._move_cursor(-(self.size.height // 2))

    def action_next_hunk(self) -> None:
        if not self._diff_file:
            return
        for i in range(self._cursor_pos + 1, len(self._diff_file.lines)):
            if self._diff_file.lines[i].kind == "hunk_header":
                self._cursor_pos = i
                self._render_diff()
                self._scroll_to_cursor()
                return

    def action_prev_hunk(self) -> None:
        if not self._diff_file:
            return
        for i in range(self._cursor_pos - 1, -1, -1):
            if self._diff_file.lines[i].kind == "hunk_header":
                self._cursor_pos = i
                self._render_diff()
                self._scroll_to_cursor()
                return

    # -- Selection --

    def action_toggle_selection(self) -> None:
        if self._selection_anchor is None:
            self._selection_anchor = self._cursor_pos
        else:
            self._selection_anchor = None
        self._render_diff()

    def action_cancel_selection(self) -> None:
        self._selection_anchor = None
        self._render_diff()

    # -- Comment actions --

    def action_comment(self) -> None:
        if not self._diff_file:
            return
        sel = self.selection_range
        if sel:
            start, end = sel
        else:
            start = end = self._cursor_pos
        self.post_message(
            self.CommentRequested(
                file=self._diff_file.path,
                start_line=start,
                end_line=end,
            )
        )
        self._selection_anchor = None

    def action_next_comment(self) -> None:
        self.post_message(self.NavigateComment(direction=1))

    def action_prev_comment(self) -> None:
        self.post_message(self.NavigateComment(direction=-1))

    def action_undo_comment(self) -> None:
        self.post_message(self.UndoComment())

    def action_delete_comment_at_cursor(self) -> None:
        self.post_message(self.DeleteCommentAtCursor())
