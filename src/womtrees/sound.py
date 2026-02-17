"""Sound notification playback."""

from __future__ import annotations

import shutil
import subprocess
import sys
from importlib import resources
from pathlib import Path

BUILTIN_SOUNDS = {"notification", "nudge", "triplet", "warble"}


def play_notification(state: str = "review") -> None:
    """Play the notification sound for the given state (non-blocking).

    Respects config.sound_enabled. The sound is chosen from
    config.sound_input / config.sound_review — either a built-in name
    (notification, nudge, triplet, warble) or an absolute path to a .wav.
    Falls back silently on any error.
    """
    from womtrees.config import get_config

    config = get_config()
    if not config.sound_enabled:
        return

    sound = config.sound_input if state == "input" else config.sound_review

    try:
        path = _resolve_sound(sound)
        if path:
            _play_file(path)
    except Exception:
        pass  # Silent fallback — notification sound is best-effort


def _resolve_sound(sound: str) -> str | None:
    """Resolve a sound name or path to a playable file path."""
    if sound in BUILTIN_SOUNDS:
        ref = resources.files("womtrees.sounds").joinpath(f"{sound}.wav")
        # as_file extracts to a temp dir if needed; we need the real path
        ctx = resources.as_file(ref)
        return str(ctx.__enter__())

    # Treat as a file path
    p = Path(sound).expanduser()
    if p.is_file():
        return str(p)

    return None


def _play_file(path: str) -> None:
    """Play a WAV file using a platform-appropriate player (non-blocking)."""
    if sys.platform == "darwin":
        player = shutil.which("afplay")
    else:
        player = shutil.which("paplay") or shutil.which("aplay")

    if player is None:
        return

    subprocess.Popen(
        [player, path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
