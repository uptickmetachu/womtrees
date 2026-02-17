from __future__ import annotations

import os
import re
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class ScriptResult:
    """Result of running setup or teardown scripts."""

    success: bool
    log_path: Path | None = None


def sanitize_branch_name(branch: str) -> str:
    """Sanitize a branch name for use as a directory name."""
    name = branch.replace("/", "-")
    name = re.sub(r"[^\w\-.]", "", name)
    name = name.strip("-.")
    return name or "worktree"


def get_current_repo() -> tuple[str, str] | None:
    """Return (repo_name, repo_path) if cwd is inside a git repo.

    When inside a worktree, resolves to the main repository (not the worktree).
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True,
        )
        git_common_dir = Path(result.stdout.strip())
        if not git_common_dir.is_absolute():
            # In a normal (non-worktree) repo, git returns relative ".git"
            git_common_dir = (Path.cwd() / git_common_dir).resolve()
        # --git-common-dir returns the .git dir (e.g. /path/to/repo/.git)
        # The repo root is its parent.
        repo_path = str(git_common_dir.parent)
        repo_name = git_common_dir.parent.name
        return repo_name, repo_path
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def load_womtrees_config(repo_path: str) -> dict[str, Any] | None:
    """Load .womtrees.toml from a repo root, with .womtrees.local.toml overrides.

    Returns None if no config file exists. Local overrides replace base keys
    at the section level (e.g. local [scripts] fully replaces base [scripts]).
    """
    base_path = Path(repo_path) / ".womtrees.toml"
    local_path = Path(repo_path) / ".womtrees.local.toml"

    if not base_path.exists() and not local_path.exists():
        return None

    config: dict[str, Any] = {}

    if base_path.exists():
        with open(base_path, "rb") as f:
            config = tomllib.load(f)

    if local_path.exists():
        with open(local_path, "rb") as f:
            local = tomllib.load(f)
        # Key-level override: local sections replace base sections entirely
        for key, value in local.items():
            config[key] = value

    return config


def create_worktree(repo_path: str, branch: str, base_dir: Path) -> Path:
    """Create a git worktree and run setup from .womtrees.toml if present.

    Returns the worktree path.
    Raises SetupScriptError if setup scripts fail (worktree is rolled back).
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

    # Run .womtrees.toml setup
    config = load_womtrees_config(repo_path)
    if config:
        _run_womtrees_copy(config, repo_path, worktree_path)
        setup_cmds = config.get("scripts", {}).get("setup", [])
        if setup_cmds:
            script_result = _run_scripts(
                setup_cmds,
                worktree_path,
                repo_path,
                "setup",
                branch,
            )
            if not script_result.success:
                # Roll back: remove the worktree
                try:
                    _remove_worktree_git(worktree_path, repo_path)
                except Exception:
                    pass
                raise SetupScriptError(script_result.log_path)

    return worktree_path


class SetupScriptError(Exception):
    """Raised when setup scripts fail during worktree creation."""

    def __init__(self, log_path: Path | None) -> None:
        self.log_path = log_path
        msg = "Setup scripts failed."
        if log_path:
            msg += f" Log: {log_path}"
        super().__init__(msg)


def _run_womtrees_copy(
    config: dict[str, Any],
    repo_path: str,
    worktree_path: Path,
) -> None:
    """Copy files from source repo to worktree based on config."""
    copy_files = config.get("copy", {}).get("files", [])
    for file_path in copy_files:
        src = Path(repo_path) / file_path
        dst = worktree_path / file_path
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)


def _run_scripts(
    commands: list[str],
    worktree_path: Path,
    repo_path: str,
    action: str,
    branch: str,
) -> ScriptResult:
    """Run shell commands sequentially with logging.

    Writes output to /tmp/womtrees-<action>-<branch>-<timestamp>.log.
    On success, the log is deleted. On failure, the log is preserved.
    """
    sanitized = sanitize_branch_name(branch)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = Path(f"/tmp/womtrees-{action}-{sanitized}-{timestamp}.log")

    env = os.environ.copy()
    env["ROOT_WORKTREE_PATH"] = repo_path

    with open(log_path, "w") as log:
        log.write(f"[womtrees {action}] {datetime.now().isoformat()}\n")
        log.write(f"worktree: {worktree_path}\n")
        log.write(f"repo: {repo_path}\n\n")

        for i, cmd in enumerate(commands):
            log.write(f"$ {cmd}\n")
            log.flush()
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=worktree_path,
                env=env,
                capture_output=True,
                text=True,
            )
            if result.stdout:
                log.write(result.stdout)
            if result.stderr:
                log.write(result.stderr)
            log.write(f"exit: {result.returncode}\n\n")

            if result.returncode != 0:
                log.write(f"RESULT: FAILED at command {i + 1}\n")
                return ScriptResult(success=False, log_path=log_path)

        log.write("RESULT: SUCCESS\n")

    # Auto-cleanup on success
    log_path.unlink(missing_ok=True)
    return ScriptResult(success=True)


def get_default_branch(repo_path: str) -> str:
    """Return the default branch name (main or master) for a repo."""
    result = subprocess.run(
        ["git", "-C", repo_path, "symbolic-ref", "refs/remotes/origin/HEAD"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        # refs/remotes/origin/main -> main
        return result.stdout.strip().rsplit("/", 1)[-1]

    # Fallback: check if main or master exists
    for branch in ("main", "master"):
        result = subprocess.run(
            ["git", "-C", repo_path, "rev-parse", "--verify", branch],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return branch

    return "main"


class RebaseRequiredError(Exception):
    """Raised when a branch needs rebasing before it can be merged."""

    def __init__(self, branch: str, default_branch: str) -> None:
        self.branch = branch
        self.default_branch = default_branch
        super().__init__(f"Branch '{branch}' needs rebase onto '{default_branch}'")


def needs_rebase(repo_path: str, branch: str) -> bool:
    """Check if a branch needs rebasing onto the default branch.

    Returns True if the default branch has commits not in the feature branch,
    meaning a rebase is required before merging.
    """
    default_branch = get_default_branch(repo_path)

    # Check if default_branch is an ancestor of the feature branch.
    # If it is NOT an ancestor, the feature branch is behind and needs rebase.
    result = subprocess.run(
        ["git", "-C", repo_path, "merge-base", "--is-ancestor", default_branch, branch],
        capture_output=True,
        text=True,
    )
    return result.returncode != 0


def rebase_branch(worktree_path: str, repo_path: str) -> str:
    """Rebase the current branch in a worktree onto the default branch.

    Runs from the worktree directory where the branch is already checked out.
    Returns the rebase output message.
    Raises subprocess.CalledProcessError on conflict or failure.
    """
    default_branch = get_default_branch(repo_path)

    result = subprocess.run(
        ["git", "rebase", default_branch],
        cwd=worktree_path,
        check=True,
        capture_output=True,
        text=True,
    )

    return result.stdout.strip()


def abort_rebase(worktree_path: str) -> None:
    """Abort an in-progress rebase in a worktree."""
    subprocess.run(
        ["git", "rebase", "--abort"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
    )


def auto_rebase_branch(worktree_path: str, branch: str, default_branch: str) -> str:
    """Use claude -p to automatically rebase a branch, resolving conflicts.

    Runs in the worktree directory so Claude has full access to the codebase.
    Returns claude's output.
    Raises subprocess.CalledProcessError on failure.
    """
    prompt = (
        f"Rebase branch '{branch}' onto '{default_branch}'. "
        f"Run `git rebase {default_branch}` and resolve any merge conflicts "
        f"that arise. Continue the rebase until it completes successfully. "
        f"Do not commit anything beyond what the rebase requires."
    )

    result = subprocess.run(
        ["claude", "-p", prompt],
        cwd=worktree_path,
        check=True,
        capture_output=True,
        text=True,
    )

    return result.stdout.strip()


def get_diff_stats(repo_path: str, branch: str) -> tuple[int, int]:
    """Return (insertions, deletions) comparing branch to the default branch."""
    default_branch = get_default_branch(repo_path)
    result = subprocess.run(
        ["git", "-C", repo_path, "diff", f"{default_branch}...{branch}", "--shortstat"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return (0, 0)

    text = result.stdout.strip()
    insertions = 0
    deletions = 0
    # Parse "N files changed, X insertions(+), Y deletions(-)"
    match = re.search(r"(\d+) insertion", text)
    if match:
        insertions = int(match.group(1))
    match = re.search(r"(\d+) deletion", text)
    if match:
        deletions = int(match.group(1))
    return (insertions, deletions)


def has_uncommitted_changes(worktree_path: str) -> bool:
    """Check if a worktree has uncommitted changes (dirty working tree)."""
    result = subprocess.run(
        ["git", "-C", worktree_path, "status", "--porcelain"],
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def get_uncommitted_diff_stats(worktree_path: str) -> tuple[int, int]:
    """Return (insertions, deletions) for uncommitted changes (staged + unstaged)."""
    result = subprocess.run(
        ["git", "-C", worktree_path, "diff", "HEAD", "--shortstat"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return (0, 0)

    text = result.stdout.strip()
    insertions = 0
    deletions = 0
    match = re.search(r"(\d+) insertion", text)
    if match:
        insertions = int(match.group(1))
    match = re.search(r"(\d+) deletion", text)
    if match:
        deletions = int(match.group(1))
    return (insertions, deletions)


def merge_branch(repo_path: str, branch: str) -> str:
    """Merge a branch into the default branch from the main repo.

    Returns the merge output message.
    Raises RebaseRequiredError if the branch needs rebasing first.
    Raises subprocess.CalledProcessError on conflict or failure.
    """
    default_branch = get_default_branch(repo_path)

    if needs_rebase(repo_path, branch):
        raise RebaseRequiredError(branch, default_branch)

    # Checkout default branch in the main repo
    subprocess.run(
        ["git", "-C", repo_path, "checkout", default_branch],
        check=True,
        capture_output=True,
        text=True,
    )

    # Merge the feature branch
    result = subprocess.run(
        ["git", "-C", repo_path, "merge", "--no-ff", branch],
        check=True,
        capture_output=True,
        text=True,
    )

    return result.stdout.strip()


def rename_branch(worktree_path: str, old_branch: str, new_branch: str) -> None:
    """Rename a git branch inside a worktree directory."""
    subprocess.run(
        ["git", "-C", worktree_path, "branch", "-m", old_branch, new_branch],
        check=True,
        capture_output=True,
        text=True,
    )


def _discover_repo_path(worktree_path: Path) -> Path | None:
    """Discover the main repo path from a worktree's .git file."""
    git_file = worktree_path / ".git"
    if git_file.is_file():
        content = git_file.read_text().strip()
        if content.startswith("gitdir:"):
            git_dir = Path(content.split(":", 1)[1].strip())
            # Go up from .git/worktrees/<name> to the repo root
            return git_dir.parent.parent.parent
    return None


def remove_worktree(
    worktree_path: str | Path,
    repo_path: str | Path | None = None,
    branch: str | None = None,
) -> str | None:
    """Remove a git worktree, running teardown scripts first.

    Returns a warning message if teardown scripts failed, None otherwise.
    The worktree is always removed regardless of teardown success.
    """
    worktree_path = Path(worktree_path)

    if repo_path is None:
        discovered = _discover_repo_path(worktree_path)
        if discovered:
            repo_path = discovered

    # Run teardown scripts before removal
    warning: str | None = None
    if repo_path:
        config = load_womtrees_config(str(repo_path))
        if config:
            teardown_cmds = config.get("scripts", {}).get("teardown", [])
            if teardown_cmds:
                # Determine branch name from worktree dir if not provided
                if branch is None:
                    branch = worktree_path.name
                result = _run_scripts(
                    teardown_cmds,
                    worktree_path,
                    str(repo_path),
                    "teardown",
                    branch,
                )
                if not result.success:
                    warning = f"Teardown scripts failed. Log: {result.log_path}"

    _remove_worktree_git(worktree_path, repo_path)
    return warning


def _remove_worktree_git(
    worktree_path: Path,
    repo_path: str | Path | None = None,
) -> None:
    """Low-level git worktree remove + prune."""
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
