from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from womtrees.worktree import (
    create_worktree,
    get_current_repo,
    load_womtrees_json,
    remove_worktree,
    sanitize_branch_name,
)


def test_sanitize_branch_name():
    assert sanitize_branch_name("feat/auth") == "feat-auth"
    assert sanitize_branch_name("fix/bug-123") == "fix-bug-123"
    assert sanitize_branch_name("simple") == "simple"
    assert sanitize_branch_name("feat/multi/level") == "feat-multi-level"
    assert sanitize_branch_name("has spaces!@#") == "hasspaces"


def test_get_current_repo(tmp_path, monkeypatch):
    # Create a git repo
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "--allow-empty", "-m", "init"],
        check=True,
        capture_output=True,
    )
    monkeypatch.chdir(tmp_path)

    result = get_current_repo()
    assert result is not None
    repo_name, repo_path = result
    assert repo_name == tmp_path.name
    assert repo_path == str(tmp_path)


def test_get_current_repo_not_git(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert get_current_repo() is None


def test_load_womtrees_json(tmp_path):
    config = {"setup": ["echo hello"], "copy": [".env"]}
    (tmp_path / ".womtrees.json").write_text(json.dumps(config))

    result = load_womtrees_json(str(tmp_path))
    assert result == config


def test_load_womtrees_json_missing(tmp_path):
    assert load_womtrees_json(str(tmp_path)) is None


@pytest.fixture
def git_repo(tmp_path):
    """Create a temporary git repo with an initial commit."""
    repo_path = tmp_path / "source_repo"
    repo_path.mkdir()
    subprocess.run(["git", "init", str(repo_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo_path), "commit", "--allow-empty", "-m", "init"],
        check=True,
        capture_output=True,
    )
    return repo_path


def test_create_and_remove_worktree(git_repo, tmp_path):
    base_dir = tmp_path / "worktrees"
    wt_path = create_worktree(str(git_repo), "feat/test", base_dir)

    assert wt_path.exists()
    assert wt_path == base_dir / git_repo.name / "feat-test"
    assert (wt_path / ".git").exists()

    remove_worktree(wt_path)
    assert not wt_path.exists()


def test_create_worktree_with_setup(git_repo, tmp_path):
    # Create a file in the source repo to copy
    (git_repo / ".env").write_text("SECRET=123")

    # Create .womtrees.json
    config = {
        "copy": [".env"],
        "setup": ["echo setup_ran > .setup_marker"],
    }
    (git_repo / ".womtrees.json").write_text(json.dumps(config))

    base_dir = tmp_path / "worktrees"
    wt_path = create_worktree(str(git_repo), "feat/setup-test", base_dir)

    # Verify file was copied
    assert (wt_path / ".env").read_text() == "SECRET=123"

    # Verify setup command ran
    assert (wt_path / ".setup_marker").exists()
    assert "setup_ran" in (wt_path / ".setup_marker").read_text()

    remove_worktree(wt_path)
