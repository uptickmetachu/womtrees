from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
# default_layout = "standard"

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

# -- Custom layouts --
# Define named layout presets. Each layout has windows, each window has panes.
# Exactly one pane across all windows must have claude = true.
#
# [layouts.standard]
# [[layouts.standard.windows]]
# name = "main"
# layout = "even-horizontal"
# panes = [
#   { claude = true },
#   {},
# ]
#
# [layouts.dev-server]
# [[layouts.dev-server.windows]]
# name = "code"
# layout = "even-horizontal"
# panes = [
#   { claude = true },
#   {},
# ]
# [[layouts.dev-server.windows]]
# name = "services"
# layout = "even-horizontal"
# panes = [
#   { command = "npm run dev" },
#   { command = "npm run test -- --watch" },
# ]
"""


@dataclass
class PaneConfig:
    claude: bool = False
    command: str | None = None


@dataclass
class WindowConfig:
    name: str
    layout: str = "even-horizontal"
    panes: list[PaneConfig] = field(default_factory=list)


@dataclass
class LayoutConfig:
    windows: list[WindowConfig] = field(default_factory=list)


def _parse_layouts(data: dict[str, Any]) -> dict[str, LayoutConfig]:
    """Parse [layouts.*] sections from TOML data into LayoutConfig objects."""
    layouts_data = data.get("layouts", {})
    layouts: dict[str, LayoutConfig] = {}

    for layout_name, layout_data in layouts_data.items():
        windows: list[WindowConfig] = []
        for win_data in layout_data.get("windows", []):
            panes: list[PaneConfig] = []
            for pane_data in win_data.get("panes", []):
                panes.append(
                    PaneConfig(
                        claude=pane_data.get("claude", False),
                        command=pane_data.get("command"),
                    )
                )
            windows.append(
                WindowConfig(
                    name=win_data.get("name", "main"),
                    layout=win_data.get("layout", "even-horizontal"),
                    panes=panes,
                )
            )
        layouts[layout_name] = LayoutConfig(windows=windows)

    return layouts


def _synthesize_standard_layout(tmux_split: str, tmux_claude_pane: str) -> LayoutConfig:
    """Synthesize a 'standard' layout from legacy tmux.split/tmux.claude_pane fields."""
    if tmux_split == "horizontal":
        layout_str = "even-vertical"
    else:
        layout_str = "even-horizontal"

    claude_first = tmux_claude_pane in ("left", "top")
    if claude_first:
        panes = [PaneConfig(claude=True), PaneConfig()]
    else:
        panes = [PaneConfig(), PaneConfig(claude=True)]

    return LayoutConfig(
        windows=[WindowConfig(name="main", layout=layout_str, panes=panes)]
    )


def _validate_layout(name: str, layout: LayoutConfig) -> None:
    """Validate a layout config. Raises ValueError on invalid config."""
    if not layout.windows:
        raise ValueError(f"Layout '{name}' must have at least one window.")

    claude_count = 0
    for win_idx, window in enumerate(layout.windows):
        if not window.panes:
            raise ValueError(
                f"Layout '{name}', window '{window.name}' must have at least one pane."
            )
        for pane_idx, pane in enumerate(window.panes):
            if pane.claude and pane.command:
                raise ValueError(
                    f"Layout '{name}', window '{window.name}', "
                    f"pane {pane_idx}: cannot have both claude=true and command."
                )
            if pane.claude:
                claude_count += 1

    if claude_count == 0:
        raise ValueError(
            f"Layout '{name}' must have exactly one pane with claude=true."
        )
    if claude_count > 1:
        raise ValueError(
            f"Layout '{name}' has {claude_count} claude panes; exactly one is required."
        )


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
    layouts: dict[str, LayoutConfig] = field(default_factory=dict)
    default_layout: str = "standard"

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
        default_layout = tmux.get("default_layout", "standard")

        claude = data.get("claude", {})
        claude_args = claude.get("args", "")

        branch_prefix = worktrees.get("branch_prefix", "np-01")

        pr_section = data.get("pull_requests", {})
        pr_prompt = pr_section.get("prompt", "/pr")

        notifications = data.get("notifications", {})
        sound_enabled = notifications.get("sound", True)
        sound_input = notifications.get("input_sound", "triplet")
        sound_review = notifications.get("review_sound", "notification")

        # Parse explicit layouts
        layouts = _parse_layouts(data)

        # Ensure "standard" always exists
        if "standard" not in layouts:
            layouts["standard"] = _synthesize_standard_layout(
                tmux_split, tmux_claude_pane
            )

        # Validate all layouts
        for name, layout in layouts.items():
            _validate_layout(name, layout)

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
            layouts=layouts,
            default_layout=default_layout,
        )


def get_config() -> Config:
    return Config.load()


def ensure_config() -> Path:
    """Create default config file if it doesn't exist. Returns config path."""
    if not CONFIG_FILE.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(DEFAULT_CONFIG)
    return CONFIG_FILE
