"""GitHub PR operations via the `gh` CLI."""

from __future__ import annotations

import json
import subprocess


class PRNotFoundError(Exception):
    """Raised when no PR is found for the given branch."""

    def __init__(self, branch: str) -> None:
        self.branch = branch
        super().__init__(f"No PR found for branch '{branch}'.")


class GitHubUnavailableError(Exception):
    """Raised when the `gh` CLI is unavailable or returns an error."""

    def __init__(self, reason: str = "") -> None:
        self.reason = reason
        super().__init__(
            f"GitHub CLI unavailable: {reason}" if reason else "GitHub CLI unavailable."
        )


def _detect_pr(repo_path: str, branch: str) -> dict | None:
    """Detect an open PR for the given branch using `gh pr list`.

    Returns a dict with keys: number, state, url, owner, repo — or None.
    """
    try:
        result = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "--head",
                branch,
                "--json",
                "number,state,url,headRepository,headRepositoryOwner",
                "--limit",
                "1",
            ],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        FileNotFoundError,
    ):
        return None

    try:
        prs = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    if not prs:
        return None

    pr = prs[0]
    return {
        "number": pr["number"],
        "state": pr["state"].lower(),
        "url": pr.get("url"),
        "owner": pr.get("headRepositoryOwner", {}).get("login", ""),
        "repo": pr.get("headRepository", {}).get("name", ""),
    }


# Public convenience alias (used by callers that don't need exceptions)
detect_pr = _detect_pr


def sync_pr() -> None:
    """Sync a single PR's status. (Stub for future implementation.)"""
    raise NotImplementedError


def create_pr() -> None:
    """Create a PR via `gh`. (Stub for future implementation.)"""
    raise NotImplementedError


def list_prs() -> None:
    """List PRs for a repo. (Stub for future implementation.)"""
    raise NotImplementedError


def sync_all_prs() -> None:
    """Sync all PR statuses. (Stub for future implementation.)"""
    raise NotImplementedError
