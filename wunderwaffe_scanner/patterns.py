"""Search targets related to the 120 in-game-day timer."""

from __future__ import annotations

import struct
from dataclasses import dataclass

# Primary value the player wants to change
TARGET_DAYS = 120

# Related numeric encodings that often appear for day timers
RELATED_INTS = {
    120: "days (exact target)",
    119: "days-1 (countdown style)",
    121: "days+1 (inclusive range)",
    120 * 24: "hours for 120 days",
    120 * 24 * 60: "minutes for 120 days",
    120 * 24 * 3600: "seconds for 120 days",
}

RELATED_FLOATS = {
    120.0: "days float",
    119.0: "days-1 float",
    float(120 * 24): "hours float",
}

# Case-insensitive keyword needles (ASCII). UTF-16LE variants are derived at runtime.
KEYWORDS = [
    "days",
    "day",
    "timer",
    "deadline",
    "countdown",
    "front",
    "fronts",
    "front days",
    "frontdays",
    "daysleft",
    "days_left",
    "dayleft",
    "maxdays",
    "max_days",
    "gamedays",
    "game_days",
    "timelimit",
    "time_limit",
    "start days",
    "startdays",
    "remaining",
    "invasion",
    "allies",
    "soviets",
    "east front",
    "west front",
    "northwest",
    "southwest",
    "wunderwaffe",
    "campaign",
    "difficulty",
]

# High-signal compound phrases for ranking
HIGH_SIGNAL_PHRASES = [
    "front days",
    "days left",
    "daysleft",
    "max days",
    "game days",
    "time limit",
    "days until",
    "invasion in",
]


@dataclass(frozen=True)
class BinaryNeedle:
    label: str
    data: bytes
    score: int


def build_binary_needles() -> list[BinaryNeedle]:
    needles: list[BinaryNeedle] = []

    for value, meaning in RELATED_INTS.items():
        score = 100 if value == TARGET_DAYS else 40
        for endian, tag in (("<", "LE"), (">", "BE")):
            needles.append(
                BinaryNeedle(
                    label=f"int32_{tag}={value} ({meaning})",
                    data=struct.pack(f"{endian}i", value),
                    score=score,
                )
            )
            if 0 <= value <= 0xFFFF:
                needles.append(
                    BinaryNeedle(
                        label=f"uint16_{tag}={value} ({meaning})",
                        data=struct.pack(f"{endian}H", value),
                        score=score - 10,
                    )
                )
            needles.append(
                BinaryNeedle(
                    label=f"int64_{tag}={value} ({meaning})",
                    data=struct.pack(f"{endian}q", value),
                    score=score - 5,
                )
            )

    for value, meaning in RELATED_FLOATS.items():
        score = 90 if value == float(TARGET_DAYS) else 35
        for endian, tag in (("<", "LE"), (">", "BE")):
            needles.append(
                BinaryNeedle(
                    label=f"float32_{tag}={value} ({meaning})",
                    data=struct.pack(f"{endian}f", value),
                    score=score,
                )
            )
            needles.append(
                BinaryNeedle(
                    label=f"float64_{tag}={value} ({meaning})",
                    data=struct.pack(f"{endian}d", value),
                    score=score - 5,
                )
            )

    # Textual "120" encodings
    needles.append(BinaryNeedle(label='ascii "120"', data=b"120", score=70))
    needles.append(
        BinaryNeedle(label='utf16le "120"', data="120".encode("utf-16le"), score=75)
    )
    needles.append(
        BinaryNeedle(label='utf16be "120"', data="120".encode("utf-16be"), score=60)
    )

    return needles


def keyword_bytes() -> list[tuple[str, bytes, int]]:
    out: list[tuple[str, bytes, int]] = []
    for kw in KEYWORDS:
        score = 80 if any(p in kw for p in ("day", "front", "timer", "limit")) else 45
        out.append((f'ascii keyword "{kw}"', kw.encode("ascii"), score))
        out.append((f'utf16le keyword "{kw}"', kw.encode("utf-16le"), score + 5))
    return out
