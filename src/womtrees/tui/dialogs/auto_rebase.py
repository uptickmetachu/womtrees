from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class AutoRebaseDialog(ModalScreen[bool]):
    """Prompt dialog offering to use Claude to auto-rebase a branch."""

    BINDINGS = [
        Binding("ctrl+s,ctrl+enter", "confirm", "Confirm", show=True, priority=True),
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
                yield Button("Auto-rebase (ctrl+s)", variant="error", id="confirm")
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
