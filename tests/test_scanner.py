"""Smoke tests for the all-in-one scanner."""

from __future__ import annotations

import json
import struct
import tempfile
import unittest
from pathlib import Path

import wunderwaffe_scanner as scanner


class ScannerTests(unittest.TestCase):
    def test_finds_keyed_120_in_json_and_binary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config.json").write_text(
                '{"frontDays": 120, "name": "east"}\n', encoding="utf-8"
            )
            (root / "data.bin").write_bytes(b"HEADER" + struct.pack("<i", 120) + b"daysleft\x00")
            (root / "noise.png").write_bytes(b"\x89PNG\r\n" + b"\x00" * 32)

            report = scanner.scan_game_root(root)
            self.assertGreaterEqual(report.total_hits, 1)
            self.assertTrue(any(h.score >= 100 for h in report.top_candidates))

            out = root / "logs"
            json_path, txt_path = scanner.write_logs(report, out)
            self.assertTrue(json_path.exists())
            self.assertTrue(txt_path.exists())
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["target_days"], 120)
            self.assertIn("Phase 1", txt_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
