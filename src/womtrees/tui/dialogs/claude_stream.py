from __future__ import annotations

from collections.abc import Callable
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, RichLog


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
        self._finished = False
        self._cancelled = False
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
            ClaudeResultEvent,
            ClaudeTextEvent,
            ClaudeToolEvent,
            stream_claude_events,
        )

        log = self.query_one("#stream-log", RichLog)
        status = self.query_one("#status-label", Label)

        text_buf = ""

        try:
            async for event in stream_claude_events(
                prompt=self._prompt,
                cwd=self._cwd,
            ):
                if self._cancelled:
                    break
                if isinstance(event, ClaudeTextEvent):
                    text_buf += event.text
                    # Flush complete lines, keep partial tail in buffer
                    while "\n" in text_buf:
                        line, text_buf = text_buf.split("\n", 1)
                        log.write(line)
                elif isinstance(event, ClaudeToolEvent):
                    if text_buf:
                        log.write(text_buf)
                        text_buf = ""
                    detail = ""
                    inp = event.tool_input
                    if event.tool_name == "Bash" and inp.get("command"):
                        detail = f"  $ {inp['command']}"
                    elif event.tool_name == "Read" and inp.get("file_path"):
                        detail = f"  {inp['file_path']}"
                    elif event.tool_name == "Write" and inp.get("file_path"):
                        detail = f"  {inp['file_path']}"
                    elif event.tool_name == "Edit" and inp.get("file_path"):
                        detail = f"  {inp['file_path']}"
                    elif event.tool_name == "Glob" and inp.get("pattern"):
                        detail = f"  {inp['pattern']}"
                    elif event.tool_name == "Grep" and inp.get("pattern"):
                        detail = f"  /{inp['pattern']}/"
                    elif event.tool_name == "Skill" and inp.get("skill"):
                        detail = f"  /{inp['skill']}"
                    log.write(f"[dim]▶ {event.tool_name}{detail}[/dim]")
                elif isinstance(event, ClaudeResultEvent):
                    if text_buf:
                        log.write(text_buf)
                        text_buf = ""
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
            if text_buf:
                log.write(text_buf)
        except Exception as exc:
            status.update(f"[red]Error: {exc}[/red]")
            self._finished = True
            self._swap_to_close_button()

        if self._cancelled and not self._finished:
            status.update("[yellow]Cancelled[/yellow]")
            self._finished = True
            self._swap_to_close_button()

    def _swap_to_close_button(self) -> None:
        btn = self.query_one("#cancel-btn", Button)
        btn.label = "Close"
        btn.variant = "primary"

    def action_cancel_or_close(self) -> None:
        if self._finished:
            self.dismiss(self._result)
        else:
            self._cancelled = True

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            if self._finished:
                self.dismiss(self._result)
            else:
                self._cancelled = True
