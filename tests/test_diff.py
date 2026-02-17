"""Tests for the diff engine."""

from __future__ import annotations

from unittest.mock import patch

from womtrees.diff import (
    MAX_DIFF_LINES,
    MAX_FILE_SIZE,
    DiffFile,
    DiffLine,
    ReviewComment,
    _highlight_lines,
    _is_binary,
    _parse_unified_diff,
    compute_diff_for_file,
    list_changed_files,
)


def test_parse_unified_diff_basic():
    """Test parsing a simple unified diff."""
    unified = [
        "--- a/test.py",
        "+++ b/test.py",
        "@@ -1,3 +1,4 @@",
        " line1",
        "-line2",
        "+line2_modified",
        "+line3_new",
        " line3",
    ]
    old_hl = ["line1", "line2", "line3"]
    new_hl = ["line1", "line2_modified", "line3_new", "line3"]

    result = _parse_unified_diff(unified, old_hl, new_hl)

    assert len(result) == 6  # hunk_header + context + removed + 2 added + context
    assert result[0].kind == "hunk_header"
    assert result[1].kind == "context"
    assert result[1].old_line_no == 1
    assert result[1].new_line_no == 1
    assert result[2].kind == "removed"
    assert result[2].old_line_no == 2
    assert result[2].new_line_no is None
    assert result[3].kind == "added"
    assert result[3].old_line_no is None
    assert result[3].new_line_no == 2
    assert result[4].kind == "added"
    assert result[4].new_line_no == 3
    assert result[5].kind == "context"
    assert result[5].old_line_no == 3
    assert result[5].new_line_no == 4


def test_parse_unified_diff_empty():
    """Empty diff produces no lines."""
    result = _parse_unified_diff([], [], [])
    assert result == []


def test_parse_unified_diff_uses_highlighted():
    """Highlighted versions should be used when available."""
    unified = [
        "--- a/f.py",
        "+++ b/f.py",
        "@@ -1,1 +1,1 @@",
        "-old",
        "+new",
    ]
    old_hl = ["OLD_HIGHLIGHTED"]
    new_hl = ["NEW_HIGHLIGHTED"]

    result = _parse_unified_diff(unified, old_hl, new_hl)
    assert result[1].highlighted == "OLD_HIGHLIGHTED"
    assert result[2].highlighted == "NEW_HIGHLIGHTED"


def test_highlight_lines_unknown_language():
    """Unknown language returns plain text lines."""
    text = "line1\nline2"
    result = _highlight_lines(text, None)
    assert result == ["line1", "line2"]


def test_highlight_lines_python():
    """Python highlighting produces some output."""
    text = "def foo():\n    pass"
    result = _highlight_lines(text, "Python")
    assert len(result) == 2
    # Should contain ANSI escape codes
    assert any("\x1b[" in line for line in result)


def test_list_changed_files():
    """Test listing changed files between refs."""
    with patch("womtrees.diff._git", return_value="a.py\nb.py\n"):
        result = list_changed_files("/repo", "main", "HEAD")
    assert result == ["a.py", "b.py"]


def test_list_changed_files_empty():
    """Empty output returns empty list."""
    with patch("womtrees.diff._git", return_value=""):
        result = list_changed_files("/repo", "main", "HEAD")
    assert result == []


def test_compute_diff_for_file():
    """Test computing diff for a single file."""
    old_content = "line1\nline2\nline3\n"
    new_content = "line1\nmodified\nline3\nextra\n"

    def mock_git(repo, *args):
        cmd = args[0] if args else ""
        if cmd == "show":
            ref_path = args[1]
            if ref_path.startswith("base:"):
                return old_content
            return new_content
        return ""

    with patch("womtrees.diff._git", side_effect=mock_git):
        result = compute_diff_for_file("/repo", "test.txt", "base", "target")

    assert isinstance(result, DiffFile)
    assert result.path == "test.txt"
    assert len(result.lines) > 0
    kinds = [l.kind for l in result.lines]
    assert "added" in kinds or "removed" in kinds


def test_review_comment_dataclass():
    """ReviewComment stores file, line range, and text."""
    c = ReviewComment(file="a.py", start_line=5, end_line=10, comment_text="Fix this")
    assert c.file == "a.py"
    assert c.start_line == 5
    assert c.end_line == 10
    assert c.comment_text == "Fix this"


# -- Binary / large file filtering tests --


def test_is_binary_detects_null_bytes():
    """Binary detection via null bytes in strings and bytes."""
    assert _is_binary("hello\x00world") is True
    assert _is_binary(b"hello\x00world") is True
    assert _is_binary("hello world") is False
    assert _is_binary(b"hello world") is False


def test_compute_diff_skips_binary_old_file():
    """Diff returns empty lines when old file is binary."""
    binary_content = "binary\x00content"
    new_content = "clean text\n"

    def mock_git(repo, *args):
        cmd = args[0] if args else ""
        if cmd == "show":
            ref_path = args[1]
            if ref_path.startswith("base:"):
                return binary_content
            return new_content
        return ""

    with patch("womtrees.diff._git", side_effect=mock_git):
        result = compute_diff_for_file("/repo", "test.bin", "base", "target")

    assert result.lines == []


def test_compute_diff_skips_binary_new_file():
    """Diff returns empty lines when new file is binary."""
    old_content = "clean text\n"
    binary_content = "binary\x00content"

    def mock_git(repo, *args):
        cmd = args[0] if args else ""
        if cmd == "show":
            ref_path = args[1]
            if ref_path.startswith("base:"):
                return old_content
            return binary_content
        return ""

    with patch("womtrees.diff._git", side_effect=mock_git):
        result = compute_diff_for_file("/repo", "test.bin", "base", "target")

    assert result.lines == []


def test_compute_diff_skips_oversized_file():
    """Diff returns empty lines when file exceeds MAX_FILE_SIZE."""
    big_content = "x" * (MAX_FILE_SIZE + 1)

    def mock_git(repo, *args):
        cmd = args[0] if args else ""
        if cmd == "show":
            return big_content
        return ""

    with patch("womtrees.diff._git", side_effect=mock_git):
        result = compute_diff_for_file("/repo", "big.txt", "base", "target")

    assert result.lines == []


def test_compute_diff_skips_oversized_diff():
    """Diff returns empty lines when unified diff exceeds MAX_DIFF_LINES."""
    # Generate enough lines to exceed the limit
    old_lines = [f"old_line_{i}\n" for i in range(MAX_DIFF_LINES)]
    new_lines = [f"new_line_{i}\n" for i in range(MAX_DIFF_LINES)]
    old_content = "".join(old_lines)
    new_content = "".join(new_lines)

    def mock_git(repo, *args):
        cmd = args[0] if args else ""
        if cmd == "show":
            ref_path = args[1]
            if ref_path.startswith("base:"):
                return old_content
            return new_content
        return ""

    with patch("womtrees.diff._git", side_effect=mock_git):
        result = compute_diff_for_file("/repo", "huge.txt", "base", "target")

    assert result.lines == []
