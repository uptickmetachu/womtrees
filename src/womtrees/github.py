from __future__ import annotations

import json
import subprocess


def detect_pr(repo_path: str, branch: str) -> dict | None:
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
