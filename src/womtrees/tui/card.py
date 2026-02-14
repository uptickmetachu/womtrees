from __future__ import annotations

from datetime import datetime, timezone

from textual.widget import Widget
from textual.reactive import reactive
from textual.app import ComposeResult
from textual.widgets import Static

from womtrees.models import ClaudeSession, WorkItem


def _time_ago(iso_str: str) -> str:
    """Return a human-readable time-ago string from an ISO 8601 timestamp."""
    try:
        then = datetime.fromisoformat(iso_str)
        now = datetime.now(timezone.utc)
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
        margin: 0 0 1 0;
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
    """

    def __init__(
        self,
        work_item: WorkItem,
        sessions: list[ClaudeSession] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.work_item = work_item
        self.sessions = sessions or []

    def compose(self) -> ComposeResult:
        yield Static(self._render_title(), classes="card-title")
        if self.work_item.prompt:
            prompt = self.work_item.prompt[:40]
            if len(self.work_item.prompt) > 40:
                prompt += "..."
            yield Static(prompt, classes="card-prompt")
        for session in self.sessions:
            age = _time_ago(session.updated_at)
            cls = f"session-{session.state}"
            indicator = " *" if session.state == "waiting" else ""
            yield Static(f"C{session.id}: {session.state}{indicator} {age}", classes=cls)

    def _render_title(self) -> str:
        if self.work_item.name:
            return f"#{self.work_item.id} {self.work_item.name} ({self.work_item.branch})"
        return f"#{self.work_item.id} {self.work_item.branch}"


class UnmanagedCard(Widget, can_focus=True):
    """Card representing unmanaged Claude sessions (no WorkItem)."""

    DEFAULT_CSS = """
    UnmanagedCard {
        height: auto;
        min-height: 3;
        margin: 0 0 1 0;
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
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.branch = branch
        self.sessions = sessions

    def compose(self) -> ComposeResult:
        yield Static(f"{self.branch} (unmanaged)", classes="card-title")
        for session in self.sessions:
            age = _time_ago(session.updated_at)
            cls = f"session-{session.state}"
            indicator = " *" if session.state == "waiting" else ""
            yield Static(f"C{session.id}: {session.state}{indicator} {age}", classes=cls)
