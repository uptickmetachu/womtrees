"""Command palette provider for the womtrees TUI."""

from __future__ import annotations

from textual.command import Hit, Hits, Provider


class WorkItemCommands(Provider):
    """Provides card-context commands for the command palette."""

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        app = self.app

        from womtrees.tui.app import WomtreesApp
        from womtrees.tui.card import WorkItemCard

        if not isinstance(app, WomtreesApp):
            return

        card = app.last_focused_card
        is_work_item = isinstance(card, WorkItemCard)
        status = card.work_item.status if isinstance(card, WorkItemCard) else None

        commands: list[tuple[str, str, str]] = []

        # Card-context commands (require a highlighted WorkItemCard)
        if is_work_item:
            if status != "done":
                commands.append(
                    ("Git Actions", "Open git actions menu", "action_git_actions")
                )
            commands.append(
                ("Edit", "Edit work item name and branch", "action_edit_item")
            )
            commands.append(("Delete", "Delete work item", "action_delete_item"))

        # Always-available commands
        commands.append(("Create", "Create a new work item", "action_create_item"))
        commands.append(("Create TODO", "Create a new TODO item", "action_todo_item"))
        commands.append(
            (
                "Toggle group by repository",
                "Toggle repo grouping on/off",
                "action_toggle_grouping",
            )
        )
        commands.append(("Help", "Show help", "action_help"))

        for name, help_text, action in commands:
            score = matcher.match(name)
            if score > 0:
                yield Hit(
                    score,
                    matcher.highlight(name),
                    lambda a=action: (
                        app.run_action(a)
                        if a.startswith("action_")
                        else getattr(app, a)()
                    ),
                    help=help_text,
                )
