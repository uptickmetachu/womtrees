# Tmux Status Bar Integration

## Goal

Show waiting Claude sessions in the tmux status bar so you always know when sessions need attention, without opening the TUI.

## Design

### `wt status --tmux` flag

Add a `--tmux` flag to the existing `wt status` command. When set, output a compact one-liner for tmux's `status-right`.

**Output format:**
- Zero waiting: `wt: 0`
- Some waiting: `wt: N waiting [branch1, branch2, +M]`
- Branch names truncated to fit ~60 chars total. Overflow shown as `+N`.

### `wt hook install` extension

Extend `install_global_hooks()` in `claude.py` to also configure tmux:
- Append `#(wt status --tmux)` to `status-right` in `~/.tmux.conf`
- Set `status-interval 5` for responsive updates
- Idempotent: skip if `wt status --tmux` already present
- Preserve existing `status-right` content by prepending `#(wt status --tmux) | ` to it
- Create `~/.tmux.conf` if it doesn't exist
- Reload tmux config if tmux is running

### Files to change

1. `src/womtrees/cli/info.py` — Add `--tmux` flag to `status` command
2. `src/womtrees/claude.py` — Add `configure_tmux_status_bar()`, call from `install_global_hooks()`
3. `src/womtrees/cli/hooks.py` — Update `install` command output to mention tmux
4. Tests for `wt status --tmux` output and tmux.conf manipulation

### What this does NOT do

- No new DB tables or migrations
- No new dependencies
- No TUI changes
- No new state machines
