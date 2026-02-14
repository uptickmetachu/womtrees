"""Tests for the TUI kanban board (Phase 4)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

from womtrees.models import ClaudeSession, WorkItem
from womtrees.tui.card import WorkItemCard, UnmanagedCard, _time_ago
from womtrees.tui.board import KanbanBoard, CLAUDE_STATE_TO_STATUS
from womtrees.tui.column import KanbanColumn


# -- Fixtures --

def _make_item(
    id: int = 1,
    repo_name: str = "myrepo",
    repo_path: str = "/tmp/myrepo",
    branch: str = "feat/test",
    name: str | None = None,
    prompt: str | None = None,
    worktree_path: str | None = None,
    tmux_session: str | None = None,
    status: str = "todo",
) -> WorkItem:
    now = datetime.now(timezone.utc).isoformat()
    return WorkItem(
        id=id,
        repo_name=repo_name,
        repo_path=repo_path,
        branch=branch,
        name=name,
        prompt=prompt,
        worktree_path=worktree_path,
        tmux_session=tmux_session,
        status=status,
        created_at=now,
        updated_at=now,
    )


def _make_session(
    id: int = 1,
    work_item_id: int | None = None,
    repo_name: str = "myrepo",
    repo_path: str = "/tmp/myrepo",
    branch: str = "feat/test",
    tmux_session: str = "myrepo/feat-test",
    tmux_pane: str = "0",
    pid: int | None = 1234,
    state: str = "working",
    prompt: str | None = None,
    claude_session_id: str | None = None,
) -> ClaudeSession:
    now = datetime.now(timezone.utc).isoformat()
    return ClaudeSession(
        id=id,
        work_item_id=work_item_id,
        repo_name=repo_name,
        repo_path=repo_path,
        branch=branch,
        tmux_session=tmux_session,
        tmux_pane=tmux_pane,
        pid=pid,
        state=state,
        prompt=prompt,
        claude_session_id=claude_session_id,
        created_at=now,
        updated_at=now,
    )


# -- Unit tests for card helpers --

class TestTimeAgo:
    def test_recent(self):
        now = datetime.now(timezone.utc).isoformat()
        assert _time_ago(now) == "<1m"

    def test_minutes(self):
        from datetime import timedelta
        t = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        assert _time_ago(t) == "30m"

    def test_hours(self):
        from datetime import timedelta
        t = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        assert _time_ago(t) == "5h"

    def test_days(self):
        from datetime import timedelta
        t = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        assert _time_ago(t) == "3d"

    def test_invalid(self):
        assert _time_ago("not-a-date") == "?"

    def test_none(self):
        assert _time_ago(None) == "?"


# -- Unit tests for board status mapping --

class TestClaudeStateMapping:
    def test_working_maps_to_working(self):
        assert CLAUDE_STATE_TO_STATUS["working"] == "working"

    def test_waiting_maps_to_input(self):
        assert CLAUDE_STATE_TO_STATUS["waiting"] == "input"

    def test_done_maps_to_review(self):
        assert CLAUDE_STATE_TO_STATUS["done"] == "review"


# -- Async TUI tests --

class TestCheckRefresh:
    """Tests for the DB-mtime-based refresh trigger."""

    @pytest.mark.asyncio
    async def test_skips_when_db_missing(self):
        """_check_refresh does nothing when DB file doesn't exist."""
        from womtrees.tui.app import WomtreesApp

        with patch("womtrees.tui.app.get_connection") as mock_conn, \
             patch("womtrees.tui.app.get_current_repo", return_value=("myrepo", "/tmp/myrepo")):
            conn = MagicMock()
            mock_conn.return_value = conn

            with patch("womtrees.tui.app.list_work_items", return_value=[]), \
                 patch("womtrees.tui.app.list_claude_sessions", return_value=[]):
                app = WomtreesApp()
                async with app.run_test(size=(120, 40)) as pilot:
                    # Point at a nonexistent file
                    from pathlib import Path
                    app._db_path = Path("/tmp/nonexistent-womtrees-test.db")
                    call_count_before = mock_conn.call_count
                    app._check_refresh()
                    # Should not have triggered another refresh
                    assert mock_conn.call_count == call_count_before

    @pytest.mark.asyncio
    async def test_skips_when_mtime_unchanged(self, tmp_path):
        """_check_refresh skips refresh when mtime hasn't changed."""
        from womtrees.tui.app import WomtreesApp

        db_file = tmp_path / "womtrees.db"
        db_file.write_text("fake")

        with patch("womtrees.tui.app.get_connection") as mock_conn, \
             patch("womtrees.tui.app.get_current_repo", return_value=("myrepo", "/tmp/myrepo")):
            conn = MagicMock()
            mock_conn.return_value = conn

            with patch("womtrees.tui.app.list_work_items", return_value=[]), \
                 patch("womtrees.tui.app.list_claude_sessions", return_value=[]):
                app = WomtreesApp()
                async with app.run_test(size=(120, 40)) as pilot:
                    app._db_path = db_file
                    app._last_db_mtime = db_file.stat().st_mtime
                    call_count_before = mock_conn.call_count
                    app._check_refresh()
                    # mtime unchanged, no new refresh
                    assert mock_conn.call_count == call_count_before

    @pytest.mark.asyncio
    async def test_refreshes_when_mtime_changes(self, tmp_path):
        """_check_refresh triggers refresh when mtime changes."""
        from womtrees.tui.app import WomtreesApp
        import time

        db_file = tmp_path / "womtrees.db"
        db_file.write_text("v1")

        with patch("womtrees.tui.app.get_connection") as mock_conn, \
             patch("womtrees.tui.app.get_current_repo", return_value=("myrepo", "/tmp/myrepo")):
            conn = MagicMock()
            mock_conn.return_value = conn

            with patch("womtrees.tui.app.list_work_items", return_value=[]), \
                 patch("womtrees.tui.app.list_claude_sessions", return_value=[]):
                app = WomtreesApp()
                async with app.run_test(size=(120, 40)) as pilot:
                    app._db_path = db_file
                    app._last_db_mtime = db_file.stat().st_mtime
                    call_count_before = mock_conn.call_count

                    # Modify the file to change mtime
                    time.sleep(0.05)
                    db_file.write_text("v2")

                    app._check_refresh()
                    # Should have triggered a refresh (new get_connection call)
                    assert mock_conn.call_count > call_count_before


@pytest.mark.asyncio
async def test_app_mounts():
    """App should mount with board, status bar, header, and footer."""
    from womtrees.tui.app import WomtreesApp

    with patch("womtrees.tui.app.get_connection") as mock_conn, \
         patch("womtrees.tui.app.get_current_repo", return_value=("myrepo", "/tmp/myrepo")):
        conn = MagicMock()
        mock_conn.return_value = conn

        with patch("womtrees.tui.app.list_work_items", return_value=[]):
            with patch("womtrees.tui.app.list_claude_sessions", return_value=[]):
                app = WomtreesApp()
                async with app.run_test(size=(120, 40)) as pilot:
                    board = app.query_one("#board", KanbanBoard)
                    assert board is not None
                    assert len(board.columns) == 4
                    assert list(board.columns.keys()) == ["todo", "working", "input", "review"]


@pytest.mark.asyncio
async def test_app_shows_items():
    """Items should appear in the correct columns."""
    from womtrees.tui.app import WomtreesApp

    items = [
        _make_item(id=1, status="todo", branch="feat/a"),
        _make_item(id=2, status="working", branch="feat/b", tmux_session="s1"),
        _make_item(id=3, status="review", branch="feat/c"),
    ]

    with patch("womtrees.tui.app.get_connection") as mock_conn, \
         patch("womtrees.tui.app.get_current_repo", return_value=("myrepo", "/tmp/myrepo")):
        conn = MagicMock()
        mock_conn.return_value = conn

        with patch("womtrees.tui.app.list_work_items", return_value=items):
            with patch("womtrees.tui.app.list_claude_sessions", return_value=[]):
                app = WomtreesApp()
                async with app.run_test(size=(120, 40)) as pilot:
                    board = app.query_one("#board", KanbanBoard)
                    todo_cards = board.columns["todo"].get_focusable_cards()
                    working_cards = board.columns["working"].get_focusable_cards()
                    review_cards = board.columns["review"].get_focusable_cards()
                    assert len(todo_cards) == 1
                    assert len(working_cards) == 1
                    assert len(review_cards) == 1


@pytest.mark.asyncio
async def test_app_unmanaged_sessions():
    """Unmanaged sessions should show in the working column."""
    from womtrees.tui.app import WomtreesApp

    sessions = [
        _make_session(id=1, work_item_id=None, state="working", branch="main"),
    ]

    with patch("womtrees.tui.app.get_connection") as mock_conn, \
         patch("womtrees.tui.app.get_current_repo", return_value=("myrepo", "/tmp/myrepo")):
        conn = MagicMock()
        mock_conn.return_value = conn

        with patch("womtrees.tui.app.list_work_items", return_value=[]):
            with patch("womtrees.tui.app.list_claude_sessions", return_value=sessions):
                app = WomtreesApp()
                async with app.run_test(size=(120, 40)) as pilot:
                    board = app.query_one("#board", KanbanBoard)
                    working_cards = board.columns["working"].get_focusable_cards()
                    assert any(isinstance(c, UnmanagedCard) for c in working_cards)


@pytest.mark.asyncio
async def test_app_toggle_grouping():
    """Pressing 'g' should toggle grouping and show notification."""
    from womtrees.tui.app import WomtreesApp

    with patch("womtrees.tui.app.get_connection") as mock_conn, \
         patch("womtrees.tui.app.get_current_repo", return_value=("myrepo", "/tmp/myrepo")):
        conn = MagicMock()
        mock_conn.return_value = conn

        with patch("womtrees.tui.app.list_work_items", return_value=[]):
            with patch("womtrees.tui.app.list_claude_sessions", return_value=[]):
                app = WomtreesApp()
                async with app.run_test(size=(120, 40)) as pilot:
                    assert app.group_by_repo is True
                    await pilot.press("g")
                    assert app.group_by_repo is False
                    await pilot.press("g")
                    assert app.group_by_repo is True


@pytest.mark.asyncio
async def test_app_toggle_all():
    """Pressing 'a' should toggle show_all."""
    from womtrees.tui.app import WomtreesApp

    with patch("womtrees.tui.app.get_connection") as mock_conn, \
         patch("womtrees.tui.app.get_current_repo", return_value=("myrepo", "/tmp/myrepo")):
        conn = MagicMock()
        mock_conn.return_value = conn

        with patch("womtrees.tui.app.list_work_items", return_value=[]):
            with patch("womtrees.tui.app.list_claude_sessions", return_value=[]):
                app = WomtreesApp()
                async with app.run_test(size=(120, 40)) as pilot:
                    assert app.show_all is False
                    await pilot.press("a")
                    assert app.show_all is True
                    await pilot.press("a")
                    assert app.show_all is False


@pytest.mark.asyncio
async def test_app_status_bar():
    """Status bar should show item counts."""
    from womtrees.tui.app import WomtreesApp
    from textual.widgets import Static

    items = [
        _make_item(id=1, status="todo"),
        _make_item(id=2, status="todo"),
        _make_item(id=3, status="working"),
    ]

    with patch("womtrees.tui.app.get_connection") as mock_conn, \
         patch("womtrees.tui.app.get_current_repo", return_value=("myrepo", "/tmp/myrepo")):
        conn = MagicMock()
        mock_conn.return_value = conn

        with patch("womtrees.tui.app.list_work_items", return_value=items):
            with patch("womtrees.tui.app.list_claude_sessions", return_value=[]):
                app = WomtreesApp()
                async with app.run_test(size=(120, 40)) as pilot:
                    status = app.query_one("#status-counts", Static)
                    text = status.content
                    assert "2 todo" in text
                    assert "1 working" in text
                    assert "myrepo" in text


@pytest.mark.asyncio
async def test_app_show_all_flag():
    """WomtreesApp(show_all=True) should start in all-repos mode."""
    from womtrees.tui.app import WomtreesApp
    from textual.widgets import Static

    with patch("womtrees.tui.app.get_connection") as mock_conn, \
         patch("womtrees.tui.app.get_current_repo", return_value=("myrepo", "/tmp/myrepo")):
        conn = MagicMock()
        mock_conn.return_value = conn

        with patch("womtrees.tui.app.list_work_items", return_value=[]):
            with patch("womtrees.tui.app.list_claude_sessions", return_value=[]):
                app = WomtreesApp(show_all=True)
                async with app.run_test(size=(120, 40)) as pilot:
                    assert app.show_all is True
                    status = app.query_one("#status-counts", Static)
                    text = status.content
                    assert "all repos" in text


@pytest.mark.asyncio
async def test_app_column_navigation():
    """h/l keys should navigate between columns with cards."""
    from womtrees.tui.app import WomtreesApp

    items = [
        _make_item(id=1, status="todo", branch="feat/a"),
        _make_item(id=2, status="working", branch="feat/b"),
        _make_item(id=3, status="review", branch="feat/c"),
    ]

    with patch("womtrees.tui.app.get_connection") as mock_conn, \
         patch("womtrees.tui.app.get_current_repo", return_value=("myrepo", "/tmp/myrepo")):
        conn = MagicMock()
        mock_conn.return_value = conn

        with patch("womtrees.tui.app.list_work_items", return_value=items):
            with patch("womtrees.tui.app.list_claude_sessions", return_value=[]):
                app = WomtreesApp()
                async with app.run_test(size=(120, 40)) as pilot:
                    assert app.active_column_idx == 0
                    await pilot.press("l")
                    assert app.active_column_idx == 1  # working
                    await pilot.press("l")
                    assert app.active_column_idx == 3  # review (skips empty input)
                    await pilot.press("h")
                    assert app.active_column_idx == 1  # working (skips empty input)
                    await pilot.press("h")
                    assert app.active_column_idx == 0  # todo
                    await pilot.press("h")
                    assert app.active_column_idx == 0  # stays at 0


@pytest.mark.asyncio
async def test_app_help_dialog():
    """Pressing ? should open help dialog."""
    from womtrees.tui.app import WomtreesApp
    from womtrees.tui.dialogs import HelpDialog

    with patch("womtrees.tui.app.get_connection") as mock_conn, \
         patch("womtrees.tui.app.get_current_repo", return_value=("myrepo", "/tmp/myrepo")):
        conn = MagicMock()
        mock_conn.return_value = conn

        with patch("womtrees.tui.app.list_work_items", return_value=[]):
            with patch("womtrees.tui.app.list_claude_sessions", return_value=[]):
                app = WomtreesApp()
                async with app.run_test(size=(120, 40)) as pilot:
                    await pilot.press("question_mark")
                    await pilot.pause()
                    # The help dialog should be on the screen stack
                    assert len(app.screen_stack) > 1
