from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from womtrees.models import ClaudeSession, GitStats, PullRequest, WorkItem
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

    def __init__(self, status: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.status = status
        self.card_map: dict[str, WorkItemCard | UnmanagedCard] = {}
        self._repo_header_map: dict[str, Static] = {}
        self._empty_label: Static | None = None
        self._first_update: bool = True

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
        git_stats: dict[int, GitStats] | None = None,
    ) -> None:
        """Diff-based update: reuse existing cards, only add/remove as needed."""
        # Update header count
        header = self.query_one(f"#header-{self.status}", Static)
        header.update(f"{self.status.upper()} ({len(items)})")

        # Build incoming card data keyed by widget ID
        incoming: dict[str, dict[str, Any]] = {}
        ordered_ids: list[str] = []
        needed_repos: list[str] = []  # ordered, unique repo names

        if group_by_repo:
            self._collect_grouped(
                incoming,
                ordered_ids,
                needed_repos,
                items,
                sessions_by_item,
                unmanaged_sessions,
                prs_by_item,
                git_stats,
            )
        else:
            self._collect_flat(
                incoming,
                ordered_ids,
                items,
                sessions_by_item,
                unmanaged_sessions,
                prs_by_item,
                git_stats,
            )

        # Remove empty label if we now have content
        if ordered_ids and self._empty_label is not None:
            self._empty_label.remove()
            self._empty_label = None

        # Remove repo headers for repos no longer present
        if group_by_repo:
            needed_set = set(needed_repos)
            for repo in list(self._repo_header_map.keys()):
                if repo not in needed_set:
                    self._repo_header_map[repo].remove()
                    del self._repo_header_map[repo]
        else:
            # Not grouping — remove all repo headers
            for hdr in self._repo_header_map.values():
                hdr.remove()
            self._repo_header_map.clear()

        # Remove cards that are no longer present
        gone = set(self.card_map.keys()) - set(ordered_ids)
        for card_id in gone:
            self.card_map[card_id].remove()
            del self.card_map[card_id]

        # Update existing cards and create new ones (not yet mounted)
        new_card_ids: list[str] = []
        for card_id in ordered_ids:
            data = incoming[card_id]
            if card_id in self.card_map:
                card = self.card_map[card_id]
                if isinstance(card, WorkItemCard) and data["type"] == "item":
                    card.update_data(
                        data["work_item"],
                        data["sessions"],
                        data["prs"],
                        data["git_stats"],
                    )
                elif isinstance(card, UnmanagedCard) and data["type"] == "unmanaged":
                    card.update_data(data["sessions"])
            else:
                if data["type"] == "item":
                    card = WorkItemCard(
                        data["work_item"],
                        data["sessions"],
                        data["prs"],
                        git_stats=data["git_stats"],
                    )
                else:
                    card = UnmanagedCard(data["branch"], data["sessions"])
                self.card_map[card_id] = card
                new_card_ids.append(card_id)

        # Show empty label if nothing to display
        if not ordered_ids:
            if self._empty_label is None:
                self._empty_label = Static("(empty)", classes="empty-label")
                self.mount(self._empty_label)
            return

        # On the very first update, mount everything in order (DOM is empty)
        if self._first_update:
            self._first_update = False
            if group_by_repo:
                last_repo: str | None = None
                for card_id in ordered_ids:
                    repo = str(incoming[card_id].get("repo", ""))
                    if repo and repo != last_repo:
                        hdr = Static(repo, classes="repo-header")
                        self._repo_header_map[repo] = hdr
                        self.mount(hdr)
                        last_repo = repo
                    self.mount(self.card_map[card_id])
            else:
                for card_id in ordered_ids:
                    self.mount(self.card_map[card_id])
            return

        # Subsequent updates: only mount NEW repo headers and NEW cards
        if group_by_repo:
            for repo in needed_repos:
                if repo not in self._repo_header_map:
                    hdr = Static(repo, classes="repo-header")
                    self._repo_header_map[repo] = hdr
                    self.mount(hdr)

        for card_id in new_card_ids:
            self.mount(self.card_map[card_id])

    def _collect_grouped(
        self,
        incoming: dict[str, dict[str, Any]],
        ordered_ids: list[str],
        needed_repos: list[str],
        items: list[WorkItem],
        sessions_by_item: dict[int | None, list[ClaudeSession]],
        unmanaged_sessions: list[ClaudeSession],
        prs_by_item: dict[int, list[PullRequest]] | None = None,
        git_stats: dict[int, GitStats] | None = None,
    ) -> None:
        by_repo: dict[str, list[WorkItem]] = {}
        for item in items:
            by_repo.setdefault(item.repo_name, []).append(item)

        unmanaged_by_repo: dict[str, list[ClaudeSession]] = {}
        for s in unmanaged_sessions:
            unmanaged_by_repo.setdefault(s.repo_name, []).append(s)

        all_repos = sorted(set(list(by_repo.keys()) + list(unmanaged_by_repo.keys())))
        needed_repos.extend(all_repos)

        for repo in all_repos:
            for item in by_repo.get(repo, []):
                card_id = f"item-{item.id}"
                sessions = sessions_by_item.get(item.id, [])
                item_prs = (prs_by_item or {}).get(item.id, [])
                stats = git_stats.get(item.id) if git_stats else None
                incoming[card_id] = {
                    "type": "item",
                    "work_item": item,
                    "sessions": sessions,
                    "prs": item_prs,
                    "git_stats": stats,
                    "repo": repo,
                }
                ordered_ids.append(card_id)

            repo_unmanaged = unmanaged_by_repo.get(repo, [])
            if repo_unmanaged:
                by_branch: dict[str, list[ClaudeSession]] = {}
                for s in repo_unmanaged:
                    by_branch.setdefault(s.branch, []).append(s)
                for branch, branch_sessions in by_branch.items():
                    card_id = f"unmanaged-{branch}"
                    incoming[card_id] = {
                        "type": "unmanaged",
                        "branch": branch,
                        "sessions": branch_sessions,
                        "repo": repo,
                    }
                    ordered_ids.append(card_id)

    def _collect_flat(
        self,
        incoming: dict[str, dict[str, Any]],
        ordered_ids: list[str],
        items: list[WorkItem],
        sessions_by_item: dict[int | None, list[ClaudeSession]],
        unmanaged_sessions: list[ClaudeSession],
        prs_by_item: dict[int, list[PullRequest]] | None = None,
        git_stats: dict[int, GitStats] | None = None,
    ) -> None:
        for item in items:
            card_id = f"item-{item.id}"
            sessions = sessions_by_item.get(item.id, [])
            item_prs = (prs_by_item or {}).get(item.id, [])
            stats = git_stats.get(item.id) if git_stats else None
            incoming[card_id] = {
                "type": "item",
                "work_item": item,
                "sessions": sessions,
                "prs": item_prs,
                "git_stats": stats,
            }
            ordered_ids.append(card_id)

        if unmanaged_sessions:
            by_branch: dict[str, list[ClaudeSession]] = {}
            for s in unmanaged_sessions:
                by_branch.setdefault(s.branch, []).append(s)
            for branch, branch_sessions in by_branch.items():
                card_id = f"unmanaged-{branch}"
                incoming[card_id] = {
                    "type": "unmanaged",
                    "branch": branch,
                    "sessions": branch_sessions,
                }
                ordered_ids.append(card_id)

    def get_focusable_cards(self) -> list[WorkItemCard | UnmanagedCard]:
        """Return all focusable card widgets in this column."""
        return list(self.card_map.values())
