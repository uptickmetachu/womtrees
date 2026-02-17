from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from womtrees.models import ClaudeSession, GitStats, PullRequest, WorkItem


def _time_ago(iso_str: str) -> str:
    """Return a human-readable time-ago string from an ISO 8601 timestamp."""
    try:
        then = datetime.fromisoformat(iso_str)
        now = datetime.now(UTC)
        delta = now - then
        minutes = int(delta.total_seconds() / 60)
        if minutes < 1:
            return "<1m"
        if minutes < 60:
            return f"{minutes}m"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h"
        days = hours // 24
        return f"{days}d"
    except (ValueError, TypeError):
        return "?"


class WorkItemCard(Widget, can_focus=True):
    """Card representing a WorkItem with its Claude sessions."""

    COMPONENT_CLASSES = {"card--waiting"}

    DEFAULT_CSS = """
    WorkItemCard {
        height: auto;
        min-height: 3;
        padding: 0 1;
        border: solid $secondary;
    }

    WorkItemCard:focus {
        border: heavy $accent;
    }

    WorkItemCard .card-title {
        text-style: bold;
    }

    WorkItemCard .card-prompt {
        color: $text-muted;
    }

    WorkItemCard .session-waiting {
        color: $warning;
        text-style: bold;
    }

    WorkItemCard .session-working {
        color: $success;
    }

    WorkItemCard .session-done {
        color: $text-muted;
    }

    WorkItemCard .pr-open {
        color: $success;
    }

    WorkItemCard .pr-closed {
        color: $error;
    }

    WorkItemCard .pr-merged {
        color: $accent;
    }

    WorkItemCard .git-added {
        color: $success;
    }

    WorkItemCard .git-removed {
        color: $error;
    }

    WorkItemCard .git-dirty {
        color: $warning;
    }
    """

    def __init__(
        self,
        work_item: WorkItem,
        sessions: list[ClaudeSession] | None = None,
        pull_requests: list[PullRequest] | None = None,
        git_stats: GitStats | None = None,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("id", f"item-{work_item.id}")
        super().__init__(**kwargs)
        self.work_item = work_item
        self.sessions = sessions or []
        self.pull_requests = pull_requests or []
        self.git_stats = git_stats

    def compose(self) -> ComposeResult:
        yield from self._build_children()

    def _build_children(self) -> list[Static]:
        children: list[Static] = []
        children.append(Static(self._render_title(), classes="card-title"))
        if self.git_stats:
            children.append(Static(self._render_git_stats(), classes="git-stats"))
        if self.work_item.prompt:
            prompt = self.work_item.prompt[:40]
            if len(self.work_item.prompt) > 40:
                prompt += "..."
            children.append(Static(prompt, classes="card-prompt"))
        for session in self.sessions:
            age = _time_ago(session.updated_at)
            cls = f"session-{session.state}"
            indicator = " *" if session.state == "waiting" else ""
            children.append(
                Static(f"C{session.id}: {session.state}{indicator} {age}", classes=cls),
            )
        for pr in self.pull_requests:
            cls = f"pr-{pr.status}"
            children.append(Static(f"PR #{pr.number} {pr.status}", classes=cls))
        return children

    def update_data(
        self,
        work_item: WorkItem,
        sessions: list[ClaudeSession] | None = None,
        pull_requests: list[PullRequest] | None = None,
        git_stats: GitStats | None = None,
    ) -> None:
        """Update card data and rebuild children in-place (no flicker)."""
        self.work_item = work_item
        self.sessions = sessions or []
        self.pull_requests = pull_requests or []
        self.git_stats = git_stats
        self._rebuild_children()

    def _rebuild_children(self) -> None:
        """Remove existing child widgets and mount fresh ones."""
        for child in list(self.children):
            child.remove()
        for widget in self._build_children():
            self.mount(widget)

    def _render_title(self) -> str:
        if self.work_item.name:
            return (
                f"#{self.work_item.id} {self.work_item.name} ({self.work_item.branch})"
            )
        return f"#{self.work_item.id} {self.work_item.branch}"

    def _render_git_stats(self) -> str:
        assert self.git_stats is not None
        parts: list[str] = []
        if self.git_stats.insertions or self.git_stats.deletions:
            parts.append(
                f"[green]+{self.git_stats.insertions}[/] "
                f"[red]-{self.git_stats.deletions}[/]",
            )
        if self.git_stats.uncommitted:
            uc = "[yellow]\\[uncommitted"
            if (
                self.git_stats.uncommitted_insertions
                or self.git_stats.uncommitted_deletions
            ):
                uc += (
                    f" +{self.git_stats.uncommitted_insertions}"
                    f" -{self.git_stats.uncommitted_deletions}"
                )
            uc += "][/]"
            parts.append(uc)
        return " ".join(parts)


class UnmanagedCard(Widget, can_focus=True):
    """Card representing unmanaged Claude sessions (no WorkItem)."""

    DEFAULT_CSS = """
    UnmanagedCard {
        height: auto;
        min-height: 3;
        padding: 0 1;
        border: dashed $secondary;
    }

    UnmanagedCard:focus {
        border: heavy $accent;
    }

    UnmanagedCard .card-title {
        text-style: italic;
    }

    UnmanagedCard .session-waiting {
        color: $warning;
        text-style: bold;
    }

    UnmanagedCard .session-working {
        color: $success;
    }
    """

    def __init__(
        self,
        branch: str,
        sessions: list[ClaudeSession],
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("id", f"unmanaged-{branch}")
        super().__init__(**kwargs)
        self.branch = branch
        self.sessions = sessions

    def compose(self) -> ComposeResult:
        yield from self._build_children()

    def _build_children(self) -> list[Static]:
        children: list[Static] = []
        children.append(Static(f"{self.branch} (unmanaged)", classes="card-title"))
        for session in self.sessions:
            age = _time_ago(session.updated_at)
            cls = f"session-{session.state}"
            indicator = " *" if session.state == "waiting" else ""
            children.append(
                Static(f"C{session.id}: {session.state}{indicator} {age}", classes=cls),
            )
        return children

    def update_data(
        self,
        sessions: list[ClaudeSession],
    ) -> None:
        """Update card data and rebuild children in-place (no flicker)."""
        self.sessions = sessions
        self._rebuild_children()

    def _rebuild_children(self) -> None:
        """Remove existing child widgets and mount fresh ones."""
        for child in list(self.children):
            child.remove()
        for widget in self._build_children():
            self.mount(widget)
