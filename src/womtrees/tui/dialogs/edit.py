from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, TextArea


class EditDialog(ModalScreen[dict | None]):
    """Modal dialog for editing a WorkItem's name, branch, and prompt."""

    BINDINGS = [
        Binding("ctrl+enter", "submit", "Submit", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    DEFAULT_CSS = """
    EditDialog {
        align: center middle;
    }

    EditDialog #dialog {
        width: 75;
        height: auto;
        padding: 1 2;
        border: thick $accent;
        background: $surface;
    }

    EditDialog #dialog Label {
        margin: 1 0 0 0;
    }

    EditDialog #dialog Input {
        margin: 0 0 1 0;
    }

    EditDialog #dialog TextArea {
        margin: 0 0 1 0;
    }

    EditDialog .buttons {
        height: auto;
        margin: 1 0 0 0;
        align: center middle;
    }

    EditDialog .buttons Button {
        margin: 0 1;
    }
    """

    def __init__(
        self,
        item_name: str | None,
        item_branch: str,
        item_prompt: str | None = None,
        show_prompt: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.item_name = item_name or ""
        self.item_branch = item_branch
        self.item_prompt = item_prompt or ""
        self.show_prompt = show_prompt

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("[bold]Edit Work Item[/bold]")
            yield Label("Name:")
            yield Input(value=self.item_name, id="name-input")
            yield Label("Branch:")
            yield Input(value=self.item_branch, id="branch-input")
            if self.show_prompt:
                yield Label("Prompt:")
                yield TextArea(self.item_prompt, id="prompt-input")
            with Grid(classes="buttons"):
                yield Button("Save", variant="primary", id="submit")
                yield Button("Cancel", id="cancel")

    def action_submit(self) -> None:
        name = self.query_one("#name-input", Input).value.strip() or None
        branch = self.query_one("#branch-input", Input).value.strip()
        if not branch:
            self.query_one("#branch-input", Input).focus()
            return
        result: dict[str, str | None] = {"name": name, "branch": branch}
        if self.show_prompt:
            prompt_text = self.query_one("#prompt-input", TextArea).text.strip()
            result["prompt"] = prompt_text or None
        self.dismiss(result)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit":
            self.action_submit()
        elif event.button.id == "cancel":
            self.action_cancel()
