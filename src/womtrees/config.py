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
"""


@dataclass
class Config:
    base_dir: Path

    @classmethod
    def load(cls) -> Config:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, "rb") as f:
                data = tomllib.load(f)
        else:
            data = {}

        worktrees = data.get("worktrees", {})
        base_dir = Path(worktrees.get("base_dir", str(DEFAULT_BASE_DIR))).expanduser()

        return cls(base_dir=base_dir)


def get_config() -> Config:
    return Config.load()


def ensure_config() -> Path:
    """Create default config file if it doesn't exist. Returns config path."""
    if not CONFIG_FILE.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(DEFAULT_CONFIG)
    return CONFIG_FILE
