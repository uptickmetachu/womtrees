# Phase 4: Textual TUI Kanban Board

## Goal

Build the Textual-based kanban board that provides a real-time overview of all WorkItems and Claude sessions. After this phase, `wt board` opens a full interactive dashboard.

## Prerequisites

- Phases 1-3 complete

## Dependencies

Add to `pyproject.toml`:

```toml
dependencies = [
    "click",
    "textual",
]
```

Textual is only imported when `wt board` is called (lazy import in `cli.py`).

## File Structure

```
src/womtrees/tui/
├── __init__.py
├── app.py          # WomtreesApp — main Textual application
├── board.py        # KanbanBoard — the 4-column layout widget
├── column.py       # KanbanColumn — a single status column
├── card.py         # WorkItemCard / ClaudeSessionCard widgets
└── dialogs.py      # CreateDialog, DeleteDialog, ConfirmDialog
```

## Architecture

### `WomtreesApp` (`app.py`)

The main Textual `App` subclass.

**Responsibilities:**
- Initialize DB connection
- Determine context (current repo or global)
- Set up the board with data
- Handle global keybindings
- Periodic refresh of data (poll SQLite every 2-3 seconds for status changes)

**Constructor args:**
- `show_all: bool` — global view vs context-aware
- `group_by_repo: bool` — default True

### `KanbanBoard` (`board.py`)

A horizontal container holding 4 `KanbanColumn` widgets.

**Layout:**
```
┌──────────┬──────────┬──────────┬──────────┐
│   TODO   │ WORKING  │  REVIEW  │   DONE   │
│          │          │          │          │
│          │          │          │          │
└──────────┴──────────┴──────────┴──────────┘
```

**Responsibilities:**
- Distribute WorkItems into correct columns based on status
- Group cards by repo within each column (when enabled)
- Handle navigation between columns (left/right arrow keys)
- Refresh data on timer

### `KanbanColumn` (`column.py`)

A vertical scrollable container for one status column.

**Display:**
- Column header with status name and count
- Repo group headers (when grouping enabled)
- Cards within each group

**Navigation:**
- Up/down arrow keys move between cards within the column
- Track which card is currently focused/selected

### Cards (`card.py`)

#### `WorkItemCard`

Represents a WorkItem with its associated Claude sessions.

```
┌─────────────────────────┐
│ #1 feat-auth            │
│ "Implement OAuth flow"  │
│                         │
│ C1: working      12m    │
│ C2: waiting ●     3m    │
└─────────────────────────┘
```

**Fields displayed:**
- WorkItem id + branch name
- Prompt (truncated to ~40 chars)
- List of Claude sessions with state + time-in-state
- Visual indicator for `waiting` state (needs human attention)

**Styling:**
- Border color based on WorkItem status
- Highlight when focused/selected
- Waiting sessions get an attention indicator (filled circle or similar)

#### `UnmanagedCard`

Represents an unmanaged Claude session (no WorkItem).

```
┌─────────────────────────┐
│ main (unmanaged)        │
│ C3: working      45m    │
└─────────────────────────┘
```

Simpler card — no prompt, no WorkItem id. Grouped under repo with "(unmanaged)" label.

### Dialogs (`dialogs.py`)

#### `CreateDialog`

Modal for creating a new WorkItem from the TUI.

**Fields:**
- Branch name (text input)
- Prompt (text area)
- Action: Create (immediate launch) or Todo (queue)

#### `DeleteDialog`

Confirmation modal for deletion.

- Shows WorkItem details
- If status is `working`: warn that `--force` is required, show confirmation
- If status is `done`: simple confirmation

## Keybindings

| Key | Action | Context |
|-----|--------|---------|
| `h` / `Left` | Move to previous column | Global |
| `l` / `Right` | Move to next column | Global |
| `j` / `Down` | Move to next card | Within column |
| `k` / `Up` | Move to previous card | Within column |
| `Enter` | Jump to tmux session/pane | On a card |
| `s` | Start selected TODO | On a TODO card |
| `c` | Open Create dialog | Global |
| `t` | Open Todo dialog | Global |
| `r` | Move to REVIEW | On a WORKING card |
| `D` | Move to DONE | On a REVIEW card |
| `d` | Delete with confirmation | On any card |
| `g` | Toggle repo grouping | Global |
| `a` | Toggle all/context view | Global |
| `q` | Quit | Global |
| `?` | Show help overlay | Global |

## Data Flow

### Initial Load

1. App starts, reads config
2. Detect current repo context (if applicable)
3. Query SQLite: all WorkItems + all ClaudeSessions
4. Group by status → columns
5. Within columns, group by repo (if enabled)
6. Render board

### Periodic Refresh

Every 2-3 seconds:
1. Re-query SQLite for updated data
2. Diff with current state
3. Update only changed cards (avoid full re-render flicker)
4. Preserve current selection/focus

### Action: Jump to Session (`Enter`)

1. Get selected card
2. If WorkItemCard: get the first Claude session's tmux pane, or the tmux session itself
3. If UnmanagedCard: get the Claude session's tmux pane
4. Suspend Textual app
5. Run `tmux switch-client -t <session>:<pane>`
6. When user returns (detaches or switches back), Textual resumes

### Action: Start (`s`)

1. Get selected WorkItem (must be TODO)
2. Call worktree creation + tmux setup (same as `wt start`)
3. Update DB
4. Card moves from TODO to WORKING on next refresh

### Action: Create (`c`)

1. Open CreateDialog
2. User fills in branch + prompt
3. On submit: create WorkItem + worktree + tmux (same as `wt create`)
4. New card appears in WORKING

### Action: Delete (`d`)

1. Open DeleteDialog with WorkItem details
2. On confirm: run deletion logic (same as `wt delete`)
3. Card removed on next refresh

## Status Bar

Bottom of the screen, always visible:

```
┌───────────────────────────────────────────────────────────────────┐
│ [s]tart [d]elete [r]eview [D]one [Enter]jump [g]group [?]help   │
│ myrepo | 2 todo | 3 working | 1 review | 5 done | 2 unmanaged   │
└───────────────────────────────────────────────────────────────────┘
```

- Top line: available actions
- Bottom line: summary counts, current repo context

## Textual CSS

Use Textual's CSS system for layout and theming:

- Columns use `1fr` widths (equal sizing)
- Cards have borders, padding, and margin
- Selected card gets highlighted border
- Status-based color coding:
  - TODO: dim/grey
  - WORKING: blue
  - REVIEW: yellow
  - DONE: green
  - Unmanaged: italic label
- Waiting Claude sessions: bold/attention color (orange or red)

## Error Handling

- If tmux is not running: show warning banner, disable jump functionality
- If SQLite is locked during refresh: skip that refresh cycle, retry next
- If a tmux session referenced by a card no longer exists: show "session lost" indicator on the card
- If creating/deleting fails: show error in a notification toast

## Testing

- Unit tests for individual widgets using Textual's test framework (`async with app.run_test()`)
- Test keybinding actions trigger correct DB operations
- Test data grouping logic (by repo, toggle on/off)
- Test periodic refresh picks up external changes
- Snapshot tests for card rendering
