# Phase 3: Claude Code Integration

## Goal

Add Claude Code session tracking, automatic detection, and status updates via Claude Code hooks. After this phase, Claude sessions are tracked in the kanban data model, and their status is updated automatically.

## Prerequisites

- Phase 1 and Phase 2 complete

## Data Model Changes

### New table: `claude_sessions`

| Field | Type | Notes |
|-------|------|-------|
| id | integer | Primary key, autoincrement |
| work_item_id | integer | Nullable. FK to work_items. Null = unmanaged |
| repo_name | text | Detected from git remote/cwd |
| repo_path | text | Absolute path |
| branch | text | Current branch |
| tmux_session | text | Tmux session name |
| tmux_pane | text | Tmux pane id |
| pid | integer | Claude Code process PID |
| state | text | `working`, `waiting`, `done` |
| prompt | text | Nullable. Initial prompt if launched via wt |
| created_at | text | ISO 8601 |
| updated_at | text | ISO 8601 |

```sql
CREATE TABLE claude_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_item_id INTEGER REFERENCES work_items(id),
    repo_name TEXT NOT NULL,
    repo_path TEXT NOT NULL,
    branch TEXT NOT NULL,
    tmux_session TEXT NOT NULL,
    tmux_pane TEXT NOT NULL,
    pid INTEGER,
    state TEXT NOT NULL DEFAULT 'working',
    prompt TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX idx_claude_sessions_work_item ON claude_sessions(work_item_id);
CREATE INDEX idx_claude_sessions_state ON claude_sessions(state);
```

### DB Functions

- `create_claude_session(...) -> ClaudeSession`
- `get_claude_session(id) -> ClaudeSession`
- `list_claude_sessions(work_item_id=None, repo_name=None, state=None) -> list[ClaudeSession]`
- `update_claude_session(id, **fields) -> ClaudeSession`
- `delete_claude_session(id) -> None`
- `find_claude_session(tmux_session, tmux_pane) -> ClaudeSession | None`

## New File: `claude.py`

### Hook Installation

Claude Code hooks are configured globally in `~/.claude/hooks.json` (or equivalent). The hooks call `wt hook` commands.

#### `install_global_hooks() -> None`

Write/merge into Claude Code's hook config:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "",
        "command": "wt hook heartbeat"
      }
    ],
    "Stop": [
      {
        "matcher": "",
        "command": "wt hook stop"
      }
    ]
  }
}
```

Provide a `wt setup` command that installs these hooks.

### Session Detection

#### `detect_context() -> dict`

Gather context from the environment when a hook fires:

- `WOMTREE_WORK_ITEM_ID` from tmux env → work_item_id (nullable)
- `TMUX_PANE` env var → tmux pane
- `tmux display-message -p '#S'` → tmux session name
- `git rev-parse --show-toplevel` → repo path
- `git remote` / directory name → repo name
- `git branch --show-current` → branch
- PID of the calling Claude Code process

## CLI: Hook Commands

Internal commands called by Claude Code hooks. These must be extremely fast — minimal imports, direct SQLite writes.

### `wt hook heartbeat`

Called on `PostToolUse`. Indicates Claude is actively working.

1. Detect context (tmux session, pane, repo, branch, work_item_id)
2. Find existing ClaudeSession by (tmux_session, tmux_pane)
3. If exists: update `state=working`, `updated_at=now`
4. If not exists: create new ClaudeSession with `state=working`

### `wt hook stop`

Called on `Stop`. Indicates Claude has stopped and is waiting for input.

1. Detect context
2. Find existing ClaudeSession by (tmux_session, tmux_pane)
3. If exists: update `state=waiting`, `updated_at=now`
4. If not exists: create new ClaudeSession with `state=waiting`

### `wt hook done`

Manually mark a session as done. Called by user or automation.

1. Find ClaudeSession
2. Update `state=done`

## CLI Changes

### `wt start <id>` — updated

After creating tmux session and panes:

1. In the Claude pane: `tmux send-keys "claude" Enter`
2. Wait briefly for Claude to initialize
3. Pipe the prompt: `tmux send-keys "<prompt>" Enter`
4. Create a ClaudeSession record linked to the WorkItem

### `wt create -b <branch> -p <prompt>` — updated

Same as `wt todo` + updated `wt start`.

### `wt list` — updated

Include Claude session info in output:

```
ID | Status  | Repo    | Branch    | Claude Sessions
1  | working | myrepo  | feat-auth | C1: working, C2: waiting (3m)
2  | todo    | myrepo  | feat-api  | -
```

### `wt attach <id>` — updated

Accept optional `--session <claude_session_id>` to jump to a specific Claude pane.

### New: `wt setup`

1. Install global Claude Code hooks
2. Print confirmation

### New: `wt sessions [--all]`

List all Claude sessions. Context-aware like `wt list`.

```
Session | WorkItem | Repo   | Branch    | State   | Age
C1      | #1       | myrepo | feat-auth | working | 12m
C2      | #1       | myrepo | feat-auth | waiting | 3m
C3      | -        | myrepo | main      | working | 45m
```

## Auto-Detection Flow

When a user manually opens Claude in any tmux session:

1. Claude starts → first tool use triggers `PostToolUse` hook
2. Hook calls `wt hook heartbeat`
3. `heartbeat` detects tmux context, checks for `WOMTREE_WORK_ITEM_ID`
4. If env var present: creates ClaudeSession linked to that WorkItem
5. If env var absent: creates unmanaged ClaudeSession (work_item_id=null)
6. Session now appears in `wt list`, `wt sessions`, and the TUI

No manual registration needed. Any Claude Code instance running inside tmux is automatically tracked.

## Stale Session Cleanup

Claude sessions can become stale if Claude exits without triggering the Stop hook (crash, kill -9, etc.).

- On `wt list` / `wt sessions` / TUI load: check if the PID is still alive
- If PID is dead and state != `done`: mark as `done`, update `updated_at`
- Optionally: periodic cleanup of sessions older than a configurable threshold

## Error Handling

- If tmux is not running when hook fires: silently exit (don't break Claude)
- If SQLite is locked: retry with short backoff (hooks may fire concurrently)
- Hook commands must never produce stdout/stderr that would interfere with Claude — all output goes to a log file at `<base_dir>/hooks.log`

## Testing

- Unit tests for `claude.py` — mock subprocess and environment
- Test hook commands with mock tmux env vars
- Test auto-detection flow: simulate heartbeat → creates session
- Test stale session detection with mock PIDs
