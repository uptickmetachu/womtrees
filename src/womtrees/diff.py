"""Diff engine — computes file diffs with syntax highlighting.

Pure data layer. No Textual imports. Uses difflib for diffing and Pygments
for syntax highlighting.
"""

from __future__ import annotations

import difflib
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class DiffLine:
    """A single line in a unified diff."""

    kind: Literal["added", "removed", "context", "hunk_header"]
    old_line_no: int | None  # line number in old file
    new_line_no: int | None  # line number in new file
    plain_text: str  # raw text without diff prefix
    highlighted: str  # Pygments ANSI-highlighted text


@dataclass
class DiffFile:
    """Diff data for a single file."""

    path: str
    language: str | None
    lines: list[DiffLine] = field(default_factory=list)


@dataclass
class DiffResult:
    """Top-level diff result containing all changed files."""

    files: list[DiffFile]
    base_ref: str
    target_ref: str


@dataclass
class ReviewComment:
    """A review comment attached to a line range in a file."""

    file: str
    start_line: int  # diff view index (0-based, for cursor matching)
    end_line: int  # inclusive
    comment_text: str
    source_start: int = 0  # real file line number (for display)
    source_end: int = 0  # real file line number (for display)
    diff_content: str = ""  # joined plain_text of commented DiffLines (content anchor)


def _git(repo_path: str, *args: str) -> str:
    """Run a git command and return stdout. Raises on failure."""
    result = subprocess.run(
        ["git", "-C", repo_path, *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def list_changed_files(repo_path: str, base: str, target: str) -> list[str]:
    """List files changed between base and target refs."""
    output = _git(repo_path, "diff", "--name-only", f"{base}...{target}")
    return [f for f in output.strip().splitlines() if f]


def list_uncommitted_files(repo_path: str) -> list[str]:
    """List files with uncommitted changes plus untracked.

    Returns empty list if the repo path doesn't support these queries
    (e.g. main repo when changes are in a worktree).
    """
    files: list[str] = []
    try:
        output = _git(repo_path, "diff", "--name-only", "HEAD")
        files = [f for f in output.strip().splitlines() if f]
    except subprocess.CalledProcessError:
        pass
    # Also include untracked files
    try:
        untracked = _git(repo_path, "ls-files", "--others", "--exclude-standard")
        for f in untracked.strip().splitlines():
            if f and f not in files:
                files.append(f)
    except subprocess.CalledProcessError:
        pass
    return files


def get_file_at_ref(repo_path: str, ref: str, path: str) -> str | None:
    """Get file contents at a specific git ref. Returns None if file doesn't exist."""
    try:
        return _git(repo_path, "show", f"{ref}:{path}")
    except subprocess.CalledProcessError:
        return None


def _detect_language(path: str) -> str | None:
    """Detect language from file extension using Pygments."""
    from pygments.lexers import get_lexer_for_filename
    from pygments.util import ClassNotFound

    try:
        lexer = get_lexer_for_filename(path)
        name: str = lexer.name  # type: ignore[attr-defined]
        return name
    except ClassNotFound:
        return None


def _highlight_lines(text: str, language: str | None) -> list[str]:
    """Highlight text with Pygments, returning one ANSI string per line.

    Falls back to plain text if language is unknown.
    """
    if not language or not text:
        return text.splitlines()

    from pygments import highlight as pyg_highlight
    from pygments.formatters import Terminal256Formatter
    from pygments.lexers import get_lexer_by_name
    from pygments.util import ClassNotFound

    try:
        lexer = get_lexer_by_name(language)
    except ClassNotFound:
        return text.splitlines()

    formatter = Terminal256Formatter(style="monokai")
    highlighted = pyg_highlight(text, lexer, formatter)
    # Split into lines, stripping trailing reset if present
    lines = highlighted.splitlines()
    return lines


def _parse_unified_diff(
    unified: list[str],
    old_highlighted: list[str],
    new_highlighted: list[str],
) -> list[DiffLine]:
    """Parse unified diff lines, mapping back to highlighted source lines.

    Args:
        unified: Lines from difflib.unified_diff (including --- +++ headers)
        old_highlighted: Pygments-highlighted lines of the old file
        new_highlighted: Pygments-highlighted lines of the new file

    Returns:
        List of DiffLine objects with line numbers and highlighting.
    """
    result: list[DiffLine] = []
    old_idx = 0
    new_idx = 0

    # Skip the --- and +++ header lines from difflib
    lines_iter = iter(unified)
    for line in lines_iter:
        if line.startswith("@@"):
            # Parse hunk header: @@ -old_start,old_count +new_start,new_count @@
            match = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)", line)
            if match:
                old_idx = int(match.group(1)) - 1  # 0-based
                new_idx = int(match.group(2)) - 1
                result.append(
                    DiffLine(
                        kind="hunk_header",
                        old_line_no=None,
                        new_line_no=None,
                        plain_text=line,
                        highlighted=line,
                    )
                )
            continue

        if line.startswith("---") or line.startswith("+++"):
            continue

        if line.startswith("-"):
            plain = line[1:]
            hl = old_highlighted[old_idx] if old_idx < len(old_highlighted) else plain
            result.append(
                DiffLine(
                    kind="removed",
                    old_line_no=old_idx + 1,
                    new_line_no=None,
                    plain_text=plain,
                    highlighted=hl,
                )
            )
            old_idx += 1
        elif line.startswith("+"):
            plain = line[1:]
            hl = new_highlighted[new_idx] if new_idx < len(new_highlighted) else plain
            result.append(
                DiffLine(
                    kind="added",
                    old_line_no=None,
                    new_line_no=new_idx + 1,
                    plain_text=plain,
                    highlighted=hl,
                )
            )
            new_idx += 1
        elif line.startswith(" "):
            plain = line[1:]
            hl = new_highlighted[new_idx] if new_idx < len(new_highlighted) else plain
            result.append(
                DiffLine(
                    kind="context",
                    old_line_no=old_idx + 1,
                    new_line_no=new_idx + 1,
                    plain_text=plain,
                    highlighted=hl,
                )
            )
            old_idx += 1
            new_idx += 1

    return result


def compute_diff_for_file(
    repo_path: str,
    file_path: str,
    base_ref: str,
    target_ref: str,
    *,
    uncommitted: bool = False,
) -> DiffFile:
    """Compute diff for a single file between two refs.

    If uncommitted=True, target_ref is ignored and the working tree is used.
    """
    language = _detect_language(file_path)

    old_text = get_file_at_ref(repo_path, base_ref, file_path) or ""
    if uncommitted:
        wt_path = Path(repo_path) / file_path
        new_text = wt_path.read_text() if wt_path.exists() else ""
    else:
        new_text = get_file_at_ref(repo_path, target_ref, file_path) or ""

    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)

    old_highlighted = _highlight_lines(old_text, language)
    new_highlighted = _highlight_lines(new_text, language)

    unified = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
            lineterm="",
        )
    )

    diff_lines = _parse_unified_diff(unified, old_highlighted, new_highlighted)
    return DiffFile(path=file_path, language=language, lines=diff_lines)


def list_diff_files(
    repo_path: str,
    base_ref: str | None = None,
    target_ref: str | None = None,
    *,
    uncommitted: bool = False,
) -> DiffResult:
    """List changed files without computing full diffs.

    Returns a DiffResult with stub DiffFile objects (path only, no lines).
    Use compute_diff_for_file() to lazily load the full diff for a file.

    Both modes diff against the working tree:
    - uncommitted: HEAD vs working tree
    - branch: base_ref vs working tree (committed + uncommitted changes)
    """
    from womtrees.worktree import get_default_branch

    if base_ref is None:
        base_ref = get_default_branch(repo_path)
    if target_ref is None:
        target_ref = "HEAD"

    if uncommitted:
        files = list_uncommitted_files(repo_path)
        label_target = "working tree"
        actual_base = "HEAD"
    else:
        # Branch mode: committed changes + uncommitted changes
        files = list_changed_files(repo_path, base_ref, target_ref)
        uncommitted_files = list_uncommitted_files(repo_path)
        seen = set(files)
        for f in uncommitted_files:
            if f not in seen:
                files.append(f)
                seen.add(f)
        label_target = "working tree"
        actual_base = base_ref

    diff_files = [DiffFile(path=f, language=_detect_language(f)) for f in files]

    return DiffResult(
        files=diff_files,
        base_ref=actual_base,
        target_ref=label_target,
    )


def compute_diff(
    repo_path: str,
    base_ref: str | None = None,
    target_ref: str | None = None,
    *,
    uncommitted: bool = False,
) -> DiffResult:
    """Compute diff for all changed files.

    Args:
        repo_path: Path to the git repository
        base_ref: Base reference (default: auto-detect default branch)
        target_ref: Target reference (default: HEAD)
        uncommitted: If True, compare HEAD vs working tree;
                     otherwise base_ref vs working tree (committed + uncommitted)
    """
    from womtrees.worktree import get_default_branch

    if base_ref is None:
        base_ref = get_default_branch(repo_path)
    if target_ref is None:
        target_ref = "HEAD"

    if uncommitted:
        files = list_uncommitted_files(repo_path)
        label_target = "working tree"
        actual_base = "HEAD"
    else:
        files = list_changed_files(repo_path, base_ref, target_ref)
        uncommitted_files = list_uncommitted_files(repo_path)
        seen = set(files)
        for f in uncommitted_files:
            if f not in seen:
                files.append(f)
                seen.add(f)
        label_target = "working tree"
        actual_base = base_ref

    diff_files: list[DiffFile] = []
    for f in files:
        # Both modes always diff against working tree
        diff_file = compute_diff_for_file(
            repo_path,
            f,
            actual_base,
            target_ref,
            uncommitted=True,
        )
        if diff_file.lines:
            diff_files.append(diff_file)

    return DiffResult(
        files=diff_files,
        base_ref=actual_base,
        target_ref=label_target,
    )
