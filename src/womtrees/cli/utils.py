from __future__ import annotations

import re
import subprocess
import sys

import click

from womtrees.worktree import get_current_repo


def _resolve_repo(repo_path_str: str | None) -> tuple[str, str]:
    """Resolve repo from --repo option or current git context."""
    if repo_path_str is not None:
        from pathlib import Path

        resolved = Path(repo_path_str).expanduser().resolve()
        return resolved.name, str(resolved)
    repo = get_current_repo()
    if repo is None:
        raise click.ClickException("Not inside a git repository.")
    return repo


def _slugify(text: str) -> str:
    """Convert text to a branch-safe slug (lowercase, dashes, no special chars)."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text or "task"


def _generate_name(prompt: str) -> str:
    """Generate a short kebab-case name for a task using claude -p.

    Falls back to a truncated slug of the prompt if claude fails.
    """
    instruction = (
        "Generate a short 2-3 word kebab-case name for this task. "
        "Output ONLY the name, nothing else. Example: fix-login-bug\n\n"
        f"Task: {prompt}"
    )
    try:
        result = subprocess.run(
            ["claude", "-p", instruction, "--model", "haiku"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            name = result.stdout.strip()
            # Sanitize the output — claude might add quotes or extra text
            name = _slugify(name)
            if name and len(name) <= 50:
                return name
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    # Fallback: truncated slug of the prompt
    return _slugify(prompt)[:40]


def _read_prompt(prompt_arg: str | None) -> str | None:
    """Read prompt from positional arg or stdin if piped."""
    if prompt_arg:
        return prompt_arg
    if not sys.stdin.isatty():
        text = sys.stdin.read().strip()
        if text:
            return text
    return None
