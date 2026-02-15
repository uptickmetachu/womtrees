from __future__ import annotations

import sqlite3

import pytest

from womtrees.db import (
    _ensure_schema,
    create_work_item,
    delete_work_item,
    get_connection,
    get_work_item,
    list_repos,
    list_work_items,
    update_work_item,
)


def _in_memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    return conn


def test_create_and_get():
    conn = _in_memory_conn()
    item = create_work_item(
        conn, "myrepo", "/tmp/myrepo", "feat/auth", prompt="Add login"
    )
    assert item.id == 1
    assert item.repo_name == "myrepo"
    assert item.branch == "feat/auth"
    assert item.prompt == "Add login"
    assert item.status == "todo"
    assert item.worktree_path is None
    assert item.tmux_session is None

    fetched = get_work_item(conn, 1)
    assert fetched is not None
    assert fetched.id == item.id
    assert fetched.branch == item.branch


def test_get_nonexistent():
    conn = _in_memory_conn()
    assert get_work_item(conn, 999) is None


def test_list_all():
    conn = _in_memory_conn()
    create_work_item(conn, "repo1", "/tmp/repo1", "branch-a")
    create_work_item(conn, "repo2", "/tmp/repo2", "branch-b")
    create_work_item(conn, "repo1", "/tmp/repo1", "branch-c")

    items = list_work_items(conn)
    assert len(items) == 3


def test_list_by_repo():
    conn = _in_memory_conn()
    create_work_item(conn, "repo1", "/tmp/repo1", "branch-a")
    create_work_item(conn, "repo2", "/tmp/repo2", "branch-b")
    create_work_item(conn, "repo1", "/tmp/repo1", "branch-c")

    items = list_work_items(conn, repo_name="repo1")
    assert len(items) == 2
    assert all(i.repo_name == "repo1" for i in items)


def test_list_by_status():
    conn = _in_memory_conn()
    create_work_item(conn, "repo1", "/tmp/repo1", "a", status="todo")
    create_work_item(conn, "repo1", "/tmp/repo1", "b", status="working")
    create_work_item(conn, "repo1", "/tmp/repo1", "c", status="todo")

    items = list_work_items(conn, status="todo")
    assert len(items) == 2
    assert all(i.status == "todo" for i in items)


def test_update():
    conn = _in_memory_conn()
    item = create_work_item(conn, "repo1", "/tmp/repo1", "branch-a")

    updated = update_work_item(
        conn,
        item.id,
        status="working",
        worktree_path="/tmp/wt",
        tmux_session="repo/branch",
    )
    assert updated is not None
    assert updated.status == "working"
    assert updated.worktree_path == "/tmp/wt"
    assert updated.tmux_session == "repo/branch"
    assert updated.updated_at > item.updated_at


def test_delete():
    conn = _in_memory_conn()
    item = create_work_item(conn, "repo1", "/tmp/repo1", "branch-a")

    assert delete_work_item(conn, item.id) is True
    assert get_work_item(conn, item.id) is None


def test_delete_nonexistent():
    conn = _in_memory_conn()
    assert delete_work_item(conn, 999) is False


def test_duplicate_branch_raises():
    conn = _in_memory_conn()
    create_work_item(conn, "repo1", "/tmp/repo1", "feat/dup")
    with pytest.raises(ValueError, match="already has an active work item"):
        create_work_item(conn, "repo1", "/tmp/repo1", "feat/dup")


def test_duplicate_branch_allowed_after_done():
    conn = _in_memory_conn()
    item = create_work_item(conn, "repo1", "/tmp/repo1", "feat/dup")
    update_work_item(conn, item.id, status="done")
    # Should succeed — previous item is done
    item2 = create_work_item(conn, "repo1", "/tmp/repo1", "feat/dup")
    assert item2.id != item.id


def test_list_repos_empty():
    conn = _in_memory_conn()
    assert list_repos(conn) == []


def test_list_repos_distinct():
    conn = _in_memory_conn()
    create_work_item(conn, "repo1", "/tmp/repo1", "a")
    create_work_item(conn, "repo2", "/tmp/repo2", "b")
    create_work_item(conn, "repo1", "/tmp/repo1", "c")  # duplicate repo

    repos = list_repos(conn)
    assert len(repos) == 2
    assert ("repo1", "/tmp/repo1") in repos
    assert ("repo2", "/tmp/repo2") in repos


def test_list_repos_ordered():
    conn = _in_memory_conn()
    create_work_item(conn, "zebra", "/tmp/zebra", "a")
    create_work_item(conn, "alpha", "/tmp/alpha", "b")

    repos = list_repos(conn)
    assert repos[0][0] == "alpha"
    assert repos[1][0] == "zebra"


def test_duplicate_branch_allowed_different_repo():
    conn = _in_memory_conn()
    create_work_item(conn, "repo1", "/tmp/repo1", "feat/dup")
    # Same branch in a different repo is fine
    item2 = create_work_item(conn, "repo2", "/tmp/repo2", "feat/dup")
    assert item2.branch == "feat/dup"
