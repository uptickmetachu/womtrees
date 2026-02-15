# womtrees 🐻

*Wombats for your worktrees.*

**womtrees** (`wt`) is a git worktree manager that burrows through your repos like a wombat through dirt — fast, focused, and slightly obsessive. It pairs git worktrees with tmux sessions and wraps them in a kanban-style TUI.

This is a personal workflow tool. It does one thing well: manage parallel workstreams across git worktrees with a terminal-native board. If that sounds like your vibe, welcome to the burrow.

## How it works

```
wt todo "fix the auth bug"        # Queue up a task 
wt create "add dark mode"         # Create and immediately start working
wt board                          # Open the kanban TUI
```

Each work item flows through: **todo** → **working** → **review** → **done**

The TUI gives you a kanban board with vim-style navigation, so you can move cards around, launch Claude Code sessions, merge branches, and rebase — all without leaving the terminal.


## Prerequisites

womtrees assumes you live in the terminal. You'll need:

- **Python 3.13+**
- **tmux** — every work item gets its own session
- **git** — obviously
- **gh** — GitHub CLI, for PR workflows
- **uv** — for running/developing

## Install

```bash
# Install the tool
uv tool install git+https://github.com/uptickmetachu/womtrees.git

# Install claude code hooks for session tracking
wt hook install

```

## Development

1. Download the repo


2. uv sync

```bash
uv run wt <command>       # Run during development
uv run pytest             # Tests
uv run ruff check .       # Lint
uv run ruff format .      # Format
uv run mypy src/          # Type check
```

