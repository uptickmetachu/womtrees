"""Review submission — formats comments and copies to clipboard."""

from __future__ import annotations

import platform
import subprocess

from womtrees.diff import ReviewComment


def format_comments(comments: list[ReviewComment]) -> str:
    """Format review comments as markdown."""
    if not comments:
        return ""

    sections: list[str] = ["# Code Review", ""]
    for comment in comments:
        if comment.source_start == comment.source_end:
            header = f"## {comment.file}#L{comment.source_start}"
        else:
            header = f"## {comment.file}#L{comment.source_start}-L{comment.source_end}"
        sections.append(header)
        sections.append(comment.comment_text)
        sections.append("")

    return "\n".join(sections)


def copy_to_clipboard(text: str) -> None:
    """Copy text to system clipboard."""
    system = platform.system()
    if system == "Darwin":
        cmd = ["pbcopy"]
    else:
        # Try xclip first, fall back to xsel
        cmd = ["xclip", "-selection", "clipboard"]

    try:
        subprocess.run(cmd, input=text, text=True, check=True)
    except FileNotFoundError:
        if system != "Darwin":
            # Fallback to xsel
            subprocess.run(
                ["xsel", "--clipboard", "--input"],
                input=text,
                text=True,
                check=True,
            )


def send_to_claude(pane: str, markdown: str) -> None:
    """Send review comments to a Claude tmux pane."""
    from womtrees.tmux import send_keys

    message = "Review my changes. Here are specific comments to address:\n\n" + markdown
    send_keys(pane, message)
