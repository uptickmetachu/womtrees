from __future__ import annotations

import os
import re
import subprocess


def _run(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, check=check)


def sanitize_session_name(name: str) -> str:
    """Sanitize a name for use as a tmux session name (no dots or colons)."""
    name = re.sub(r"[.:]", "-", name)
    return name


def create_session(name: str, working_dir: str) -> str:
    """Create a detached tmux session. Returns the session name used."""
    name = sanitize_session_name(name)

    # If session name already exists, append a numeric suffix
    if session_exists(name):
        i = 2
        while session_exists(f"{name}-{i}"):
            i += 1
        name = f"{name}-{i}"

    _run(["tmux", "new-session", "-d", "-s", name, "-c", working_dir])
    return name


def split_pane(session: str, direction: str, working_dir: str) -> str:
    """Split a pane in the session. Returns the new pane id.

    direction: 'vertical' (-h, side by side) or 'horizontal' (-v, top/bottom)
    """
    flag = "-h" if direction == "vertical" else "-v"
    result = _run([
        "tmux", "split-window", flag,
        "-t", session,
        "-c", working_dir,
        "-P", "-F", "#{pane_id}",
    ])
    return result.stdout.strip()


def swap_pane(session: str) -> None:
    """Swap the current pane with the previous one (used to put Claude on left/top)."""
    _run(["tmux", "swap-pane", "-t", session, "-U"])


def select_pane(session: str, pane: str) -> None:
    """Select a specific pane."""
    _run(["tmux", "select-pane", "-t", f"{session}.{pane}"])


def send_keys(target: str, keys: str) -> None:
    """Send keys to a tmux target (session:window.pane)."""
    _run(["tmux", "send-keys", "-t", target, keys, "Enter"])


def kill_session(name: str) -> None:
    """Kill a tmux session."""
    _run(["tmux", "kill-session", "-t", name], check=False)


def session_exists(name: str) -> bool:
    """Check if a tmux session exists."""
    result = _run(["tmux", "has-session", "-t", name], check=False)
    return result.returncode == 0


def set_environment(session: str, key: str, value: str) -> None:
    """Set a session-scoped environment variable."""
    _run(["tmux", "set-environment", "-t", session, key, value])


def attach(name: str) -> None:
    """Attach or switch to a tmux session."""
    if os.environ.get("TMUX"):
        subprocess.run(["tmux", "switch-client", "-t", name])
    else:
        subprocess.run(["tmux", "attach-session", "-t", name])


def is_available() -> bool:
    """Check if tmux is installed."""
    try:
        _run(["tmux", "-V"])
        return True
    except FileNotFoundError:
        return False
