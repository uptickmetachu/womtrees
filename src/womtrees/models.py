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
    tmux_session: str | None
    status: str  # todo, working, review, done
    created_at: str
    updated_at: str


@dataclass
class ClaudeSession:
    id: int
    work_item_id: int | None
    repo_name: str
    repo_path: str
    branch: str
    tmux_session: str
    tmux_pane: str
    pid: int | None
    state: str  # working, waiting, done
    prompt: str | None
    created_at: str
    updated_at: str
