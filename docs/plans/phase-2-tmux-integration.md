# Phase 2: Tmux Integration

## Goal

Add tmux session management to worktree lifecycle. After this phase, `wt start` and `wt create` spin up tmux sessions with a configurable pane layout. Users can attach/jump to sessions from the CLI.

## Prerequisites

- Phase 1 complete

## Config Additions

```toml
[tmux]
split = "vertical"       # vertical | horizontal
claude_pane = "left"     # left | right | top | bottom
```

## Data Model Changes

### WorkItem additions

| Field | Type | Notes |
|-------|------|-------|
| tmux_session | text | Nullable. Tmux session name |

## New File

### `tmux.py`

Thin wrapper around tmux subprocess calls.

#### `create_session(name, working_dir) -> str`

1. Sanitize session name (tmux doesn't allow `.` and `:`)
2. `tmux new-session -d -s <name> -c <working_dir>`
3. Return session name

#### `split_pane(session, direction, working_dir) -> str`

1. Map config direction to tmux flag: `vertical` -> `-h`, `horizontal` -> `-v`
2. `tmux split-window <flag> -t <session> -c <working_dir>`
3. Return pane id

#### `send_keys(session, pane, keys) -> None`

`tmux send-keys -t <session>:<pane> "<keys>" Enter`

#### `kill_session(name) -> None`

`tmux kill-session -t <name>`

#### `session_exists(name) -> bool`

Check if a tmux session exists. `tmux has-session -t <name>` returns 0 if it exists.

#### `attach(name) -> None`

If inside tmux: `tmux switch-client -t <name>`
If outside tmux: `tmux attach-session -t <name>`

#### `set_environment(session, key, value) -> None`

`tmux set-environment -t <session> <key> <value>`

Sets session-scoped environment variables. Used later for `WOMTREE_WORK_ITEM_ID`.

## CLI Changes

### `wt start <id>` — updated

1. Fetch WorkItem, verify status=`todo`
2. Call `create_worktree()`
3. Create tmux session named `<repo_name>/<sanitized_branch>`
4. Set tmux env: `WOMTREE_WORK_ITEM_ID=<id>`
5. The initial pane is the shell pane (right/bottom depending on config)
6. Split pane for Claude (left/top depending on config) — **leave empty for now**, Claude integration comes in Phase 3
7. Update WorkItem: status=`working`, `worktree_path`, `tmux_session`
8. Print: `Started #<id> in tmux session <session_name>`

### `wt create -b <branch> -p <prompt>` — updated

Same as `wt todo` + the updated `wt start`.

### `wt delete <id>` — updated

Add step: if `tmux_session` is set and session exists, `kill_session()`.

### New: `wt attach <id>`

1. Fetch WorkItem
2. Verify `tmux_session` is set
3. Call `attach(tmux_session)`

## Pane Layout Logic

Based on config `split` and `claude_pane`:

| split | claude_pane | Result |
|-------|-------------|--------|
| vertical | left | Claude left, shell right |
| vertical | right | Shell left, Claude right |
| horizontal | top | Claude top, shell bottom |
| horizontal | bottom | Shell top, Claude bottom |

The "first" pane created by `new-session` becomes the shell. The split pane becomes the Claude pane. If `claude_pane` is `left` or `top`, swap panes after splitting using `tmux swap-pane`.

## Error Handling

- If tmux is not installed: `Error: tmux is required. Install it with: brew install tmux`
- If session name already exists: append a numeric suffix
- If session creation fails: clean up worktree, report error
- Detect if running inside tmux (`$TMUX` env var) to choose attach vs switch-client

## Testing

- Unit tests for `tmux.py` — mock subprocess calls
- Integration tests: verify tmux session creation and pane layout in a real tmux (CI may need to skip these)
- Test attach behavior inside vs outside tmux
