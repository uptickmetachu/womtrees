# womtrees (wt)

Git worktree manager with tmux and Claude Code integration. CLI + TUI kanban board.

## Stack
- Python 3.13+, Click (CLI), Textual (TUI), SQLite (storage)
- Config: `~/.config/womtrees/config.toml` | Data: `~/.local/share/womtrees/`
- Entry point: `wt = womtrees.cli:cli`

## Rules
- Keep CLI imports lean — never import Textual at module level; lazy-import only in `wt board`
- No ORM — plain SQLite queries in `db.py`
- All subprocess calls (git, tmux) go through dedicated wrapper modules (`worktree.py`, `tmux.py`)
- Design docs in `docs/plans/` — implement in phase order (1→2→3→4)

## Commands
```
uv run wt <command>      # Run CLI during development
uv run pytest            # Run tests
```


## Feature work
Always implement things via AB testing and R-E-D (RED)  format for worktree, terminal etc.

