"""Tests for review submission."""

from __future__ import annotations

from unittest.mock import patch

from womtrees.diff import ReviewComment
from womtrees.review import copy_to_clipboard, format_comments


def test_format_comments_empty():
    """Empty comments list produces empty string."""
    assert format_comments([]) == ""


def test_format_comments_single():
    """Single comment formats correctly."""
    comments = [
        ReviewComment(
            file="a.py",
            start_line=5,
            end_line=5,
            comment_text="Fix this",
            source_start=42,
            source_end=42,
        )
    ]
    result = format_comments(comments)
    assert "# Code Review" in result
    assert "## a.py#L42" in result
    assert "Fix this" in result


def test_format_comments_range():
    """Comment with line range formats as start-end."""
    comments = [
        ReviewComment(
            file="b.py",
            start_line=10,
            end_line=15,
            comment_text="Refactor",
            source_start=100,
            source_end=105,
        )
    ]
    result = format_comments(comments)
    assert "## b.py#L100-L105" in result


def test_format_comments_multiple():
    """Multiple comments produce multiple sections."""
    comments = [
        ReviewComment(file="a.py", start_line=1, end_line=1, comment_text="First"),
        ReviewComment(file="b.py", start_line=5, end_line=8, comment_text="Second"),
    ]
    result = format_comments(comments)
    assert result.count("##") == 2
    assert "First" in result
    assert "Second" in result


def test_copy_to_clipboard_macos():
    """On macOS, uses pbcopy."""
    with (
        patch("womtrees.review.platform") as mock_platform,
        patch("womtrees.review.subprocess") as mock_sub,
    ):
        mock_platform.system.return_value = "Darwin"
        copy_to_clipboard("test text")
        mock_sub.run.assert_called_once_with(
            ["pbcopy"], input="test text", text=True, check=True
        )


def test_copy_to_clipboard_linux():
    """On Linux, uses xclip."""
    with (
        patch("womtrees.review.platform") as mock_platform,
        patch("womtrees.review.subprocess") as mock_sub,
    ):
        mock_platform.system.return_value = "Linux"
        copy_to_clipboard("test text")
        mock_sub.run.assert_called_once_with(
            ["xclip", "-selection", "clipboard"],
            input="test text",
            text=True,
            check=True,
        )
