# Update-in-Place Cards

## Problem

Every refresh in `KanbanColumn.update_cards()` (column.py:57-84) removes all card widgets and remounts them from scratch. This causes visible flicker even when nothing changed, and loses scroll position within columns.

## Design

Keep card widgets alive across refreshes. Each card gets a stable key. On refresh, diff incoming data against mounted cards: add new, remove gone, update existing in-place. Cards never unmount unless the underlying item is actually deleted or moved to a different column.

## Implementation

### A. Add stable keys to cards

Cards are identified by:
- `WorkItemCard` -> `f"item-{work_item.id}"`
- `UnmanagedCard` -> `f"unmanaged-{branch}"`

Set the Textual widget `id` to this key on construction so cards can be queried by id.

### B. Add `update_data()` to card widgets

In `card.py`, add a method to update content without remounting:

```python
class WorkItemCard(Widget, can_focus=True):
    def __init__(self, work_item, sessions=None, **kwargs):
        key = f"item-{work_item.id}"
        super().__init__(id=key, **kwargs)
        self.work_item = work_item
        self.sessions = sessions or []

    def update_data(self, work_item: WorkItem, sessions: list[ClaudeSession]) -> None:
        """Update card content in-place without remounting."""
        self.work_item = work_item
        self.sessions = sessions
        # Replace child Static widgets with new content
        self._rebuild_children()

    def _rebuild_children(self) -> None:
        """Remove and remount only the child Static widgets."""
        for child in list(self.children):
            child.remove()
        self.mount(Static(self._render_title(), classes="card-title"))
        if self.work_item.prompt:
            prompt = self.work_item.prompt[:40]
            if len(self.work_item.prompt) > 40:
                prompt += "..."
            self.mount(Static(prompt, classes="card-prompt"))
        for session in self.sessions:
            age = _time_ago(session.updated_at)
            cls = f"session-{session.state}"
            indicator = " *" if session.state == "waiting" else ""
            self.mount(Static(f"C{session.id}: {session.state}{indicator} {age}", classes=cls))
```

Same pattern for `UnmanagedCard`:

```python
class UnmanagedCard(Widget, can_focus=True):
    def __init__(self, branch, sessions, **kwargs):
        key = f"unmanaged-{branch}"
        super().__init__(id=key, **kwargs)
        self.branch = branch
        self.sessions = sessions

    def update_data(self, sessions: list[ClaudeSession]) -> None:
        self.sessions = sessions
        self._rebuild_children()

    def _rebuild_children(self) -> None:
        for child in list(self.children):
            child.remove()
        self.mount(Static(f"{self.branch} (unmanaged)", classes="card-title"))
        for session in self.sessions:
            age = _time_ago(session.updated_at)
            cls = f"session-{session.state}"
            indicator = " *" if session.state == "waiting" else ""
            self.mount(Static(f"C{session.id}: {session.state}{indicator} {age}", classes=cls))
```

### C. Rewrite `KanbanColumn.update_cards()` with diff logic

Replace the teardown-and-rebuild in `column.py`:

```python
class KanbanColumn(VerticalScroll):
    def __init__(self, status, **kwargs):
        super().__init__(**kwargs)
        self.status = status
        self.card_map: dict[str, WorkItemCard | UnmanagedCard] = {}

    def update_cards(self, items, sessions_by_item, unmanaged_sessions, group_by_repo):
        # Update header count
        header = self.query_one(f"#header-{self.status}", Static)
        header.update(f"{self.status.upper()} ({len(items)})")

        # Build incoming key -> data map
        incoming: dict[str, tuple] = {}
        for item in items:
            key = f"item-{item.id}"
            sessions = sessions_by_item.get(item.id, [])
            incoming[key] = ("item", item, sessions)

        by_branch: dict[str, list] = {}
        for s in unmanaged_sessions:
            by_branch.setdefault(s.branch, []).append(s)
        for branch, branch_sessions in by_branch.items():
            key = f"unmanaged-{branch}"
            incoming[key] = ("unmanaged", branch, branch_sessions)

        incoming_keys = set(incoming.keys())
        existing_keys = set(self.card_map.keys())

        # Remove cards no longer present
        for key in existing_keys - incoming_keys:
            self.card_map[key].remove()
            del self.card_map[key]

        # Update existing cards
        for key in existing_keys & incoming_keys:
            data = incoming[key]
            card = self.card_map[key]
            if data[0] == "item":
                card.update_data(data[1], data[2])
            else:
                card.update_data(data[2])

        # Mount new cards
        for key in incoming_keys - existing_keys:
            data = incoming[key]
            if data[0] == "item":
                card = WorkItemCard(data[1], data[2])
            else:
                card = UnmanagedCard(data[1], data[2])
            self.mount(card)
            self.card_map[key] = card

        # Handle empty state
        empty_id = f"empty-{self.status}"
        existing_empty = self.query(f"#{empty_id}")
        if not incoming:
            if not existing_empty:
                self.mount(Static("(empty)", classes="empty-label", id=empty_id))
        else:
            for e in existing_empty:
                e.remove()
```

Note: this simplified version drops repo-grouping header Statics. When `group_by_repo` is true, repo headers are non-focusable decorative Statics. These can be handled separately as a lightweight add -- mount repo header Statics before their group of cards based on sort order. Since they're non-interactive, tearing them down and remounting is fine (they don't flicker visibly like cards do).

### D. Remove focus-save/restore from `app.py`

Since cards are no longer destroyed, the `_get_focused_card_key()` and `_restore_focus()` methods (app.py:124-143) become unnecessary. The focused widget stays in the DOM, so focus is preserved automatically.

Remove:
- `_get_focused_card_key()` method
- `_restore_focus()` method
- The focused_key save/restore logic in `_refresh_board()` (lines 97, 121-122)

The simplified `_refresh_board()`:

```python
def _refresh_board(self) -> None:
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
```

## Files changed

- `src/womtrees/tui/card.py` -- add `update_data()`, `_rebuild_children()`, set widget `id` from key
- `src/womtrees/tui/column.py` -- rewrite `update_cards()` with diff logic, replace `cards` list with `card_map` dict
- `src/womtrees/tui/app.py` -- remove focus save/restore logic from `_refresh_board()`

## Testing

### A test: update_data changes content without remount

```python
def test_work_item_card_update_in_place():
    """update_data changes card content without destroying the widget."""
    item = WorkItem(id=1, repo_name="r", repo_path="/r", branch="b",
                    prompt=None, worktree_path=None, tmux_session=None,
                    status="todo", created_at="", updated_at="")
    card = WorkItemCard(item)
    widget_id_before = id(card)

    item2 = WorkItem(id=1, repo_name="r", repo_path="/r", branch="b",
                     prompt="new prompt", worktree_path=None, tmux_session=None,
                     status="working", created_at="", updated_at="")
    card.update_data(item2, [])
    assert id(card) == widget_id_before  # same widget object
    assert card.work_item.status == "working"
```

### B test: column diff adds/removes correctly

```python
def test_column_diff_adds_new_removes_gone():
    """Column only mounts new cards and removes gone ones."""
    # First update: items [1, 2]
    # Second update: items [2, 3]
    # Assert: item-1 removed, item-2 updated, item-3 mounted
```
