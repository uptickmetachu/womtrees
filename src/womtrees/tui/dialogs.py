from __future__ import annotations

from collections.abc import Callable
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, RichLog, Select, TextArea


class CreateDialog(ModalScreen[dict | None]):
    """Modal dialog for creating a new WorkItem."""

    BINDINGS = [
        Binding("ctrl+enter", "submit", "Submit", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    DEFAULT_CSS = """
    CreateDialog {
        align: center middle;
    }

    CreateDialog #dialog {
        width: 60;
        height: auto;
        padding: 1 2;
        border: thick $accent;
        background: $surface;
    }

    CreateDialog #dialog Label {
        margin: 1 0 0 0;
    }

    CreateDialog #dialog Input, CreateDialog #dialog TextArea, CreateDialog #dialog Select {
        margin: 0 0 1 0;
    }

    CreateDialog #repo-path-input {
        display: none;
    }

    CreateDialog .show-other #repo-path-input {
        display: block;
    }

    CreateDialog .buttons {
        height: auto;
        margin: 1 0 0 0;
        align: center middle;
    }

    CreateDialog .buttons Button {
        margin: 0 1;
    }
    """

    _OTHER_SENTINEL = "__other__"

    def __init__(
        self,
        mode: str = "create",
        repos: list[tuple[str, str]] | None = None,
        default_repo: tuple[str, str] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.mode = mode  # "create" or "todo"
        self.repos = repos or []
        self.default_repo = default_repo

    def compose(self) -> ComposeResult:
        title = "Create & Launch" if self.mode == "create" else "Create TODO"

        # Build repo select options
        options: list[tuple[str, str | None]] = []
        default_value = Select.BLANK
        seen = set()
        for repo_name, repo_path in self.repos:
            key = (repo_name, repo_path)
            if key not in seen:
                seen.add(key)
                options.append((repo_name, repo_path))
        # Ensure default repo is in the list
        if (
            self.default_repo
            and (self.default_repo[0], self.default_repo[1]) not in seen
        ):
            options.insert(0, (self.default_repo[0], self.default_repo[1]))
        options.append(("Other...", self._OTHER_SENTINEL))

        if self.default_repo:
            default_value = self.default_repo[1]

        with Vertical(id="dialog"):
            yield Label(f"[bold]{title}[/bold]")
            yield Label("Repo:")
            yield Select(
                [(label, value) for label, value in options],
                value=default_value,
                id="repo-select",
            )
            yield Input(placeholder="/path/to/repo", id="repo-path-input")
            yield Label("Name:")
            yield Input(placeholder="Short description", id="name-input")
            yield Label("Branch:")
            yield Input(placeholder="feat/my-feature", id="branch-input")
            yield Label("Prompt:")
            yield TextArea(id="prompt-input")
            with Grid(classes="buttons"):
                yield Button("Submit", variant="primary", id="submit")
                yield Button("Cancel", id="cancel")

    def on_select_changed(self, event: Select.Changed) -> None:
        dialog = self.query_one("#dialog", Vertical)
        if event.value == self._OTHER_SENTINEL:
            dialog.add_class("show-other")
            self.query_one("#repo-path-input", Input).focus()
        else:
            dialog.remove_class("show-other")

    def action_submit(self) -> None:
        from pathlib import Path

        repo_select = self.query_one("#repo-select", Select)
        repo_path_input = self.query_one("#repo-path-input", Input)
        name_input = self.query_one("#name-input", Input)
        branch_input = self.query_one("#branch-input", Input)
        prompt_input = self.query_one("#prompt-input", TextArea)
        name = name_input.value.strip() or None
        branch = branch_input.value.strip()
        prompt = prompt_input.text.strip() or None

        # Resolve repo
        if repo_select.value == self._OTHER_SENTINEL:
            raw = repo_path_input.value.strip()
            if not raw:
                repo_path_input.focus()
                return
            resolved = Path(raw).expanduser().resolve()
            repo_name = resolved.name
            repo_path = str(resolved)
        elif repo_select.value is not Select.BLANK:
            repo_path = repo_select.value
            # Find repo_name from our options
            repo_name = Path(repo_path).name
            for rn, rp in self.repos:
                if rp == repo_path:
                    repo_name = rn
                    break
            if self.default_repo and self.default_repo[1] == repo_path:
                repo_name = self.default_repo[0]
        else:
            repo_select.focus()
            return

        if not branch:
            branch_input.focus()
            return

        self.dismiss(
            {
                "branch": branch,
                "prompt": prompt,
                "name": name,
                "mode": self.mode,
                "repo_name": repo_name,
                "repo_path": repo_path,
            }
        )

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit":
            self.action_submit()
        elif event.button.id == "cancel":
            self.action_cancel()


class DeleteDialog(ModalScreen[bool]):
    """Confirmation dialog for deleting a WorkItem."""

    BINDINGS = [
        Binding("ctrl+enter", "confirm", "Confirm", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    DEFAULT_CSS = """
    DeleteDialog {
        align: center middle;
    }

    DeleteDialog #dialog {
        width: 50;
        height: auto;
        padding: 1 2;
        border: thick $error;
        background: $surface;
    }

    DeleteDialog .buttons {
        height: auto;
        margin: 1 0 0 0;
        align: center middle;
    }

    DeleteDialog .buttons Button {
        margin: 0 1;
    }
    """

    def __init__(self, message: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.message)
            with Grid(classes="buttons"):
                yield Button("Delete", variant="error", id="confirm")
                yield Button("Cancel", variant="primary", id="cancel")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm":
            self.action_confirm()
        else:
            self.action_cancel()


class MergeDialog(ModalScreen[bool]):
    """Confirmation dialog for merging a branch."""

    BINDINGS = [
        Binding("ctrl+enter", "confirm", "Confirm", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    DEFAULT_CSS = """
    MergeDialog {
        align: center middle;
    }

    MergeDialog #dialog {
        width: 55;
        height: auto;
        padding: 1 2;
        border: thick $success;
        background: $surface;
    }

    MergeDialog .buttons {
        height: auto;
        margin: 1 0 0 0;
        align: center middle;
    }

    MergeDialog .buttons Button {
        margin: 0 1;
    }
    """

    def __init__(self, message: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.message)
            with Grid(classes="buttons"):
                yield Button("Merge", variant="success", id="confirm")
                yield Button("Cancel", variant="primary", id="cancel")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm":
            self.action_confirm()
        else:
            self.action_cancel()


class RebaseDialog(ModalScreen[bool]):
    """Prompt dialog offering to rebase a branch before merging."""

    BINDINGS = [
        Binding("ctrl+enter", "confirm", "Confirm", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    DEFAULT_CSS = """
    RebaseDialog {
        align: center middle;
    }

    RebaseDialog #dialog {
        width: 55;
        height: auto;
        padding: 1 2;
        border: thick $warning;
        background: $surface;
    }

    RebaseDialog .buttons {
        height: auto;
        margin: 1 0 0 0;
        align: center middle;
    }

    RebaseDialog .buttons Button {
        margin: 0 1;
    }
    """

    def __init__(self, message: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.message)
            with Grid(classes="buttons"):
                yield Button("Rebase", variant="warning", id="confirm")
                yield Button("Cancel", variant="primary", id="cancel")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm":
            self.action_confirm()
        else:
            self.action_cancel()


class AutoRebaseDialog(ModalScreen[bool]):
    """Prompt dialog offering to use Claude to auto-rebase a branch."""

    BINDINGS = [
        Binding("ctrl+enter", "confirm", "Confirm", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    DEFAULT_CSS = """
    AutoRebaseDialog {
        align: center middle;
    }

    AutoRebaseDialog #dialog {
        width: 60;
        height: auto;
        padding: 1 2;
        border: thick $error;
        background: $surface;
    }

    AutoRebaseDialog .buttons {
        height: auto;
        margin: 1 0 0 0;
        align: center middle;
    }

    AutoRebaseDialog .buttons Button {
        margin: 0 1;
    }
    """

    def __init__(self, message: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.message)
            with Grid(classes="buttons"):
                yield Button("Auto-rebase", variant="error", id="confirm")
                yield Button("Cancel", variant="primary", id="cancel")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm":
            self.action_confirm()
        else:
            self.action_cancel()


class ClaudeStreamDialog(ModalScreen[dict[str, Any] | None]):
    """Floating modal that streams output from a Claude session.

    Shows a RichLog with live text / tool-use indicators, a status line,
    and a Cancel / Close button.
    """

    BINDINGS = [
        Binding("escape", "cancel_or_close", "Cancel/Close", show=False),
    ]

    DEFAULT_CSS = """
    ClaudeStreamDialog {
        align: center middle;
    }

    ClaudeStreamDialog #dialog {
        width: 90%;
        height: 80%;
        padding: 1 2;
        border: thick $accent;
        background: $surface;
    }

    ClaudeStreamDialog #title-label {
        text-style: bold;
        margin: 0 0 1 0;
    }

    ClaudeStreamDialog #status-label {
        color: $text-muted;
        margin: 0 0 1 0;
    }

    ClaudeStreamDialog #stream-log {
        height: 1fr;
        border: round $primary-background;
    }

    ClaudeStreamDialog .buttons {
        height: auto;
        margin: 1 0 0 0;
        align: center middle;
    }

    ClaudeStreamDialog .buttons Button {
        margin: 0 1;
    }
    """

    def __init__(
        self,
        title: str,
        prompt: str,
        cwd: str,
        on_result: Callable[[], dict[str, Any] | None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._title = title
        self._prompt = prompt
        self._cwd = cwd
        self._on_result = on_result
        self._session: Any = None
        self._finished = False
        self._result: dict[str, Any] | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(f"[bold]{self._title}[/bold]", id="title-label")
            yield Label("Running...", id="status-label")
            yield RichLog(highlight=True, wrap=True, markup=True, id="stream-log")
            with Grid(classes="buttons"):
                yield Button("Cancel", variant="error", id="cancel-btn")

    def on_mount(self) -> None:
        self.run_worker(self._run_stream(), exclusive=True)

    async def _run_stream(self) -> None:
        from womtrees.claude import (
            ClaudeCancelledError,
            ClaudeResultEvent,
            ClaudeTextEvent,
            ClaudeToolEvent,
            start_claude_session,
        )

        log = self.query_one("#stream-log", RichLog)
        status = self.query_one("#status-label", Label)

        self._session = start_claude_session(
            prompt=self._prompt,
            cwd=self._cwd,
        )

        try:
            async for event in self._session.events:
                if isinstance(event, ClaudeTextEvent):
                    log.write(event.text)
                elif isinstance(event, ClaudeToolEvent):
                    log.write(f"\n[dim]▶ Tool: {event.tool_name}[/dim]")
                elif isinstance(event, ClaudeResultEvent):
                    self._finished = True
                    cost = f" (${event.cost_usd:.4f})" if event.cost_usd else ""
                    if event.is_error:
                        status.update(f"[red]Error{cost}[/red]")
                    else:
                        status.update(f"[green]Done{cost}[/green]")
                    self._swap_to_close_button()
                    if self._on_result is not None:
                        try:
                            self._result = self._on_result()
                        except Exception:
                            pass
        except ClaudeCancelledError:
            status.update("[yellow]Cancelled[/yellow]")
            self._finished = True
            self._swap_to_close_button()
        except Exception as exc:
            status.update(f"[red]Error: {exc}[/red]")
            self._finished = True
            self._swap_to_close_button()

    def _swap_to_close_button(self) -> None:
        btn = self.query_one("#cancel-btn", Button)
        btn.label = "Close"
        btn.variant = "primary"
        btn.id = "close-btn"

    async def _do_cancel(self) -> None:
        if self._session is not None and not self._finished:
            status = self.query_one("#status-label", Label)
            status.update("[yellow]Cancelling...[/yellow]")
            await self._session.cancel()

    def action_cancel_or_close(self) -> None:
        if self._finished:
            self.dismiss(self._result)
        else:
            self.run_worker(self._do_cancel(), exclusive=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.run_worker(self._do_cancel(), exclusive=True)
        elif event.button.id == "close-btn":
            self.dismiss(self._result)


class HelpDialog(ModalScreen):
    """Help overlay showing keybindings."""

    BINDINGS = [("escape", "dismiss", "Close"), ("question_mark", "dismiss", "Close")]

    DEFAULT_CSS = """
    HelpDialog {
        align: center middle;
    }

    HelpDialog #dialog {
        width: 50;
        height: auto;
        padding: 1 2;
        border: thick $accent;
        background: $surface;
    }

    HelpDialog Button {
        margin: 1 0 0 0;
        width: 100%;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("[bold]Keybindings[/bold]")
            yield Label("")
            yield Label("h/Left    Previous column")
            yield Label("l/Right   Next column")
            yield Label("j/Down    Next card")
            yield Label("k/Up      Previous card")
            yield Label("Enter     Jump to tmux session")
            yield Label("s         Start a TODO item")
            yield Label("c         Create & launch")
            yield Label("t         Create TODO")
            yield Label("r         Move to review")
            yield Label("m         Merge into default branch")
            yield Label("p         Create PR via Claude")
            yield Label("d         Delete")
            yield Label("g         Toggle repo grouping")
            yield Label("a         Toggle all/repo view")
            yield Label("q         Quit")
            yield Label("")
            yield Button("Close", id="close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss()

    def action_dismiss(self) -> None:
        self.app.pop_screen()
