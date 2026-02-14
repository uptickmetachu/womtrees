# Sentinel File Refresh Trigger

## Problem

The TUI polls every 3 seconds via `set_interval(3, _refresh_board)`. This is both too slow (3s latency on state changes) and too aggressive (full DB query + DOM rebuild even when nothing changed).

## Design

A sentinel file at `~/.local/share/womtrees/.refresh` acts as a change signal. Every DB write operation touches this file. The TUI `stat()`s the file on a fast interval and only refreshes when the mtime changes.

## Implementation

### A. Add `notify_refresh()` to `db.py`

Add a module-level helper that writes a timestamp to the sentinel file:

```python
_REFRESH_FILE: Path | None = None

def _get_refresh_path() -> Path:
    global _REFRESH_FILE
    if _REFRESH_FILE is None:
        _REFRESH_FILE = get_config().base_dir / ".refresh"
    return _REFRESH_FILE

def notify_refresh() -> None:
    """Touch the sentinel file to signal TUI refresh."""
    path = _get_refresh_path()
    path.write_text(str(time.monotonic_ns()))
```

### B. Call `notify_refresh()` after every write

Add `notify_refresh()` at the end of these functions in `db.py`:

- `create_work_item()` (after line 167, after `conn.commit()`)
- `update_work_item()` (after line 208, after `conn.commit()`)
- `delete_work_item()` (after line 215, after `conn.commit()`)
- `create_claude_session()` (after line 241, after `conn.commit()`)
- `update_claude_session()` (after line 288, after `conn.commit()`)
- `delete_claude_session()` (after line 294, after `conn.commit()`)

### C. Replace polling in `app.py`

Replace the current `on_mount()` (lines 90-92):

```python
# Before
def on_mount(self) -> None:
    self._refresh_board()
    self.set_interval(3, self._refresh_board)
```

With:

```python
def on_mount(self) -> None:
    self._last_refresh_mtime: float = 0
    self._refresh_board()
    self.set_interval(0.5, self._check_refresh)   # fast stat() check
    self.set_interval(10, self._refresh_board)     # safety net fallback

def _check_refresh(self) -> None:
    """Check sentinel file mtime; refresh only if changed."""
    from womtrees.db import _get_refresh_path
    path = _get_refresh_path()
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        return
    if mtime != self._last_refresh_mtime:
        self._last_refresh_mtime = mtime
        self._refresh_board()
```

### D. Performance characteristics

| Operation | Before | After |
|-----------|--------|-------|
| Idle check | Full DB query every 3s | `stat()` syscall every 0.5s |
| Change latency | Up to 3s | Up to 0.5s |
| Fallback | None | 10s full refresh |

`stat()` is a single syscall (~microseconds). No DB connection, no widget work. The 10s fallback covers edge cases like external DB edits or sentinel file deletion.

## Files changed

- `src/womtrees/db.py` -- add `notify_refresh()`, `_get_refresh_path()`, call after each write
- `src/womtrees/tui/app.py` -- replace `set_interval(3)` with `_check_refresh()` + 10s fallback

## Testing

### A test: sentinel file is touched on DB write

```python
def test_notify_refresh_on_create(tmp_path):
    """Creating a work item touches the sentinel file."""
    conn = get_connection(tmp_path / "test.db")
    path = tmp_path / ".refresh"
    # patch _get_refresh_path to use tmp_path
    create_work_item(conn, "repo", "/path", "branch")
    assert path.exists()
    mtime1 = path.stat().st_mtime
    update_work_item(conn, 1, status="working")
    mtime2 = path.stat().st_mtime
    assert mtime2 > mtime1
```

### B test: TUI only refreshes on mtime change

```python
def test_check_refresh_skips_when_unchanged(app):
    """_check_refresh does not call _refresh_board when mtime is same."""
    # Mock _refresh_board, call _check_refresh twice
    # Assert _refresh_board called only once (initial)
```
