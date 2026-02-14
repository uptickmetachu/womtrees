# Session Resume Design

## Problem

When a Claude Code process exits (user quits, crash, OOM), the tmux pane remains alive but Claude is no longer running. The work item is stuck in working/input status with a dead session. Users must manually restart Claude in the correct pane.

## Solution

On attach (CLI `wt attach` or TUI Enter), detect dead Claude sessions and automatically relaunch with `claude --resume <session-id>`.

## Data Model

Add `claude_session_id TEXT` to `claude_sessions` table. This stores Claude Code's own session UUID (from hook stdin JSON), which the `--resume` flag needs.

Hook commands receive JSON on stdin from Claude Code containing `session_id`. The `_handle_hook` function reads stdin and stores it on every heartbeat.

## Detection

Check `is_pid_alive(session.pid)`. PID is already captured on every heartbeat via `os.getppid()`. No new detection code needed.

## Resume Flow

```
1. Look up WorkItem -> get tmux_session
2. Find active ClaudeSession for this work item
3. If session exists and NOT is_pid_alive(session.pid):
   a. Build: claude --resume <claude_session_id> [claude_args]
   b. tmux.send_keys(session.tmux_pane, cmd)
4. tmux.attach(session_name)
```

No state manipulation on resume — hooks fire naturally once Claude is alive and handle all transitions.

If `claude_session_id` is None (old session), fall back to `claude --continue`.

## Changes

| File | Change |
|---|---|
| models.py | Add `claude_session_id: str \| None` |
| db.py | Migration + CRUD update |
| cli.py | `_handle_hook` reads stdin; `wt attach` calls resume helper |
| tui/app.py | `action_jump` calls resume helper |
