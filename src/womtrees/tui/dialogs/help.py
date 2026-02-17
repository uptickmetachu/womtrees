from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class HelpDialog(ModalScreen[None]):
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
            yield Label("e         Edit name/branch")
            yield Label("c         Create & launch")
            yield Label("t         Create TODO")
            yield Label("g         Git actions (merge/commit/rebase/push/pull)")
            yield Label("p         Create PR via Claude")
            yield Label("d         Delete")
            yield Label("q         Quit")
            yield Label("")
            yield Button("Close", id="close")

    def on_button_pressed(self, _event: Button.Pressed) -> None:
        self.dismiss()

    def action_dismiss(self, _result: object = None) -> None:  # type: ignore[override]
        self.app.pop_screen()
