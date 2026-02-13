from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path


def sanitize_branch_name(branch: str) -> str:
    """Sanitize a branch name for use as a directory name."""
    name = branch.replace("/", "-")
    name = re.sub(r"[^\w\-.]", "", name)
    name = name.strip("-.")
    return name or "worktree"


def get_current_repo() -> tuple[str, str] | None:
    """Return (repo_name, repo_path) if cwd is inside a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        repo_path = result.stdout.strip()
        repo_name = Path(repo_path).name
        return repo_name, repo_path
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def load_womtrees_json(repo_path: str) -> dict | None:
    """Load .womtrees.json from a repo root if it exists."""
    json_path = Path(repo_path) / ".womtrees.json"
    if not json_path.exists():
        return None
    with open(json_path) as f:
        return json.load(f)


def create_worktree(repo_path: str, branch: str, base_dir: Path) -> Path:
    """Create a git worktree and run setup from .womtrees.json if present.

    Returns the worktree path.
    """
    repo_name = Path(repo_path).name
    sanitized = sanitize_branch_name(branch)
    worktree_path = base_dir / repo_name / sanitized

    worktree_path.parent.mkdir(parents=True, exist_ok=True)

    # Check if branch exists
    result = subprocess.run(
        ["git", "-C", repo_path, "rev-parse", "--verify", branch],
        capture_output=True,
        text=True,
    )
    branch_exists = result.returncode == 0

    cmd = ["git", "-C", repo_path, "worktree", "add"]
    if not branch_exists:
        cmd += ["-b", branch, str(worktree_path)]
    else:
        cmd += [str(worktree_path), branch]

    subprocess.run(cmd, check=True, capture_output=True, text=True)

    # Run .womtrees.json setup
    config = load_womtrees_json(repo_path)
    if config:
        _run_womtrees_setup(config, repo_path, worktree_path)

    return worktree_path


def _run_womtrees_setup(config: dict, repo_path: str, worktree_path: Path) -> None:
    """Copy files and run setup commands from .womtrees.json."""
    # Copy files first
    for file_path in config.get("copy", []):
        src = Path(repo_path) / file_path
        dst = worktree_path / file_path
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)

    # Run setup commands
    env = os.environ.copy()
    env["ROOT_WORKTREE_PATH"] = repo_path

    for cmd in config.get("setup", []):
        subprocess.run(
            cmd,
            shell=True,
            cwd=worktree_path,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )


def remove_worktree(worktree_path: str | Path, repo_path: str | Path | None = None) -> None:
    """Remove a git worktree and prune."""
    worktree_path = Path(worktree_path)

    # Discover the main repo from the worktree's .git file if not provided
    if repo_path is None:
        git_file = worktree_path / ".git"
        if git_file.is_file():
            # .git file in worktree contains: gitdir: /path/to/repo/.git/worktrees/<name>
            content = git_file.read_text().strip()
            if content.startswith("gitdir:"):
                git_dir = Path(content.split(":", 1)[1].strip())
                # Go up from .git/worktrees/<name> to the repo root
                repo_path = git_dir.parent.parent.parent

    cmd = ["git"]
    if repo_path:
        cmd += ["-C", str(repo_path)]
    cmd += ["worktree", "remove", str(worktree_path), "--force"]

    subprocess.run(cmd, check=True, capture_output=True, text=True)

    prune_cmd = ["git"]
    if repo_path:
        prune_cmd += ["-C", str(repo_path)]
    prune_cmd += ["worktree", "prune"]

    subprocess.run(prune_cmd, capture_output=True, text=True)
