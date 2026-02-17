"""Custom diff viewer widget with vim navigation and visual selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rich.text import Text
from textual.binding import Binding
from textual.cache import LRUCache
from textual.events import MouseDown, MouseMove, MouseUp
from textual.geometry import Size
from textual.message import Message
from textual.scroll_view import ScrollView
from textual.strip import Strip

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


class DiffView(ScrollView):
    """Scrollable diff viewer with vim-style navigation."""

    can_focus = True

    BINDINGS = [
        Binding("j,down", "cursor_down", "Down", show=False),
        Binding("k,up", "cursor_up", "Up", show=False),
        Binding("g", "cursor_top", "Top", show=False),
        Binding("G", "cursor_bottom", "Bottom", show=False),
        Binding("ctrl+d,}", "page_down", "Page down", show=False),
        Binding("ctrl+u,{", "page_up", "Page up", show=False),
        Binding("],right_square_bracket", "next_hunk", "Next hunk", show=False),
        Binding("[,left_square_bracket", "prev_hunk", "Prev hunk", show=False),
        Binding("v", "toggle_selection", "Select", show=False),
        Binding("escape", "cancel_selection", "Cancel", show=False),
        Binding("c", "comment", "Comment", show=False),
        Binding("n", "next_comment", "Next comment", show=False),
        Binding("N", "prev_comment", "Prev comment", show=False),
        Binding("u", "undo_comment", "Undo comment", show=False),
        Binding(
            "x",
            "delete_comment_at_cursor",
            "Delete comment",
            show=False,
        ),
        Binding("e", "edit_comment", "Edit comment", show=False),
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

    class EditCommentAtCursor(Message):
        """User pressed 'e' to edit comment at cursor."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._diff_file: DiffFile | None = None
        self._cursor_pos: int = 0
        self._selection_anchor: int | None = None
        self._file_comments: list[ReviewComment] = []
        self._commented_lines: set[int] = set()
        self._line_cache: LRUCache[tuple[object, ...], Strip] = LRUCache(2048)

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

    def _y_to_line_idx(self, y: int) -> int | None:
        """Convert a widget-relative y coordinate to a line index."""
        line_idx = self.scroll_offset.y + y
        count = self._line_count()
        if count == 0 or line_idx < 0 or line_idx >= count:
            return None
        return line_idx

    def on_mouse_down(self, event: MouseDown) -> None:
        """Start drag selection."""
        idx = self._y_to_line_idx(event.y)
        if idx is not None:
            self._selection_anchor = idx
            self._cursor_pos = idx
            self._line_cache.clear()
            self.refresh()
            self.capture_mouse()

    def on_mouse_move(self, event: MouseMove) -> None:
        """Extend selection while dragging."""
        if self._selection_anchor is None:
            return
        if not event.button:
            return
        idx = self._y_to_line_idx(event.y)
        if idx is not None and idx != self._cursor_pos:
            self._cursor_pos = idx
            self._line_cache.clear()
            self.refresh()

    def on_mouse_up(self, event: MouseUp) -> None:
        """End drag selection."""
        self.release_mouse()

    def load_file(self, diff_file: DiffFile) -> None:
        """Load a new file's diff into the view."""
        self._diff_file = diff_file
        self._cursor_pos = 0
        self._selection_anchor = None
        self._invalidate()
        self.scroll_to(0, 0, animate=False)

    def set_comments(self, comments: list[ReviewComment]) -> None:
        """Update comments and re-render."""
        self._file_comments = comments
        self._recompute_commented_lines()
        self._invalidate()

    def clear(self) -> None:
        """Clear the diff view."""
        self._diff_file = None
        self._invalidate()

    def _invalidate(self) -> None:
        """Recompute virtual size and trigger re-render."""
        self._line_cache.clear()
        self._recompute_commented_lines()
        count = self._line_count()
        width = self.size.width if self.size.width else 120
        self.virtual_size = Size(width, count)
        self.refresh()

    def _recompute_commented_lines(self) -> None:
        """Cache the set of line indices that have comments."""
        lines: set[int] = set()
        if self._diff_file:
            for c in self._file_comments:
                if c.file == self._diff_file.path:
                    for i in range(c.start_line, c.end_line + 1):
                        lines.add(i)
        self._commented_lines = lines

    def _line_count(self) -> int:
        if not self._diff_file:
            return 0
        return len(self._diff_file.lines)

    # -- Virtual scrolling render --

    def render_line(self, y: int) -> Strip:
        scroll_x, scroll_y = self.scroll_offset
        line_idx = scroll_y + y
        width = self.scrollable_content_region.width

        if not self._diff_file or line_idx >= len(self._diff_file.lines):
            return Strip.blank(width, self.rich_style)

        sel = self.selection_range
        cache_key = (
            line_idx,
            scroll_x,
            width,
            self._cursor_pos == line_idx,
            sel,
            line_idx in self._commented_lines,
        )
        if cache_key in self._line_cache:
            return self._line_cache[cache_key]

        line = self._diff_file.lines[line_idx]
        text = self._build_line(line_idx, line, sel, self._commented_lines)

        # Convert Rich Text to Strip
        segments = list(text.render(self.app.console))
        strip = Strip(segments)
        # Pad to full width and crop for horizontal scroll
        strip = strip.extend_cell_length(width, self.rich_style)
        strip = strip.crop(scroll_x, scroll_x + width)

        self._line_cache[cache_key] = strip
        return strip

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

        # Cursor line highlight
        if idx == self._cursor_pos:
            bg = bg or _BG_CURSOR
            text.stylize(f"on {bg} bold underline")
        elif bg:
            text.stylize(f"on {bg}")

        return text

    # -- Cursor movement --

    def _move_cursor(self, delta: int) -> None:
        count = self._line_count()
        if count == 0:
            return
        new_pos = max(0, min(count - 1, self._cursor_pos + delta))
        if new_pos == self._cursor_pos:
            return
        self._cursor_pos = new_pos
        self._line_cache.clear()
        self.refresh()
        self._scroll_to_cursor()

    def _scroll_to_cursor(self) -> None:
        """Scroll only if cursor is outside the visible viewport."""
        margin = 3
        top = self.scroll_offset.y
        bottom = top + self.scrollable_content_region.height
        if self._cursor_pos < top + margin:
            self.scroll_to(
                y=max(0, self._cursor_pos - margin),
                animate=False,
            )
        elif self._cursor_pos >= bottom - margin:
            target = (
                self._cursor_pos - self.scrollable_content_region.height + margin + 1
            )
            self.scroll_to(y=target, animate=False)

    # -- Navigation actions --

    def action_cursor_down(self) -> None:
        self._move_cursor(1)

    def action_cursor_up(self) -> None:
        self._move_cursor(-1)

    def action_cursor_top(self) -> None:
        self._cursor_pos = 0
        self._line_cache.clear()
        self.refresh()
        self.scroll_to(y=0, animate=False)

    def action_cursor_bottom(self) -> None:
        count = self._line_count()
        if count > 0:
            self._cursor_pos = count - 1
            self._line_cache.clear()
            self.refresh()
            self._scroll_to_cursor()

    def action_page_down(self) -> None:
        self._move_cursor(self.scrollable_content_region.height // 2)

    def action_page_up(self) -> None:
        self._move_cursor(-(self.scrollable_content_region.height // 2))

    def action_next_hunk(self) -> None:
        if not self._diff_file:
            return
        for i in range(self._cursor_pos + 1, len(self._diff_file.lines)):
            if self._diff_file.lines[i].kind == "hunk_header":
                self._cursor_pos = i
                self._line_cache.clear()
                self.refresh()
                self._scroll_to_cursor()
                return

    def action_prev_hunk(self) -> None:
        if not self._diff_file:
            return
        for i in range(self._cursor_pos - 1, -1, -1):
            if self._diff_file.lines[i].kind == "hunk_header":
                self._cursor_pos = i
                self._line_cache.clear()
                self.refresh()
                self._scroll_to_cursor()
                return

    # -- Selection --

    def action_toggle_selection(self) -> None:
        if self._selection_anchor is None:
            self._selection_anchor = self._cursor_pos
        else:
            self._selection_anchor = None
        self._line_cache.clear()
        self.refresh()

    def action_cancel_selection(self) -> None:
        self._selection_anchor = None
        self._line_cache.clear()
        self.refresh()

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

    def action_edit_comment(self) -> None:
        self.post_message(self.EditCommentAtCursor())
