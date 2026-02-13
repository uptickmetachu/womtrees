from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Grid, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, TextArea


class CreateDialog(ModalScreen[dict | None]):
    """Modal dialog for creating a new WorkItem."""

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

    CreateDialog #dialog Input, CreateDialog #dialog TextArea {
        margin: 0 0 1 0;
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

    def __init__(self, mode: str = "create", **kwargs) -> None:
        super().__init__(**kwargs)
        self.mode = mode  # "create" or "todo"

    def compose(self) -> ComposeResult:
        title = "Create & Launch" if self.mode == "create" else "Create TODO"
        with Vertical(id="dialog"):
            yield Label(f"[bold]{title}[/bold]")
            yield Label("Branch:")
            yield Input(placeholder="feat/my-feature", id="branch-input")
            yield Label("Prompt:")
            yield TextArea(id="prompt-input")
            with Grid(classes="buttons"):
                yield Button("Submit", variant="primary", id="submit")
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit":
            branch_input = self.query_one("#branch-input", Input)
            prompt_input = self.query_one("#prompt-input", TextArea)
            branch = branch_input.value.strip()
            prompt = prompt_input.text.strip() or None
            if branch:
                self.dismiss({"branch": branch, "prompt": prompt, "mode": self.mode})
            else:
                branch_input.focus()
        elif event.button.id == "cancel":
            self.dismiss(None)


class DeleteDialog(ModalScreen[bool]):
    """Confirmation dialog for deleting a WorkItem."""

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

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")


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
            yield Label("D         Move to done")
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
