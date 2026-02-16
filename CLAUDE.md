# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

womtrees (`wt`) — Git worktree manager with tmux and Claude Code integration. CLI + TUI kanban board.

## Stack
- Python 3.13+, Click (CLI), Textual (TUI), SQLite (storage)
- Config: `~/.config/womtrees/config.toml` | Data: `~/.local/share/womtrees/`
- Entry point: `wt = womtrees.cli:cli`

## Commands
```
uv run wt <command>      # Run CLI during development
uv run pytest            # Run tests
uv run pytest tests/test_cli.py::test_name  # Run a single test
uv run ruff check .      # Lint
uv run ruff format .     # Format
uv run mypy src/         # Type check
```

## Rules
- Keep CLI imports lean — never import Textual at module level; lazy-import only in `wt board`
- No ORM — plain SQLite queries in `db.py`
- All subprocess calls (git, tmux) go through dedicated wrapper modules (`worktree.py`, `tmux.py`)
- Design docs in `docs/plans/` — implement in phase order (1→2→3→4)
- Always implement features via AB testing and R-E-D (RED) format for worktree, terminal etc.
- Use `ruff` for formatting and linting. Run `ruff check` and `ruff format` before committing.
- Use `mypy` for type checking. All new code should include type hints.
- Update this `CLAUDE.md` when significant structural changes are made (new modules, changed architecture, new commands, modified state machines, DB migrations, etc.).

## Architecture

**Data flow:** CLI command → `services/` (business logic) → `db.py` (SQLite) → `worktree.py`/`tmux.py` (subprocess) → `claude.py` (hooks)

**Key modules in `src/womtrees/`:**
- `cli/` — Click commands split across `items.py` (CRUD), `info.py` (list/status/attach), `hooks.py`, `admin.py`, `utils.py`
- `services/workitem.py` — Business logic for work item lifecycle (create, start, review, done, delete, merge, edit). Raises typed exceptions (`WorkItemNotFoundError`, `InvalidStateError`, `DuplicateBranchError`, `OpenPullRequestError`). CLI and TUI are thin callers.
- `services/github.py` — GitHub PR detection/management via `gh` CLI. Exceptions: `PRNotFoundError`, `GitHubUnavailableError`.
- `db.py` — All DB access; plain SQL, WAL mode, migration system (`SCHEMA_VERSION`), returns dataclasses. Use `connection()` context manager (or `get_connection()` for long-lived connections).
- `models.py` — `WorkItem`, `ClaudeSession`, `PullRequest`, `GitStats` dataclasses
- `worktree.py` — Git worktree create/remove/merge/list; repo detection
- `tmux.py` — Tmux session/pane management; send-keys, attach, split
- `claude.py` — Context detection (reads `$TMUX_PANE`, resolves work item from tmux env)
- `config.py` — TOML config loading with typed `Config` dataclass
- `tui/app.py` — Textual `WomtreesApp` with kanban board, vim-style navigation, dialog callbacks
- `tui/dialogs/` — Modal dialogs split into individual files: `create.py`, `edit.py`, `delete.py`, `merge.py`, `rebase.py`, `auto_rebase.py`, `claude_stream.py`, `help.py`. Re-exported from `tui/dialogs/__init__.py`.

**TUI stable widget pattern (anti-flicker):** Cards and column widgets use update-in-place to avoid flicker from destroy/recreate cycles:
- All cards have stable DOM IDs (`id=f"item-{work_item.id}"`, `id=f"unmanaged-{branch}"`). Never create throwaway cards without IDs.
- Use `update_data()` + `_rebuild_children()` to update card content — replaces child `Static`s only, card widget stays in DOM so focus is preserved.
- `KanbanColumn.card_map` (dict keyed by widget ID) and `_repo_header_map` track all mounted widgets. On refresh, diff against incoming data: remove gone widgets, call `update_data()` on existing ones, `mount()` only truly new ones.
- **Never call `widget.remove()` then `self.mount(widget)` on the same widget** — Textual's `remove()` is async and invalidates the widget before the synchronous `mount()` runs, causing blank panels.
- Repo headers are kept in DOM across refreshes (tracked in `_repo_header_map`). Only add/remove when the repo set changes.
- `_first_update` flag gates the initial mount (everything in order) vs subsequent diffs (only new widgets mounted).
- `_check_refresh()` uses a 1-second debounce timer so rapid heartbeats coalesce into a single `_refresh_board()` call.
- Focus save/restore is unnecessary — cards stay in DOM so focus is preserved automatically.

**TUI dialog key bindings:** `ctrl+s` is the universal submit/confirm shortcut across all dialogs. Use `Binding("ctrl+s", ..., priority=True)` — priority bindings fire before focused widgets consume the event. Note: `ctrl+enter` is not a valid terminal key (terminals send it as plain `enter`/`ctrl+m`). Button labels include the shortcut hint, e.g. `"Submit (ctrl+s)"`.

**State machines:**
- WorkItem: `todo` → `working` → `input`/`review` → `done`
- ClaudeSession: `working` → `waiting` → `done`
- Hook commands (`wt hook heartbeat|input|stop|mark-done`) drive state transitions

**DB schema:** Three tables — `work_items` (repo, branch, worktree path, tmux session, status), `claude_sessions` (FK to work_item, pane, pid, state, prompt), `pull_requests` (FK to work_item, number, status, url). Migrations in `db.py` `MIGRATIONS` dict.

## Testing Patterns
- CLI tests use `click.testing.CliRunner`
- Patch `womtrees.db.get_connection` with a temp DB factory (the `connection()` context manager calls `get_connection()` internally, so one patch covers both)
- Patch `womtrees.cli.utils.get_current_repo` to isolate context
- Service functions that use `create_worktree`/`remove_worktree` — patch at `womtrees.services.workitem.create_worktree`
- See existing fixtures in `tests/` for patterns

## Claude Hook System
- `wt hook install` registers hooks in `~/.claude/settings.json` (UserPromptSubmit, PostToolUse, Notification, Stop)
- Hooks call back into `wt hook heartbeat|input|stop` to update session state
- `claude.py` detects context via tmux pane env vars → resolves work item ID
