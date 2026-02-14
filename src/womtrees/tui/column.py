from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from womtrees.models import ClaudeSession, PullRequest, WorkItem
from womtrees.tui.card import UnmanagedCard, WorkItemCard


STATUS_COLORS = {
    "todo": "$text-muted",
    "working": "$primary",
    "review": "$warning",
    "done": "$success",
}


class KanbanColumn(VerticalScroll):
    """A single column in the kanban board representing one status."""

    DEFAULT_CSS = """
    KanbanColumn {
        width: 1fr;
        height: 100%;
        border: solid $secondary;
        padding: 0 1;
    }

    KanbanColumn .column-header {
        text-style: bold;
        text-align: center;
        width: 100%;
        margin: 0 0 1 0;
    }

    KanbanColumn .repo-header {
        text-style: italic;
        color: $text-muted;
        margin: 1 0 0 0;
    }

    KanbanColumn .empty-label {
        color: $text-muted;
        text-align: center;
    }
    """

    def __init__(self, status: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.status = status
        self.cards: list[WorkItemCard | UnmanagedCard] = []

    def compose(self) -> ComposeResult:
        yield Static(
            f"{self.status.upper()} (0)",
            classes="column-header",
            id=f"header-{self.status}",
        )

    def update_cards(
        self,
        items: list[WorkItem],
        sessions_by_item: dict[int | None, list[ClaudeSession]],
        unmanaged_sessions: list[ClaudeSession],
        group_by_repo: bool,
        prs_by_item: dict[int, list[PullRequest]] | None = None,
    ) -> None:
        """Rebuild the column's cards from fresh data."""
        # Remove old cards
        for card in self.cards:
            card.remove()
        self.cards.clear()

        # Update header count
        total = len(items) + (1 if unmanaged_sessions else 0)
        header = self.query_one(f"#header-{self.status}", Static)
        header.update(f"{self.status.upper()} ({len(items)})")

        if not items and not unmanaged_sessions:
            empty = Static("(empty)", classes="empty-label")
            self.mount(empty)
            self.cards.append(empty)
            return

        if group_by_repo:
            self._mount_grouped(
                items, sessions_by_item, unmanaged_sessions, prs_by_item
            )
        else:
            self._mount_flat(items, sessions_by_item, unmanaged_sessions, prs_by_item)

    def _mount_grouped(
        self,
        items: list[WorkItem],
        sessions_by_item: dict[int | None, list[ClaudeSession]],
        unmanaged_sessions: list[ClaudeSession],
        prs_by_item: dict[int, list[PullRequest]] | None = None,
    ) -> None:
        # Group items by repo
        by_repo: dict[str, list[WorkItem]] = {}
        for item in items:
            by_repo.setdefault(item.repo_name, []).append(item)

        # Group unmanaged sessions by repo
        unmanaged_by_repo: dict[str, list[ClaudeSession]] = {}
        for s in unmanaged_sessions:
            unmanaged_by_repo.setdefault(s.repo_name, []).append(s)

        all_repos = sorted(set(list(by_repo.keys()) + list(unmanaged_by_repo.keys())))

        for repo in all_repos:
            repo_header = Static(repo, classes="repo-header")
            self.mount(repo_header)
            self.cards.append(repo_header)

            for item in by_repo.get(repo, []):
                sessions = sessions_by_item.get(item.id, [])
                item_prs = (prs_by_item or {}).get(item.id, [])
                card = WorkItemCard(item, sessions, item_prs)
                self.mount(card)
                self.cards.append(card)

            # Unmanaged sessions for this repo
            repo_unmanaged = unmanaged_by_repo.get(repo, [])
            if repo_unmanaged:
                # Group by branch
                by_branch: dict[str, list[ClaudeSession]] = {}
                for s in repo_unmanaged:
                    by_branch.setdefault(s.branch, []).append(s)
                for branch, branch_sessions in by_branch.items():
                    card = UnmanagedCard(branch, branch_sessions)
                    self.mount(card)
                    self.cards.append(card)

    def _mount_flat(
        self,
        items: list[WorkItem],
        sessions_by_item: dict[int | None, list[ClaudeSession]],
        unmanaged_sessions: list[ClaudeSession],
        prs_by_item: dict[int, list[PullRequest]] | None = None,
    ) -> None:
        for item in items:
            sessions = sessions_by_item.get(item.id, [])
            item_prs = (prs_by_item or {}).get(item.id, [])
            card = WorkItemCard(item, sessions, item_prs)
            self.mount(card)
            self.cards.append(card)

        if unmanaged_sessions:
            by_branch: dict[str, list[ClaudeSession]] = {}
            for s in unmanaged_sessions:
                by_branch.setdefault(s.branch, []).append(s)
            for branch, branch_sessions in by_branch.items():
                card = UnmanagedCard(branch, branch_sessions)
                self.mount(card)
                self.cards.append(card)

    def get_focusable_cards(self) -> list[WorkItemCard | UnmanagedCard]:
        """Return all focusable card widgets in this column."""
        return [c for c in self.cards if isinstance(c, (WorkItemCard, UnmanagedCard))]
