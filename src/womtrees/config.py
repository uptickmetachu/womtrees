from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "womtrees"
CONFIG_FILE = CONFIG_DIR / "config.toml"

DEFAULT_BASE_DIR = Path.home() / ".local" / "share" / "womtrees"

DEFAULT_CONFIG = """\
[worktrees]
base_dir = "~/.local/share/womtrees"
# Prefix for auto-generated branch names (e.g. "np-01/my-feature")
branch_prefix = "np-01"

[tmux]
split = "vertical"
claude_pane = "left"

[claude]
# Extra args passed to `claude` when launching in a worktree pane.
# e.g. "--dangerously-skip-permissions" to skip the trust-folder prompt.
# args = "--dangerously-skip-permissions"

[notifications]
sound = true
# Sound to play on input/review. Built-in: notification, nudge, triplet, warble
# Or an absolute path to a .wav file.
# input_sound = "triplet"
# review_sound = "notification"

# [pull_requests]
# Prompt passed to `claude -p` when creating a PR from the TUI.
# prompt = "/pr"
"""


@dataclass
class Config:
    base_dir: Path
    tmux_split: str  # vertical | horizontal
    tmux_claude_pane: str  # left | right | top | bottom
    claude_args: str  # extra CLI args for claude
    branch_prefix: str  # prefix for auto-generated branch names
    pr_prompt: str  # prompt passed to `claude -p` for PR creation
    sound_enabled: bool  # play sound on input/review transitions
    sound_input: str  # sound name or path for input state
    sound_review: str  # sound name or path for review state

    @classmethod
    def load(cls) -> Config:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, "rb") as f:
                data = tomllib.load(f)
        else:
            data = {}

        worktrees = data.get("worktrees", {})
        base_dir = Path(worktrees.get("base_dir", str(DEFAULT_BASE_DIR))).expanduser()

        tmux = data.get("tmux", {})
        tmux_split = tmux.get("split", "vertical")
        tmux_claude_pane = tmux.get("claude_pane", "left")

        claude = data.get("claude", {})
        claude_args = claude.get("args", "")

        branch_prefix = worktrees.get("branch_prefix", "np-01")

        pr_section = data.get("pull_requests", {})
        pr_prompt = pr_section.get("prompt", "/pr")

        notifications = data.get("notifications", {})
        sound_enabled = notifications.get("sound", True)
        sound_input = notifications.get("input_sound", "triplet")
        sound_review = notifications.get("review_sound", "notification")

        return cls(
            base_dir=base_dir,
            tmux_split=tmux_split,
            tmux_claude_pane=tmux_claude_pane,
            claude_args=claude_args,
            branch_prefix=branch_prefix,
            pr_prompt=pr_prompt,
            sound_enabled=sound_enabled,
            sound_input=sound_input,
            sound_review=sound_review,
        )


def get_config() -> Config:
    return Config.load()


def ensure_config() -> Path:
    """Create default config file if it doesn't exist. Returns config path."""
    if not CONFIG_FILE.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(DEFAULT_CONFIG)
    return CONFIG_FILE
