from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal

from womtrees.models import ClaudeSession, WorkItem
from womtrees.tui.column import KanbanColumn


STATUSES = ["todo", "working", "input", "review", "done"]

# Map Claude session states to the kanban column they should appear in
CLAUDE_STATE_TO_STATUS = {
    "working": "working",
    "waiting": "input",
    "done": "review",
}


class KanbanBoard(Horizontal):
    """The main kanban board with 5 status columns."""

    DEFAULT_CSS = """
    KanbanBoard {
        width: 100%;
        height: 1fr;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.columns: dict[str, KanbanColumn] = {}

    def compose(self) -> ComposeResult:
        for status in STATUSES:
            col = KanbanColumn(status, id=f"col-{status}")
            self.columns[status] = col
            yield col

    def refresh_data(
        self,
        items: list[WorkItem],
        sessions: list[ClaudeSession],
        group_by_repo: bool,
    ) -> None:
        """Refresh all columns with new data."""
        # Group items by status
        items_by_status: dict[str, list[WorkItem]] = {s: [] for s in STATUSES}
        for item in items:
            if item.status in items_by_status:
                items_by_status[item.status].append(item)

        # Group sessions by work_item_id
        sessions_by_item: dict[int | None, list[ClaudeSession]] = {}
        unmanaged: list[ClaudeSession] = []
        for s in sessions:
            if s.work_item_id is not None:
                sessions_by_item.setdefault(s.work_item_id, []).append(s)
            else:
                unmanaged.append(s)

        # Group unmanaged sessions by the status column they belong in
        unmanaged_by_status: dict[str, list[ClaudeSession]] = {s: [] for s in STATUSES}
        for s in unmanaged:
            target = CLAUDE_STATE_TO_STATUS.get(s.state, "working")
            unmanaged_by_status[target].append(s)

        for status in STATUSES:
            self.columns[status].update_cards(
                items_by_status[status],
                sessions_by_item,
                unmanaged_by_status[status],
                group_by_repo,
            )
