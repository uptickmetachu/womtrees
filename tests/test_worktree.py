from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from womtrees.worktree import (
    SetupScriptError,
    create_worktree,
    get_current_repo,
    load_womtrees_config,
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


# -- .womtrees.toml config loading --


def test_load_womtrees_config(tmp_path):
    (tmp_path / ".womtrees.toml").write_text(
        '[scripts]\nsetup = ["echo hello"]\n\n[copy]\nfiles = [".env"]\n'
    )

    result = load_womtrees_config(str(tmp_path))
    assert result is not None
    assert result["scripts"]["setup"] == ["echo hello"]
    assert result["copy"]["files"] == [".env"]


def test_load_womtrees_config_missing(tmp_path):
    assert load_womtrees_config(str(tmp_path)) is None


def test_load_womtrees_config_local_override(tmp_path):
    (tmp_path / ".womtrees.toml").write_text(
        '[scripts]\nsetup = ["npm install"]\nteardown = ["docker-compose down"]\n'
    )
    (tmp_path / ".womtrees.local.toml").write_text(
        '[scripts]\nsetup = ["pnpm install"]\n'
    )

    result = load_womtrees_config(str(tmp_path))
    assert result is not None
    # Local fully replaces the scripts section
    assert result["scripts"]["setup"] == ["pnpm install"]
    # teardown is gone because local replaced the entire [scripts] section
    assert "teardown" not in result["scripts"]


def test_load_womtrees_config_local_only(tmp_path):
    (tmp_path / ".womtrees.local.toml").write_text(
        '[scripts]\nsetup = ["echo local"]\n'
    )

    result = load_womtrees_config(str(tmp_path))
    assert result is not None
    assert result["scripts"]["setup"] == ["echo local"]


# -- Worktree creation/removal --


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

    # Create .womtrees.toml
    (git_repo / ".womtrees.toml").write_text(
        '[copy]\nfiles = [".env"]\n\n[scripts]\nsetup = ["echo setup_ran > .setup_marker"]\n'
    )

    base_dir = tmp_path / "worktrees"
    wt_path = create_worktree(str(git_repo), "feat/setup-test", base_dir)

    # Verify file was copied
    assert (wt_path / ".env").read_text() == "SECRET=123"

    # Verify setup command ran
    assert (wt_path / ".setup_marker").exists()
    assert "setup_ran" in (wt_path / ".setup_marker").read_text()

    remove_worktree(wt_path)


def test_create_worktree_setup_failure_rolls_back(git_repo, tmp_path):
    (git_repo / ".womtrees.toml").write_text('[scripts]\nsetup = ["exit 1"]\n')

    base_dir = tmp_path / "worktrees"
    with pytest.raises(SetupScriptError) as exc_info:
        create_worktree(str(git_repo), "feat/fail-setup", base_dir)

    # Worktree should be rolled back
    expected_path = base_dir / git_repo.name / "feat-fail-setup"
    assert not expected_path.exists()

    # Log file should be preserved
    assert exc_info.value.log_path is not None
    assert exc_info.value.log_path.exists()
    log_content = exc_info.value.log_path.read_text()
    assert "FAILED" in log_content

    # Cleanup log
    exc_info.value.log_path.unlink()


def test_setup_success_cleans_log(git_repo, tmp_path):
    (git_repo / ".womtrees.toml").write_text('[scripts]\nsetup = ["echo ok"]\n')

    base_dir = tmp_path / "worktrees"
    wt_path = create_worktree(str(git_repo), "feat/log-clean", base_dir)

    # No log files should remain in /tmp for successful runs
    import glob

    logs = glob.glob("/tmp/womtrees-setup-feat-log-clean-*.log")
    assert len(logs) == 0

    remove_worktree(wt_path)


# -- Teardown scripts --


def test_remove_worktree_with_teardown(git_repo, tmp_path):
    (git_repo / ".womtrees.toml").write_text(
        '[scripts]\nteardown = ["echo teardown_ran > /tmp/womtrees-test-teardown-marker"]\n'
    )

    base_dir = tmp_path / "worktrees"
    wt_path = create_worktree(str(git_repo), "feat/teardown-test", base_dir)

    warning = remove_worktree(wt_path, branch="feat/teardown-test")
    assert warning is None
    assert not wt_path.exists()

    # Verify teardown command ran
    marker = Path("/tmp/womtrees-test-teardown-marker")
    assert marker.exists()
    assert "teardown_ran" in marker.read_text()
    marker.unlink()


def test_remove_worktree_teardown_failure_still_removes(git_repo, tmp_path):
    (git_repo / ".womtrees.toml").write_text('[scripts]\nteardown = ["exit 1"]\n')

    base_dir = tmp_path / "worktrees"
    wt_path = create_worktree(str(git_repo), "feat/teardown-fail", base_dir)

    warning = remove_worktree(wt_path, branch="feat/teardown-fail")

    # Worktree should still be removed
    assert not wt_path.exists()

    # Warning should be returned with log path
    assert warning is not None
    assert "Teardown scripts failed" in warning
    assert "Log:" in warning

    # Log file should exist
    log_path = Path(warning.split("Log: ")[1])
    assert log_path.exists()
    log_content = log_path.read_text()
    assert "FAILED" in log_content

    # Cleanup log
    log_path.unlink()
