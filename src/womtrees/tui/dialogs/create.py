from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, TextArea


class CreateDialog(ModalScreen[dict | None]):
    """Modal dialog for creating a new WorkItem."""

    BINDINGS = [
        Binding("ctrl+s,ctrl+enter", "submit", "Submit", show=True, priority=True),
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
        options: list[tuple[str, str]] = []
        default_value: object = Select.BLANK
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
                yield Button("Submit (ctrl+s)", variant="primary", id="submit")
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
            repo_path = str(repo_select.value)
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
