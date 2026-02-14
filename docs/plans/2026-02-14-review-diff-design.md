# Review Diff Viewer — Design Document

**Date:** 2026-02-14
**Status:** Draft

## Overview

A built-in diff viewer TUI for reviewing Claude's uncommitted changes with inline comments. Uses difftastic's JSON output for AST-aware semantic diffs, rendered in a Textual widget with vim-style line selection and commenting. On submit, writes a review file and sends a prompt to Claude's tmux pane.

## Entry Points

- `wt review-diff <id>` — standalone CLI command, takes a work item ID
- Keybinding from the kanban board — opens the diff TUI on the selected card

## Diff Source

- **Comparison:** Working tree vs HEAD (uncommitted changes in the worktree)
- **Engine:** `difft --display json` for structured semantic diff data
- **Fallback:** `git diff --unified` parsed into the same data model when difft is not installed (one-time suggestion to install difftastic)

## Architecture

### New Files

| File | Purpose |
|------|---------|
| `src/womtrees/diff.py` | Runs difft/git-diff, parses output into structured dataclasses |
| `src/womtrees/review.py` | Writes review file, sends prompt to Claude's tmux pane |
| `src/womtrees/tui/diff_app.py` | Textual app for the review-diff TUI |
| `src/womtrees/tui/diff_view.py` | Scrollable diff widget with syntax highlighting, selection, comments |
| `src/womtrees/tui/comment_input.py` | Modal for entering a comment on a selected range |

### Data Model (dataclasses, not DB)

```python
@dataclass
class DiffChange:
    kind: Literal["added", "removed", "unchanged"]
    lhs_line_no: int | None
    rhs_line_no: int | None
    content: str

@dataclass
class DiffHunk:
    changes: list[DiffChange]

@dataclass
class DiffFile:
    path: str
    language: str | None
    hunks: list[DiffHunk]

@dataclass
class ReviewComment:
    file: str
    start_line: int
    end_line: int
    comment_text: str
```

### Data Flow

1. `diff.py` runs `difft --display json <worktree>` and parses JSON into `DiffFile` objects
2. `diff_view.py` renders each `DiffFile` as a scrollable Textual widget with Rich syntax highlighting
3. User navigates, selects lines, adds comments — stored as in-memory `ReviewComment` list
4. On submit, `review.py` writes comments to temp file and sends prompt to Claude

## Interaction Design

### Navigation

| Key | Action |
|-----|--------|
| `j` / `↓` | Move cursor down one line |
| `k` / `↑` | Move cursor up one line |
| `J` / `K` | Jump to next/previous file |
| `{` / `}` | Jump to next/previous hunk |
| `gg` / `G` | Top / bottom of diff |
| `Ctrl+d/u` | Half-page down/up |

### Selection & Commenting

| Key | Action |
|-----|--------|
| `v` | Start/extend visual line selection |
| `V` | Select entire hunk under cursor |
| `Esc` | Cancel current selection |
| `c` | Open comment input for current selection |
| `n` | Jump to next comment |
| `x` | Delete comment under cursor |

### Actions

| Key | Action |
|-----|--------|
| `S` | Submit all comments — write review file, send to Claude |
| `q` | Quit without submitting |
| `?` | Help overlay |

### Visual Feedback

- Selected lines: highlight background (vim visual mode style)
- Commented lines: gutter marker (`●`)
- Status bar: file count, comment count, current position

### Comment Input

Press `c` to open a modal. Shows the selected range (file + lines) for context. Text input for the comment. Enter to save, Esc to cancel.

## Review File & Claude Delivery

### Review File Format

Written to `/tmp/womtrees-review-<work_item_id>.md`:

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

### Delivery to Claude

1. Write review file to `/tmp/womtrees-review-<work_item_id>.md`
2. Look up the work item's active Claude session (most recent active from `claude_sessions` table)
3. `tmux send-keys -t <pane>` to type: `Review my changes. Read /tmp/womtrees-review-<id>.md for specific comments to address.` + Enter

### Edge Cases

- **No active Claude session:** Print the review file path and instruct user to pass it manually
- **Multiple Claude sessions:** Use the most recent active one

## Implementation Phases

### Phase 1 — Diff Engine (`diff.py`)
- Run `difft --display json` against a worktree
- Parse JSON into `DiffFile`/`DiffHunk`/`DiffChange` dataclasses
- Fallback to `git diff --unified` parsing
- Unit tests with fixture diffs

### Phase 2 — TUI Diff Viewer (`tui/diff_view.py`, `tui/diff_app.py`)
- Scrollable Textual widget rendering `DiffFile` objects with Rich syntax highlighting
- Vim navigation (j/k, J/K, {/}, gg/G, Ctrl+d/u)
- Status bar with file count, position

### Phase 3 — Selection & Commenting (`tui/comment_input.py`)
- Visual line selection (v, V, Esc)
- Comment modal (c), gutter markers for commented lines
- Comment navigation (n) and deletion (x)
- In-memory list of `ReviewComment` objects

### Phase 4 — Review Submission (`review.py`) & CLI Integration
- Write comments to `/tmp/womtrees-review-<id>.md`
- Send prompt to Claude's tmux pane via `tmux send-keys`
- `wt review-diff <id>` CLI command
- Kanban board integration (keybinding to open diff view on a card)
