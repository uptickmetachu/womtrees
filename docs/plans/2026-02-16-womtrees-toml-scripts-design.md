# Design: .womtrees.toml Scripts (Setup & Teardown)

**Date:** 2026-02-16
**Branch:** feat/on-create-scripts

## Problem

Worktree creation/deletion often requires project-specific scripts (installing deps, starting/stopping services, cleaning caches). The existing `.womtrees.json` format supports `setup` and `copy` but:

- No teardown scripts for deletion
- No logging — failures are opaque
- JSON format is inconsistent with the rest of the project (TOML)
- No local overrides (secrets, machine-specific paths)

## Design

### Configuration Files

Replace `.womtrees.json` with two TOML files in the repo root:

**`.womtrees.toml`** (committed to git):
```toml
[copy]
files = [".env.template", "node_modules"]

[scripts]
setup = ["npm install", "cp .env.example .env"]
teardown = ["docker-compose down"]
```

**`.womtrees.local.toml`** (gitignored, optional):
```toml
[scripts]
setup = ["npm install", "cp .env.local .env"]
```

**Merge behavior:** `.womtrees.local.toml` overrides `.womtrees.toml` at the key level. If local defines `scripts.setup`, it fully replaces the base `scripts.setup` (no appending). Keys not present in local fall through to base.

### Script Execution

Commands run sequentially in the worktree directory using the user's shell environment. The `ROOT_WORKTREE_PATH` env var points to the source repo.

**Setup:** Runs after worktree creation + file copying. On failure, the worktree is rolled back (removed).

**Teardown:** Runs *before* `git worktree remove`. On failure, the worktree is still removed — failure is a warning, not a blocker.

### Logging

Every script execution writes to a timestamped log file:

```
/tmp/womtrees-<action>-<branch>-<timestamp>.log
```

Example: `/tmp/womtrees-setup-feat-login-20260216-143022.log`

Log contents:
```
[womtrees setup] 2026-02-16 14:30:22
worktree: /home/user/.local/share/womtrees/myapp/feat-login
repo: /home/user/projects/myapp

$ npm install
<stdout/stderr output>
exit: 0

$ cp .env.example .env
<stdout/stderr output>
exit: 0

RESULT: SUCCESS
```

**Auto-cleanup:** On success, the log file is deleted. On failure, the log is preserved.

**Notification:**
- **CLI:** Warning to stderr with log path — `Warning: teardown failed. See: /tmp/womtrees-teardown-feat-login-...log`
- **TUI:** Toast notification via `self.notify()` with log path

### Error Handling Summary

| Scenario | Behavior |
|---|---|
| Setup script fails | Worktree rolled back, log preserved, error raised |
| Teardown script fails | Worktree still removed, log preserved, warning surfaced |
| `.womtrees.toml` missing | No scripts run (silent, same as today) |
| `.womtrees.local.toml` missing | Base config used as-is |

## Implementation

### Modified Files

1. **`worktree.py`**
   - Replace `_load_womtrees_config()` → load TOML, merge local overrides
   - Replace `_run_womtrees_setup()` → use new `_run_scripts()` with logging
   - Add `_run_womtrees_teardown()` — called from `remove_worktree()`
   - Add `_run_scripts(commands, worktree_path, repo_path, action, branch) -> ScriptResult` — core executor with logging
   - Update `create_worktree()` to use new config loading
   - Update `remove_worktree()` to load config and call teardown before removal

2. **`services/workitem.py`**
   - Surface teardown warnings from `remove_worktree()` to callers

3. **`tui/app.py`**
   - Show teardown warnings as toast notifications

4. **`cli/items.py`**
   - Print teardown warnings to stderr

5. **Tests**
   - Update `test_worktree.py` to use `.womtrees.toml` format
   - Add teardown tests
   - Add logging tests (log created on failure, cleaned on success)

### No Changes

- No DB schema changes
- No new CLI commands
- No global config.toml changes
