"""Tests for Phase 2 save decode + candidate detection."""

from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

import wunderwaffe_patcher as patcher


def encode_minus1(text: str) -> bytes:
    return bytes((ord(ch) - 1) & 0xFF for ch in text)


class PatcherTests(unittest.TestCase):
    def test_decode_plus1_mechanics_path(self) -> None:
        raw = encode_minus1("/Game/Mechanics/Grid")
        self.assertEqual(patcher.decode_plus1(raw), b"/Game/Mechanics/Grid")

    def test_finds_front_days_near_int(self) -> None:
        # name (minus1) then padding then int32 LE = 120
        blob = (
            encode_minus1("FrontDays")
            + b"\x00\x00\x00\x00"
            + struct.pack("<i", 120)
            + b"\x00\x00"
        )
        with tempfile.TemporaryDirectory() as tmp:
            save = Path(tmp) / "continue_save_game_pww"
            save.write_bytes(blob)
            cands = patcher.analyze_save(save)
            self.assertTrue(cands)
            self.assertTrue(any(c.old_value == 120 and c.score >= 80 for c in cands))

            logs = patcher.patch_candidates(cands, new_value=9999999, min_score=80)
            self.assertTrue(any("PATCH" in line for line in logs))
            data = save.read_bytes()
            self.assertIn(struct.pack("<i", 9999999), data)
            self.assertTrue(save.with_suffix(save.suffix + ".bak").exists())


if __name__ == "__main__":
    unittest.main()
