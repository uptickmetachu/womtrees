"""Generate cute notification sounds as WAV files.

Run once during development:
    python src/womtrees/sounds/generate.py
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

SAMPLE_RATE = 44100
AMPLITUDE = 0.35
SOUNDS_DIR = Path(__file__).parent


def _boop(
    freq_start: float,
    freq_end: float,
    duration: float,
    amplitude: float = AMPLITUDE,
) -> list[int]:
    """Generate a soft 'boop' with pitch slide and rounded envelope."""
    n = int(SAMPLE_RATE * duration)
    samples: list[int] = []
    phase = 0.0

    for i in range(n):
        t = i / n

        # Smooth frequency glide (quadratic ease-out)
        freq = freq_start + (freq_end - freq_start) * (1 - (1 - t) ** 2)

        # Rounded envelope: quick rise, gentle plump decay
        attack = 0.08
        if t < attack:
            env = math.sin((t / attack) * math.pi / 2)
        else:
            env = math.cos(((t - attack) / (1 - attack)) * math.pi / 2)

        sample = env * amplitude * (0.85 * math.sin(phase) + 0.15 * math.sin(phase * 2))

        phase += 2 * math.pi * freq / SAMPLE_RATE
        samples.append(int(sample * 32767))

    return samples


def _silence(duration: float) -> list[int]:
    return [0] * int(SAMPLE_RATE * duration)


def _write_wav(path: Path, samples: list[int]) -> Path:
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return path


def generate_notification() -> Path:
    """'notification' — two rising boops, the original baby wombat squeak."""
    boop1 = _boop(620, 830, 0.12, 0.30)
    boop2 = _boop(880, 1050, 0.15, 0.35)
    return _write_wav(
        SOUNDS_DIR / "notification.wav",
        boop1 + _silence(0.04) + boop2,
    )


def generate_nudge() -> Path:
    """'nudge' — a single gentle descending note, like a sleepy wombat yawn."""
    # One soft falling tone, longer decay, very round
    note = _boop(780, 520, 0.25, 0.30)
    return _write_wav(SOUNDS_DIR / "nudge.wav", note)


def generate_triplet() -> Path:
    """'triplet' — three quick ascending pips, like little paws trotting."""
    pip1 = _boop(600, 700, 0.07, 0.25)
    pip2 = _boop(750, 870, 0.07, 0.30)
    pip3 = _boop(920, 1100, 0.09, 0.35)
    gap = _silence(0.03)
    return _write_wav(
        SOUNDS_DIR / "triplet.wav",
        pip1 + gap + pip2 + gap + pip3,
    )


def generate_warble() -> Path:
    """'warble' — a wobbly up-down chirp, like a happy wombat wiggle."""
    n = int(SAMPLE_RATE * 0.28)
    samples: list[int] = []
    phase = 0.0

    for i in range(n):
        t = i / n

        # Wobbling frequency: rises then dips then rises again
        base = 700
        freq = base + 250 * math.sin(t * math.pi * 3) * (1 - t * 0.3)

        # Soft bell envelope
        attack = 0.06
        if t < attack:
            env = math.sin((t / attack) * math.pi / 2)
        else:
            env = (1 - ((t - attack) / (1 - attack))) ** 1.5

        sample = env * 0.32 * (0.80 * math.sin(phase) + 0.20 * math.sin(phase * 3))

        phase += 2 * math.pi * freq / SAMPLE_RATE
        samples.append(int(sample * 32767))

    return _write_wav(SOUNDS_DIR / "warble.wav", samples)


def generate_all() -> list[Path]:
    return [
        generate_notification(),
        generate_nudge(),
        generate_triplet(),
        generate_warble(),
    ]


if __name__ == "__main__":
    for path in generate_all():
        print(f"Generated: {path.name}")
