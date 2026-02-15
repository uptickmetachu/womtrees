from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label


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
