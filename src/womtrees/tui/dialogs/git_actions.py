from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static

from womtrees.models import GitStats, PullRequest


class GitActionsDialog(ModalScreen[str | None]):
    """Modal showing git actions for a work item."""

    BINDINGS = [
        Binding("m", "select('merge')", "Merge", show=False, priority=True),
        Binding("c", "select('commit')", "Commit", show=False, priority=True),
        Binding("r", "select('rebase')", "Rebase", show=False, priority=True),
        Binding("p", "select('push')", "Push", show=False, priority=True),
        Binding("l", "select('pull')", "Pull", show=False, priority=True),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    DEFAULT_CSS = """
    GitActionsDialog {
        align: center middle;
    }

    GitActionsDialog #dialog {
        width: 60;
        height: auto;
        padding: 1 2;
        border: thick $accent;
        background: $surface;
    }

    GitActionsDialog .git-info {
        margin: 0 0 1 0;
        color: $text-muted;
    }

    GitActionsDialog .git-action {
        padding: 0 1;
    }

    GitActionsDialog .git-action-key {
        color: $accent;
        text-style: bold;
    }

    GitActionsDialog .section-title {
        text-style: bold;
        margin: 0 0 1 0;
    }

    GitActionsDialog #cancel-btn {
        margin: 1 0 0 0;
        width: 100%;
    }
    """

    def __init__(
        self,
        branch: str,
        status: str,
        git_stats: GitStats | None = None,
        pull_requests: list[PullRequest] | None = None,
        needs_rebase: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._branch = branch
        self._status = status
        self._git_stats = git_stats
        self._pull_requests = pull_requests or []
        self._needs_rebase = needs_rebase

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(f"[bold]Git: {self._branch}[/bold]", classes="section-title")

            # Info section
            info_parts: list[str] = []
            if self._git_stats:
                if self._git_stats.insertions or self._git_stats.deletions:
                    info_parts.append(
                        f"[green]+{self._git_stats.insertions}[/] "
                        f"[red]-{self._git_stats.deletions}[/]"
                    )
                if self._git_stats.uncommitted:
                    uc_text = "[yellow]uncommitted"
                    if (
                        self._git_stats.uncommitted_insertions
                        or self._git_stats.uncommitted_deletions
                    ):
                        uc_text += (
                            f" +{self._git_stats.uncommitted_insertions}"
                            f" -{self._git_stats.uncommitted_deletions}"
                        )
                    uc_text += "[/]"
                    info_parts.append(uc_text)
                else:
                    info_parts.append("[dim]clean[/]")

            if self._needs_rebase:
                info_parts.append("[red]rebase needed[/]")

            for pr in self._pull_requests:
                pr_text = f"PR #{pr.number} {pr.status}"
                if pr.url:
                    pr_text += f" ({pr.url})"
                color = {"open": "green", "closed": "red", "merged": "magenta"}.get(
                    pr.status, ""
                )
                if color:
                    pr_text = f"[{color}]{pr_text}[/]"
                info_parts.append(pr_text)

            if info_parts:
                yield Static("  ".join(info_parts), classes="git-info")

            # Actions
            can_merge = self._status == "review"
            can_rebase = self._status == "review"
            can_push = self._status in ("working", "input", "review")
            can_pull = self._status != "done"

            yield Static(
                f"  [{'$accent' if can_merge else '$text-muted'}]\\[m][/]erge"
                + ("" if can_merge else " [dim](review only)[/]"),
                classes="git-action",
            )
            yield Static(
                "  [dim]\\[c][/dim]ommit",
                classes="git-action",
            )
            yield Static(
                f"  [{'$accent' if can_rebase else '$text-muted'}]\\[r][/]ebase"
                + ("" if can_rebase else " [dim](review only)[/]"),
                classes="git-action",
            )
            yield Static(
                f"  [{'$accent' if can_push else '$text-muted'}]\\[p][/]ush"
                + ("" if can_push else " [dim](not available)[/]"),
                classes="git-action",
            )
            yield Static(
                f"  pul[{'$accent' if can_pull else '$text-muted'}]\\[l][/]"
                + ("" if can_pull else " [dim](not available)[/]"),
                classes="git-action",
            )

            yield Button("Cancel (esc)", id="cancel-btn")

    def action_select(self, action: str) -> None:
        self.dismiss(action)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)
