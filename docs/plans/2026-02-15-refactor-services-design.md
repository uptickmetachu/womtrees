# Refactor: Service Layer, DB Cleanup, TUI Decomposition

## Goals

1. **Service layer** — shared business logic callable from both CLI and TUI, eliminating code duplication
2. **Typed exception handling** — domain-specific exceptions with clear error contracts (no new dependencies)
3. **DB connection cleanup** — context manager to eliminate manual `conn.close()` boilerplate
4. **TUI decomposition** — split `dialogs.py` into one file per dialog

## Decisions

- **DB pattern:** Keep `get_connection()` as-is + add a `@contextmanager` wrapper for auto-close (no singleton — safer for Textual threading)
- **Error model:** Python exceptions — extend existing typed exceptions (no `result` library, no `ErrorKind` enum)
- **Services:** One service file — `services/workitem.py` (merge with existing, add full lifecycle)
- **TUI:** Split `dialogs.py` into `tui/dialogs/` directory. Keep `app.py` as single file — action methods become thin after service extraction.
- **Skip:** `services/session.py` (hooks are CLI-only, simple), `services/git.py` (wraps functions already in `worktree.py`), `tui/actions.py` + `tui/refresh.py` (free functions taking `app` is just methods with extra steps)

---

## 1. Error Model

Extend the existing typed exception pattern in `services/workitem.py`. No new files, no new dependencies.

**Existing exceptions (keep as-is):**
```python
class DuplicateBranchError(Exception): ...
class OpenPullRequestError(Exception): ...
```

**New exceptions to add in `services/workitem.py`:**
```python
class WorkItemNotFoundError(Exception):
    """Raised when a work item ID does not exist."""
    def __init__(self, item_id: int) -> None:
        self.item_id = item_id
        super().__init__(f"Work item #{item_id} not found.")

class InvalidStateError(Exception):
    """Raised when a state transition is not allowed."""
    def __init__(self, item_id: int, current: str, target: str) -> None:
        self.item_id = item_id
        self.current = current
        self.target = target
        super().__init__(
            f"Cannot move #{item_id} from '{current}' to '{target}'."
        )
```

**Keep existing `RebaseRequiredError` in `worktree.py`** — it belongs with the git operations.

**CLI consumption (same pattern as today, but catching service exceptions):**
```python
try:
    item = workitem.start_work_item(conn, item_id, config)
    click.echo(f"Started #{item.id}: {item.name}")
except WorkItemNotFoundError as e:
    raise click.ClickException(str(e))
except InvalidStateError as e:
    raise click.ClickException(str(e))
```

**TUI consumption:**
```python
try:
    item = workitem.start_work_item(conn, item_id, config)
    self.notify(f"Started {item.name}")
except (WorkItemNotFoundError, InvalidStateError) as e:
    self.notify(str(e), severity="error")
```

---

## 2. DB Connection: Context Manager

Keep `get_connection()` returning a fresh connection (current behavior). Add a context manager to eliminate `conn.close()` boilerplate. This is safer than a singleton for Textual's threading model.

**Add to `db.py`** (~5 lines):
```python
from contextlib import contextmanager
from collections.abc import Iterator

@contextmanager
def connection(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Context manager for DB access. Auto-closes on exit."""
    conn = get_connection(db_path)
    try:
        yield conn
    finally:
        conn.close()
```

**Before (current pattern — easy to leak on exception):**
```python
conn = get_connection()
try:
    item = get_work_item(conn, item_id)
    # ... work ...
except ValueError as e:
    conn.close()
    raise click.ClickException(str(e))
finally:
    conn.close()
```

**After:**
```python
with db.connection() as conn:
    item = workitem.start_work_item(conn, item_id, config)
    click.echo(f"Started #{item.id}")
```

**Write transactions use SQLite's built-in `with conn:`:**
```python
with db.connection() as conn:
    with conn:  # BEGIN → auto-commit on success, rollback on error
        conn.execute("INSERT INTO work_items ...", ...)
        conn.execute("UPDATE ...", ...)
```

**Testing:** Same as today — patch `db.get_connection()` with temp in-memory DB. The context manager wraps it transparently.

---

## 3. Service Layer

### `services/workitem.py` (~200 lines)

Merge with the existing file (which has `edit_work_item`, `DuplicateBranchError`, `OpenPullRequestError`). Add the full work item lifecycle. This is the highest-value change — it eliminates the duplication between `cli/items.py:_start_work_item` and `tui/app.py:action_start_item`.

```python
"""Work item lifecycle operations — shared by CLI and TUI."""

# Exceptions
class WorkItemNotFoundError(Exception): ...
class InvalidStateError(Exception): ...
class DuplicateBranchError(Exception): ...  # existing
class OpenPullRequestError(Exception): ...  # existing

# Lifecycle functions — all take conn as first parameter
def create_work_item(conn, repo: str, name: str, prompt: str | None = None) -> WorkItem
def start_work_item(conn, item_id: int, config: Config) -> WorkItem
    # Creates worktree, tmux session, launches claude, creates ClaudeSession, updates status
    # Extracted from cli/items.py:_start_work_item
def review_work_item(conn, item_id: int) -> WorkItem
def done_work_item(conn, item_id: int) -> WorkItem
def delete_work_item(conn, item_id: int) -> None
def edit_work_item(conn, item: WorkItem, *, name=None, branch=None) -> bool  # existing
def merge_work_item(conn, item_id: int) -> WorkItem
def list_work_items(conn, repo: str | None = None, status: str | None = None) -> list[WorkItem]
def get_work_item(conn, item_id: int) -> WorkItem  # raises WorkItemNotFoundError
```

**Key extraction: `start_work_item`** — currently ~70 lines duplicated between CLI and TUI:
- Creates worktree via `worktree.create_worktree()`
- Creates tmux session + split pane via `tmux.create_session()` / `tmux.split()`
- Sends claude command to pane
- Creates ClaudeSession record + sets `WOMTREE_WORK_ITEM_ID` env var
- Updates WorkItem status → `working`

After extraction, both CLI and TUI call the same function.

### `services/github.py` (~120 lines)

GitHub integration — owns all `gh` CLI interaction AND DB coordination. Absorbs the existing `github.py` root module so there's one place for all GitHub logic.

The existing `github.py` (root module, 53 lines) contains `detect_pr()` which calls `gh pr list`. This gets merged into `services/github.py` as a private helper. The root `github.py` is deleted.

```python
"""GitHub integration — gh CLI wrapper + PR state sync."""

class PRNotFoundError(Exception):
    """Raised when no PR exists for a branch."""
    def __init__(self, branch: str) -> None:
        self.branch = branch
        super().__init__(f"No open PR found for branch '{branch}'.")

class GitHubUnavailableError(Exception):
    """Raised when gh CLI is not available or auth fails."""

# Private: gh CLI subprocess calls
def _detect_pr(repo_path: str, branch: str) -> dict | None
    # Absorbed from github.py — calls `gh pr list`, returns raw dict or None

def _create_pr_via_gh(repo_path: str, branch: str, *, title: str, body: str) -> dict
    # Calls `gh pr create`, returns raw dict
    # Raises GitHubUnavailableError if gh not available

# Public: business logic with DB coordination
def sync_pr(conn, item_id: int) -> PullRequest
    # Calls _detect_pr(), creates or updates PR record in DB
    # Raises PRNotFoundError if no PR exists

def create_pr(conn, item_id: int, *, title: str | None = None, body: str | None = None) -> PullRequest
    # Calls _create_pr_via_gh(), stores in DB

def list_prs(conn, item_id: int | None = None) -> list[PullRequest]
    # Lists PRs from DB, optionally filtered by work item

def sync_all_prs(conn, repo: str) -> list[PullRequest]
    # Bulk sync — iterate active work items, sync each PR
    # Used by TUI board refresh
```

**All GitHub logic in one file:**
- Private `_detect_pr()`, `_create_pr_via_gh()` — subprocess wrappers for `gh` CLI
- Public `sync_pr()`, `create_pr()`, etc. — business logic coordinating gh calls with DB

### What stays where

- **`cli/hooks.py`** — hook handlers stay here. They're CLI-only, simple, and must be fast. No service extraction needed.
- **`worktree.py`** — git stats functions (`get_diff_stats`, `has_uncommitted_changes`) stay here. TUI calls them directly. No `services/git.py` wrapper needed.
- **`github.py`** (root) — **deleted**. Absorbed into `services/github.py` which owns both the `gh` CLI subprocess calls and DB coordination.
- **`services/__init__.py`** — empty or minimal. Use explicit imports (`from womtrees.services.workitem import start_work_item`), not star exports.

---

## 4. CLI Becomes Thin

CLI commands become ~10-15 lines each: parse args, open connection, call service, catch exceptions, print output.

**Before (items.py `_start_work_item`, ~70 lines of inline logic):**
```python
@click.command()
def create(name, prompt, repo):
    conn = get_connection()
    try:
        repo_path = _resolve_repo(repo)
        # ... 40 lines of business logic ...
    except ValueError as e:
        conn.close()
        raise click.ClickException(str(e))
    finally:
        conn.close()
```

**After (~10 lines):**
```python
@click.command()
def create(name, prompt, repo):
    repo_path = _resolve_repo(repo)
    with db.connection() as conn:
        try:
            item = workitem.create_work_item(conn, str(repo_path), name, prompt)
            click.echo(f"Created #{item.id}: {item.name}")
        except (DuplicateBranchError, InvalidStateError) as e:
            raise click.ClickException(str(e))
```

**Remove from `cli/__init__.py`:** The `__all__ = ["cli", "_start_work_item", "_maybe_resume_claude", "_restore_tmux_session"]` hack. The TUI imports from `services.workitem` instead.

---

## 5. TUI Decomposition

### `app.py` stays as single file

After service layer extraction, action methods shrink from ~60 lines to ~15 lines each. A ~400-line `app.py` (shell + thin actions + refresh) is manageable as a single file. No need for `tui/actions.py` or `tui/refresh.py` — free functions taking `app` as parameter would be tightly coupled to the app's widget internals anyway.

**Before (`action_start_item`, ~60 lines):**
```python
async def action_start_item(self) -> None:
    # ... 60 lines of inline business logic ...
```

**After (~15 lines):**
```python
async def action_start_item(self) -> None:
    card = self._focused_card()
    if card is None:
        return
    with db.connection() as conn:
        try:
            workitem.start_work_item(conn, card.item.id, self.config)
            self._refresh_board()
        except (WorkItemNotFoundError, InvalidStateError) as e:
            self.notify(str(e), severity="error")
```

### Split `dialogs.py` (711 → 7 files)

**`tui/dialogs/`** directory:

| File | Contents | ~Lines |
|------|----------|--------|
| `__init__.py` | Explicit re-exports of all dialog classes | ~10 |
| `create.py` | `CreateDialog` | ~100 |
| `edit.py` | `EditDialog` | ~80 |
| `delete.py` | `DeleteDialog` | ~60 |
| `merge.py` | `MergeDialog` | ~80 |
| `rebase.py` | `RebaseDialog`, `AutoRebaseDialog` | ~120 |
| `claude_stream.py` | `ClaudeStreamDialog` | ~150 |
| `help.py` | `HelpDialog` | ~60 |

**`__init__.py` uses explicit re-exports (no star imports):**
```python
from womtrees.tui.dialogs.create import CreateDialog
from womtrees.tui.dialogs.edit import EditDialog
from womtrees.tui.dialogs.delete import DeleteDialog
from womtrees.tui.dialogs.merge import MergeDialog
from womtrees.tui.dialogs.rebase import AutoRebaseDialog, RebaseDialog
from womtrees.tui.dialogs.claude_stream import ClaudeStreamDialog
from womtrees.tui.dialogs.help import HelpDialog
```

This preserves existing import paths: `from womtrees.tui.dialogs import CreateDialog` still works.

---

## 6. Final File Layout

```
src/womtrees/
    __init__.py
    models.py           # unchanged
    config.py           # unchanged
    db.py               # ADD connection() context manager (~5 lines)
    worktree.py         # unchanged (subprocess wrapper, keeps git stats)
    tmux.py             # unchanged (subprocess wrapper)
    claude.py           # unchanged (context detection)
    github.py           # DELETED — absorbed into services/github.py

    services/
        __init__.py     # empty
        workitem.py     # EXPANDED — merge existing + extract from cli/items.py + tui/app.py
        github.py       # NEW — PR sync/create, coordinates github.py wrapper + DB

    cli/
        __init__.py     # CLEAN UP — remove _start_work_item export hack
        items.py        # THINNED — delegates to services/workitem.py
        info.py         # THINNED — uses db.connection() context manager
        hooks.py        # MINOR — uses db.connection() context manager (logic stays here)
        admin.py        # unchanged
        utils.py        # unchanged

    tui/
        __init__.py
        app.py          # THINNED — action methods delegate to services
        board.py        # unchanged
        column.py       # unchanged
        card.py         # unchanged
        dialogs/        # SPLIT from single dialogs.py
            __init__.py
            create.py
            edit.py
            delete.py
            merge.py
            rebase.py
            claude_stream.py
            help.py
```

**Net change:** ~15 source files → ~22 source files. The increase is almost entirely from the dialog split (7 files replacing 1).

---

## 7. Migration Strategy

Three phases, each independently shippable and testable:

### Phase 1: Service Layer (highest value)
1. Add `WorkItemNotFoundError` and `InvalidStateError` to `services/workitem.py`
2. Extract `_start_work_item` from `cli/items.py` into `services/workitem.py`
3. Extract other lifecycle functions (create, review, done, delete, merge)
4. Update CLI commands to call service functions
5. Update TUI actions to call service functions
6. Remove `_start_work_item` export hack from `cli/__init__.py`
7. Run tests, fix breakages

### Phase 2: TUI Dialog Split
8. Create `tui/dialogs/` directory
9. Move each dialog class to its own file
10. Add `__init__.py` with explicit re-exports
11. Delete old `tui/dialogs.py`
12. Verify all imports resolve

### Phase 3: Cleanup
13. Add `db.connection()` context manager
14. Migrate all `get_connection()` / `conn.close()` sites to use `with db.connection() as conn:`
15. Update tests for new patterns
16. Update `CLAUDE.md` with new architecture

---

## 8. CLAUDE.md Updates

After refactoring, update the Architecture section:

```markdown
**Data flow:** CLI/TUI → services/workitem.py (business logic) → db.py + worktree.py/tmux.py (subprocess)

**Key modules in `src/womtrees/`:**
- `db.py` — All DB access; plain SQL, WAL mode, migration system; `connection()` context manager for auto-close
- `models.py` — `WorkItem`, `ClaudeSession`, `PullRequest`, `GitStats` dataclasses
- `worktree.py` — Git worktree create/remove/merge/list; repo detection; diff stats
- `tmux.py` — Tmux session/pane management; send-keys, attach, split
- `claude.py` — Context detection (reads `$TMUX_PANE`, resolves work item from tmux env)
- `config.py` — TOML config loading with typed `Config` dataclass

**Service layer (`services/`):**
- `workitem.py` — Work item lifecycle (create, start, review, done, merge, delete, edit). Coordinates DB, git, tmux operations. Both CLI and TUI call these functions. Defines domain exceptions: `WorkItemNotFoundError`, `InvalidStateError`, `DuplicateBranchError`, `OpenPullRequestError`.
- `github.py` — All GitHub logic: `gh` CLI subprocess calls (private) + PR sync/create with DB coordination (public). Absorbs root `github.py`. Defines `PRNotFoundError`, `GitHubUnavailableError`.

**CLI (`cli/`):**
- Thin Click commands: parse args → `with db.connection()` → call service → catch exceptions → print output
- `hooks.py` — Claude Code hook handlers (heartbeat, input, stop) — logic stays here (CLI-only)

**TUI (`tui/`):**
- `app.py` — Textual app: keybindings, compose, thin action methods calling services
- `dialogs/` — One file per dialog (create, edit, delete, merge, rebase, claude_stream, help)
- `board.py` / `column.py` / `card.py` — Kanban layout widgets

**Error handling pattern:**
- Service functions raise typed exceptions (WorkItemNotFoundError, InvalidStateError, etc.)
- CLI catches and wraps in click.ClickException
- TUI catches and shows via self.notify(severity="error")
- Subprocess errors (git, tmux) propagate as CalledProcessError — caught at service boundary
```
