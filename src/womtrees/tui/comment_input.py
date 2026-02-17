"""Modal dialog for entering a review comment."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, TextArea


class CommentInputDialog(ModalScreen[str | None]):
    """Modal for entering a review comment on selected lines."""

    BINDINGS = [
        Binding("ctrl+s", "submit", "Submit", show=True, priority=True),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    DEFAULT_CSS = """
    CommentInputDialog {
        align: center middle;
    }

    CommentInputDialog #dialog {
        width: 70;
        height: auto;
        padding: 1 2;
        border: thick $accent;
        background: $surface;
    }

    CommentInputDialog #dialog Label {
        margin: 1 0 0 0;
    }

    CommentInputDialog #dialog TextArea {
        height: 8;
        margin: 0 0 1 0;
    }

    CommentInputDialog .buttons {
        height: auto;
        margin: 1 0 0 0;
        align: center middle;
    }

    CommentInputDialog .buttons Button {
        margin: 0 1;
    }
    """

    def __init__(
        self, context: str = "", initial_text: str = "", **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        self._comment_context = context
        self._initial_text = initial_text

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("[bold]Add Comment[/bold]")
            yield Label(f"[dim]{self._comment_context}[/dim]")
            yield Label("Comment:")
            yield TextArea(id="comment-input")
            with Grid(classes="buttons"):
                yield Button("Submit (ctrl+s)", variant="primary", id="submit")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        ta = self.query_one("#comment-input", TextArea)
        if self._initial_text:
            ta.load_text(self._initial_text)
        ta.focus()

    def action_submit(self) -> None:
        text = self.query_one("#comment-input", TextArea).text.strip()
        if not text:
            self.query_one("#comment-input", TextArea).focus()
            return
        self.dismiss(text)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit":
            self.action_submit()
        elif event.button.id == "cancel":
            self.action_cancel()
