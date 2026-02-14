from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


CLAUDE_SETTINGS_DIR = Path.home() / ".claude"
CLAUDE_SETTINGS_FILE = CLAUDE_SETTINGS_DIR / "settings.json"

WOMTREE_HOOKS = {
    "hooks": {
        "UserPromptSubmit": [
            {
                "matcher": "",
                "hooks": [
                    {
                        "type": "command",
                        "command": "wt hook heartbeat",
                    }
                ],
            }
        ],
        "PostToolUse": [
            {
                "matcher": "",
                "hooks": [
                    {
                        "type": "command",
                        "command": "wt hook heartbeat",
                    }
                ],
            }
        ],
        "Notification": [
            {
                "matcher": "permission_prompt",
                "hooks": [
                    {
                        "type": "command",
                        "command": "wt hook input",
                    }
                ],
            },
            {
                "matcher": "elicitation_dialog",
                "hooks": [
                    {
                        "type": "command",
                        "command": "wt hook input",
                    }
                ],
            },
        ],
        "PermissionRequest": [
            {
                "matcher": "",
                "hooks": [
                    {
                        "type": "command",
                        "command": "wt hook input",
                    }
                ],
            }
        ],
        "Stop": [
            {
                "matcher": "",
                "hooks": [
                    {
                        "type": "command",
                        "command": "wt hook stop",
                    }
                ],
            }
        ],
    }
}


def _is_wt_hook_entry(entry: dict) -> bool:
    """Check if a hook entry contains a wt hook command."""
    for handler in entry.get("hooks", []):
        if "wt hook" in handler.get("command", ""):
            return True
    # Old format: {"command": "wt hook ..."}
    if "wt hook" in entry.get("command", ""):
        return True
    return False


TMUX_CONF = Path.home() / ".tmux.conf"
TMUX_STATUS_MARKER = "wt status --tmux"


def configure_tmux_status_bar() -> bool:
    """Add wt status to tmux status-right in ~/.tmux.conf.

    Returns True if changes were made, False if already configured.
    """
    if TMUX_CONF.exists():
        content = TMUX_CONF.read_text()
    else:
        content = ""

    if TMUX_STATUS_MARKER in content:
        return False

    lines_to_add = [
        "",
        "# womtrees status bar",
        'set -g status-right "#(wt status --tmux) | %H:%M"',
        "set -g status-interval 5",
    ]

    # If there's an existing status-right, comment it out
    new_lines = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("set") and "status-right" in stripped and not stripped.startswith("#"):
            new_lines.append(f"# {line}  # replaced by womtrees")
        elif stripped.startswith("set") and "status-interval" in stripped and not stripped.startswith("#"):
            new_lines.append(f"# {line}  # replaced by womtrees")
        else:
            new_lines.append(line)

    new_content = "\n".join(new_lines)
    if not new_content.endswith("\n"):
        new_content += "\n"
    new_content += "\n".join(lines_to_add) + "\n"

    TMUX_CONF.write_text(new_content)

    # Reload tmux config if tmux is running
    try:
        subprocess.run(
            ["tmux", "source-file", str(TMUX_CONF)],
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        pass

    return True


def install_global_hooks() -> None:
    """Install womtrees hooks into Claude Code's global settings.

    Strips all existing wt hook entries per event, then adds the current
    ones fresh. This handles additions, removals, and matcher changes.
    """
    CLAUDE_SETTINGS_DIR.mkdir(parents=True, exist_ok=True)

    if CLAUDE_SETTINGS_FILE.exists():
        with open(CLAUDE_SETTINGS_FILE) as f:
            settings = json.load(f)
    else:
        settings = {}

    hooks = settings.get("hooks", {})

    # Clean stale wt hook entries from ALL events (including ones we no longer use)
    for event in list(hooks.keys()):
        hooks[event] = [e for e in hooks[event] if not _is_wt_hook_entry(e)]

    # Add current wt hook entries
    for event, hook_list in WOMTREE_HOOKS["hooks"].items():
        existing = hooks.get(event, [])
        existing.extend(hook_list)
        hooks[event] = existing

    settings["hooks"] = hooks

    with open(CLAUDE_SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)


def detect_context() -> dict:
    """Gather context from the current environment for hook commands.

    Returns dict with: tmux_session, tmux_pane, repo_name, repo_path,
    branch, work_item_id (nullable), pid.
    """
    context = {
        "tmux_session": None,
        "tmux_pane": None,
        "repo_name": None,
        "repo_path": None,
        "branch": None,
        "work_item_id": None,
        "pid": os.getppid(),
    }

    # Get tmux pane from env
    context["tmux_pane"] = os.environ.get("TMUX_PANE", "")

    # Get tmux session name
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#S"],
            capture_output=True, text=True, check=True,
        )
        context["tmux_session"] = result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # Get work_item_id from tmux environment
    if context["tmux_session"]:
        try:
            result = subprocess.run(
                ["tmux", "show-environment", "-t", context["tmux_session"], "WOMTREE_WORK_ITEM_ID"],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                # Output format: WOMTREE_WORK_ITEM_ID=42
                line = result.stdout.strip()
                if "=" in line:
                    value = line.split("=", 1)[1]
                    context["work_item_id"] = int(value)
        except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
            pass

    # Get git info
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        context["repo_path"] = result.stdout.strip()
        context["repo_name"] = Path(context["repo_path"]).name
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, check=True,
        )
        context["branch"] = result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    return context


def is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is still running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False
