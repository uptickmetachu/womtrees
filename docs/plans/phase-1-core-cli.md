# Phase 1: Core CLI & Worktree Management

## Goal

Build the foundation: config, SQLite storage, git worktree operations, and the core CLI commands. No tmux, no Claude, no TUI. After this phase, `wt` can create, list, and delete worktrees with proper state tracking.

## Data Model

### WorkItem

| Field | Type | Notes |
|-------|------|-------|
| id | integer | Primary key, autoincrement |
| repo_name | text | Derived from git remote or directory name |
| repo_path | text | Absolute path to the source repo |
| branch | text | Branch name |
| prompt | text | Nullable. The task description / Claude prompt |
| worktree_path | text | Nullable. Set when worktree is created |
| status | text | `todo`, `working`, `review`, `done` |
| created_at | text | ISO 8601 |
| updated_at | text | ISO 8601 |

### Config (`~/.config/womtrees/config.toml`)

```toml
[worktrees]
base_dir = "~/.local/share/womtrees"
```

## Project Setup

### pyproject.toml

```toml
[project]
name = "womtrees"
version = "0.1.0"
description = "Git worktree manager with tmux and Claude Code integration"
readme = "README.md"
requires-python = ">=3.13"
dependencies = [
    "click",
]

[project.scripts]
wt = "womtrees.cli:cli"
```

### File Structure

```
src/
└── womtrees/
    ├── __init__.py
    ├── cli.py          # Click command group
    ├── config.py       # TOML config loading/defaults
    ├── db.py           # SQLite connection, migrations, queries
    ├── models.py       # WorkItem dataclass
    └── worktree.py     # git worktree operations
```

## Config (`config.py`)

- Load from `~/.config/womtrees/config.toml`
- Create default config on first run if missing
- Expand `~` in paths
- Provide `get_config()` function that returns a Config dataclass

```python
@dataclass
class Config:
    base_dir: Path  # default: ~/.local/share/womtrees
```

## Database (`db.py`)

- SQLite at `<base_dir>/womtrees.db`
- Create tables on first connection if they don't exist
- Use a simple migration scheme: version table + sequential migrations
- All queries as plain functions, no ORM

### Schema

```sql
CREATE TABLE work_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_name TEXT NOT NULL,
    repo_path TEXT NOT NULL,
    branch TEXT NOT NULL,
    prompt TEXT,
    worktree_path TEXT,
    status TEXT NOT NULL DEFAULT 'todo',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX idx_work_items_repo ON work_items(repo_name);
CREATE INDEX idx_work_items_status ON work_items(status);
```

### Functions

- `create_work_item(repo_name, repo_path, branch, prompt, status) -> WorkItem`
- `get_work_item(id) -> WorkItem`
- `list_work_items(repo_name=None, status=None) -> list[WorkItem]`
- `update_work_item(id, **fields) -> WorkItem`
- `delete_work_item(id) -> None`

## Models (`models.py`)

```python
@dataclass
class WorkItem:
    id: int
    repo_name: str
    repo_path: str
    branch: str
    prompt: str | None
    worktree_path: str | None
    status: str  # todo, working, review, done
    created_at: str
    updated_at: str
```

## Worktree Operations (`worktree.py`)

### `create_worktree(repo_path, branch, base_dir) -> Path`

1. Sanitize branch name for filesystem: replace `/` with `-`, strip special chars
2. Compute worktree path: `<base_dir>/<repo_name>/<sanitized_branch>/`
3. Run `git worktree add <path> <branch>` (create branch if it doesn't exist with `-b`)
4. If `.womtrees.json` exists in source repo:
   - Copy files listed in `copy` array from source repo to worktree
   - Run commands listed in `setup` array sequentially, with `$ROOT_WORKTREE_PATH` set to source repo
5. Return the worktree path

### `remove_worktree(worktree_path) -> None`

1. Run `git worktree remove <path>`
2. Run `git worktree prune`

### `load_womtrees_json(repo_path) -> dict | None`

Parse `.womtrees.json` from repo root if it exists.

## CLI Commands (`cli.py`)

### `wt todo -b <branch> -p <prompt>`

1. Detect current repo (name + path) from cwd
2. Validate branch name
3. Insert WorkItem with status=`todo`
4. Print: `Created TODO #<id>: <branch>`

### `wt create -b <branch> -p <prompt>`

Phase 1 version (no tmux/Claude yet):
1. Same as `wt todo` but with status=`working`
2. Call `create_worktree()`
3. Update WorkItem with `worktree_path`
4. Print: `Created worktree #<id>: <path>`

### `wt start <id>`

Phase 1 version:
1. Fetch WorkItem, verify status=`todo`
2. Call `create_worktree()`
3. Update WorkItem: status=`working`, set `worktree_path`
4. Print: `Started #<id>: <path>`

### `wt list [--all]`

1. Detect current repo from cwd (if in a repo)
2. If `--all` or not in a repo: list all WorkItems
3. If in a repo: list WorkItems for current repo only
4. Print table: `ID | Status | Repo | Branch | Prompt (truncated)`

### `wt status [<id>]`

1. If id given: show full details for that WorkItem
2. If no id: summary counts by status (context-aware like `list`)

### `wt delete <id> [--force]`

1. Fetch WorkItem
2. If status is `working` and no `--force`: refuse with message
3. If status is `done` or `--force`: prompt for confirmation
4. If worktree_path exists: call `remove_worktree()`
5. Delete from SQLite
6. Print: `Deleted #<id>`

### `wt review <id>`

1. Fetch WorkItem, verify status=`working`
2. Update status to `review`

### `wt done <id>`

1. Fetch WorkItem, verify status=`review`
2. Update status to `done`

### `wt config [--edit]`

1. No args: print current config
2. `--edit`: open config file in `$EDITOR`

## Context Detection

A shared utility used by multiple commands:

```python
def get_current_repo() -> tuple[str, str] | None:
    """Return (repo_name, repo_path) if cwd is inside a git repo."""
```

- Run `git rev-parse --show-toplevel` to get repo path
- Derive repo name from the directory name or git remote

## Error Handling

- If not in a git repo and command requires it: clear error message
- If WorkItem not found: `Error: WorkItem #<id> not found`
- If invalid state transition: `Error: Cannot start #<id>, status is <status> (expected todo)`
- If worktree creation fails: clean up partial state, report git error

## Testing

- Unit tests for `db.py` using in-memory SQLite
- Unit tests for `worktree.py` using a temporary git repo
- Integration tests for CLI commands using Click's `CliRunner`
- Test `.womtrees.json` copy and setup execution
