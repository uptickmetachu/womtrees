from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WorkItem:
    id: int
    repo_name: str
    repo_path: str
    branch: str
    prompt: str | None
    worktree_path: str | None
    status: str  # todo, working, review, done
    created_at: str
    updated_at: str
