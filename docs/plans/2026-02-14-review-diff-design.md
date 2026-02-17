# Review Diff Viewer — Design Document

**Date:** 2026-02-14
**Updated:** 2026-02-17
**Status:** Final

## Overview

A built-in diff viewer TUI for reviewing code changes with inline comments. Two-panel layout: file tree on the left, unified diff on the right. Uses Python's `difflib` for diffing and Pygments for syntax highlighting. Comments are copied to the clipboard on submit, with an option to send directly to Claude's tmux pane.

## Entry Points

- `wt review-diff [<id>]` — standalone CLI command, auto-detects work item from worktree context if no ID given
- Keybinding from the kanban board — opens the diff TUI on the selected card

## Diff Source

- **Default comparison:** Branch vs main (what a PR diff shows)
- **Flags:**
  - `--uncommitted` — working tree vs HEAD
  - `--base <ref>` — custom base ref
- **Engine:** Python `difflib.unified_diff()` — pure Python, no external dependencies
- **Syntax highlighting:** Pygments — highlight both file versions, then map highlighted lines onto diff output

## Architecture

### Layout

```
┌──────────────┬──────────────────────────────────────┐
│  File Tree   │  Unified Diff View                   │
│              │                                      │
│ ● cli.py    │  @@ -40,6 +40,8 @@                  │
│   db.py      │   def get_items():                   │
│   models.py  │  -    return query(...)              │
│              │  +    items = query(...)              │
│              │  +    return sorted(items)            │
│              │                                      │
│              │  ● Comment [L42-43]: rename this...  │
│              │                                      │
├──────────────┴──────────────────────────────────────┤
│  Status: 3 files changed │ 2 comments │ cli.py:42  │
└─────────────────────────────────────────────────────┘
```

- **Left panel:** Textual `Tree` widget listing changed files, `●` marker for files with comments
- **Right panel:** Custom scrollable diff widget with colored +/- lines, dual line numbers, and comment gutter markers
- **Status bar:** File count, comment count, current position

### New Files

| File | Purpose |
|------|---------|
| `src/womtrees/diff.py` | Runs `difflib.unified_diff()`, Pygments highlighting, produces `DiffFile` dataclasses |
| `src/womtrees/review.py` | Formats comments to markdown, copies to clipboard, optionally sends to Claude |
| `src/womtrees/tui/diff_app.py` | Standalone Textual app for the diff viewer |
| `src/womtrees/tui/diff_view.py` | Custom scrollable diff widget with vim nav, selection, comment markers |
| `src/womtrees/tui/comment_input.py` | Modal dialog for entering comment text |

### Data Model (dataclasses, not DB)

```python
@dataclass
class DiffLine:
    kind: Literal["added", "removed", "context", "hunk_header"]
    old_line_no: int | None   # line number in old file
    new_line_no: int | None   # line number in new file
    plain_text: str           # raw text (for difflib matching)
    highlighted: str          # Pygments ANSI-highlighted text

@dataclass
class DiffFile:
    path: str
    language: str | None      # detected from file extension
    lines: list[DiffLine]     # all diff lines (headers, context, changes)

@dataclass
class DiffResult:
    files: list[DiffFile]
    base_ref: str             # e.g. "main" or "HEAD"
    target_ref: str           # e.g. "working tree" or branch name

@dataclass
class ReviewComment:
    file: str
    start_line: int           # line number in the new file
    end_line: int
    comment_text: str
```

### Data Flow

1. `diff.py` gets list of changed files via `git diff --name-only <base>..<target>`
2. For each file: `git show <base>:<path>` and `git show <target>:<path>` to get both versions
3. Pygments highlights both versions (language detected from file extension)
4. `difflib.unified_diff()` on plain text to compute the diff
5. Each diff line is mapped back to its Pygments-highlighted version
6. Packaged into `DiffFile` dataclasses
7. `diff_view.py` renders the diff lines with +/- background coloring overlaid on syntax colors
8. User navigates, selects lines, adds comments — stored as in-memory `ReviewComment` list
9. On submit, `review.py` formats comments to markdown and copies to clipboard

## Interaction Design

### Navigation

| Key | Action |
|-----|--------|
| `j` / `↓` | Move cursor down one line in diff |
| `k` / `↑` | Move cursor up one line in diff |
| `J` / `K` | Jump to next/previous file (also selects in tree) |
| `]` / `[` | Jump to next/previous hunk |
| `Tab` | Toggle focus between file tree and diff view |
| `gg` / `G` | Top / bottom of current file's diff |
| `Ctrl+d` / `Ctrl+u` | Half-page down/up |

### Selection & Commenting

| Key | Action |
|-----|--------|
| `v` | Start/extend visual line selection |
| `Esc` | Cancel current selection |
| `c` | Open comment input for selected lines (or current line if no selection) |
| `n` / `N` | Jump to next/previous comment |
| `u` | Undo last comment (remove most recently added) |
| `x` | Delete comment under cursor |

### Actions

| Key | Action |
|-----|--------|
| `ctrl+s` | Submit — format comments, copy to clipboard |
| `S` | Submit + send to Claude's tmux pane |
| `q` | Quit |
| `?` | Help overlay |

### Visual Feedback

- Added lines: green background
- Removed lines: red background
- Context lines: default background
- Selected lines: bright highlight (vim visual mode style)
- Commented lines: `●` gutter marker, slightly different background tint
- Inline comment display: shown below the commented lines, dimmed/indented

### Comment Input

Press `c` to open a modal. Shows the file path + selected line range as context. Single TextArea for the comment text. `ctrl+s` to save, `Esc` to cancel.

## Submission & Clipboard

### Clipboard Format

```markdown
# Code Review

## src/womtrees/cli.py:42-47
Rename this variable — `x` is unclear, use `work_item_id`

## src/womtrees/db.py:15
This query is missing a WHERE clause for repo filtering

## src/womtrees/tui/board.py:88-95
This refresh logic will flicker. Batch the updates instead of refreshing per-card.
```

Minimal format — file path, line range, and comment. No code quoted; Claude reads the files itself.

### Submit Flows

**`ctrl+s` (clipboard only):**
1. Format all comments as markdown
2. Copy to system clipboard (`pbcopy` on macOS)
3. Flash notification: "Copied 3 comments to clipboard"
4. Stay in viewer

**`S` (clipboard + Claude):**
1. Same as above
2. Look up work item's active Claude session (most recent from `claude_sessions` table)
3. `tmux send-keys -t <pane>` to type: `Review my changes. Here are specific comments to address:` + paste clipboard + Enter
4. Exit viewer

### Edge Cases

- **No active Claude session:** Flash warning, clipboard copy still works
- **Multiple Claude sessions:** Use the most recent active one
- **No comments:** Flash "No comments to submit"

## Implementation Phases

### Phase 1 — Diff Engine (`diff.py`)
- Get changed files via `git diff --name-only`
- Retrieve file contents via `git show`
- Highlight both versions with Pygments
- Compute unified diff with `difflib.unified_diff()`
- Map diff lines to highlighted versions
- Package into `DiffFile`/`DiffLine` dataclasses
- Unit tests with fixture diffs

### Phase 2 — TUI Diff Viewer (`tui/diff_view.py`, `tui/diff_app.py`)
- Two-panel layout: Textual `Tree` (file list) + custom scrollable diff widget
- Render diff lines with Pygments syntax colors + diff background colors
- Vim navigation (j/k, J/K, ]/[, gg/G, Ctrl+d/u)
- File tree selection syncs with diff view
- Status bar with file count, position

### Phase 3 — Selection & Commenting (`tui/comment_input.py`)
- Visual line selection (v, Esc)
- Comment modal (c) with TextArea input, `ctrl+s` to save
- Gutter markers for commented lines
- Inline comment display below commented lines
- Comment navigation (n/N) and deletion (x)
- Undo last comment (u)
- In-memory list of `ReviewComment` objects

### Phase 4 — Submission (`review.py`) & CLI Integration
- Format comments as markdown
- Copy to clipboard via `pbcopy` (macOS)
- Optional Claude delivery via `tmux send-keys`
- `wt review-diff [<id>]` CLI command with `--uncommitted` and `--base` flags
- Kanban board integration (keybinding to open diff view on a card)
