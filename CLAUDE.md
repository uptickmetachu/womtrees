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

**Data flow:** CLI command → `db.py` (SQLite) → `worktree.py`/`tmux.py` (subprocess) → `claude.py` (hooks)

**Key modules in `src/womtrees/`:**
- `cli.py` — Click command group; all commands + `hook` subgroup for Claude integration
- `db.py` — All DB access; plain SQL, WAL mode, migration system (`SCHEMA_VERSION`), returns dataclasses
- `models.py` — `WorkItem` and `ClaudeSession` dataclasses
- `worktree.py` — Git worktree create/remove/merge/list; repo detection
- `tmux.py` — Tmux session/pane management; send-keys, attach, split
- `claude.py` — Context detection (reads `$TMUX_PANE`, resolves work item from tmux env)
- `config.py` — TOML config loading with typed `Config` dataclass
- `tui/` — Textual app: `WomtreesApp` → `KanbanBoard` → `KanbanColumn` → `WorkItemCard` + `dialogs.py`

**State machines:**
- WorkItem: `todo` → `working` → `input`/`review` → `done`
- ClaudeSession: `working` → `waiting` → `done`
- Hook commands (`wt hook heartbeat|input|stop|mark-done`) drive state transitions

**DB schema:** Two main tables — `work_items` (repo, branch, worktree path, tmux session, status) and `claude_sessions` (FK to work_item, pane, pid, state, prompt). Migrations in `db.py` `MIGRATIONS` dict.

## Testing Patterns
- CLI tests use `click.testing.CliRunner`
- Patch `db.get_connection()` with a temp in-memory DB
- Patch `worktree.get_current_repo()` to isolate context
- See existing fixtures in `tests/` for patterns

## Claude Hook System
- `wt hook install` registers hooks in `~/.claude/settings.json` (UserPromptSubmit, PostToolUse, Notification, Stop)
- Hooks call back into `wt hook heartbeat|input|stop` to update session state
- `claude.py` detects context via tmux pane env vars → resolves work item ID

