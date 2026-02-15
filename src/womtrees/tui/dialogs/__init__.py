"""TUI modal dialogs — each dialog in its own submodule."""

from womtrees.tui.dialogs.auto_rebase import AutoRebaseDialog
from womtrees.tui.dialogs.claude_stream import ClaudeStreamDialog
from womtrees.tui.dialogs.create import CreateDialog
from womtrees.tui.dialogs.delete import DeleteDialog
from womtrees.tui.dialogs.edit import EditDialog
from womtrees.tui.dialogs.git_actions import GitActionsDialog
from womtrees.tui.dialogs.help import HelpDialog
from womtrees.tui.dialogs.merge import MergeDialog
from womtrees.tui.dialogs.rebase import RebaseDialog

__all__ = [
    "AutoRebaseDialog",
    "ClaudeStreamDialog",
    "CreateDialog",
    "DeleteDialog",
    "EditDialog",
    "GitActionsDialog",
    "HelpDialog",
    "MergeDialog",
    "RebaseDialog",
]
