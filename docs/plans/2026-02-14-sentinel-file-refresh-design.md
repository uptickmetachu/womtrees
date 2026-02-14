# DB Mtime Refresh Trigger

**Status: Implemented**

## Problem

The TUI polls every 3 seconds via `set_interval(3, _refresh_board)`. This is both too slow (3s latency on state changes) and too aggressive (full DB query + DOM rebuild even when nothing changed).

## Design

Watch the SQLite database file's mtime directly. Every `conn.commit()` updates the file's mtime automatically — no sentinel file or `db.py` changes needed. The TUI `stat()`s the DB file on a 0.5s interval and only refreshes when the mtime changes.

**WAL caveat:** With `journal_mode=WAL`, writes go to `womtrees.db-wal` and the main file's mtime only updates on checkpoint. Solution: stat both files and use max mtime.

## Implementation

### Replace polling in `app.py`

```python
def on_mount(self) -> None:
    self._db_path = get_config().base_dir / "womtrees.db"
    self._wal_path = self._db_path.parent / (self._db_path.name + "-wal")
    self._last_db_mtime: float = 0
    self._refresh_board()
    self.set_interval(0.5, self._check_refresh)   # fast stat() check
    self.set_interval(10, self._refresh_board)     # safety net fallback

def _check_refresh(self) -> None:
    """Check DB/WAL file mtime; refresh only if changed."""
    mtime: float = 0
    for path in (self._db_path, self._wal_path):
        try:
            mtime = max(mtime, path.stat().st_mtime)
        except FileNotFoundError:
            continue
    if mtime and mtime != self._last_db_mtime:
        self._last_db_mtime = mtime
        self._refresh_board()
```

### Performance characteristics

| Operation | Before | After |
|-----------|--------|-------|
| Idle check | Full DB query every 3s | `stat()` syscall every 0.5s |
| Change latency | Up to 3s | Up to 0.5s |
| Fallback | None | 10s full refresh |

## Files changed

- `src/womtrees/tui/app.py` -- replace `set_interval(3)` with `_check_refresh()` + 10s fallback
- `tests/test_tui.py` -- 3 new tests for `_check_refresh()` behavior
