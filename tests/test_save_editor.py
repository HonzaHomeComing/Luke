"""Tests for save decrypt / apply flow."""

from __future__ import annotations

import json
import struct
import tempfile
import unittest
from pathlib import Path

import wunderwaffe_save_editor as editor


def encode_minus1(text: str) -> bytes:
    return bytes((ord(ch) - 1) & 0xFF for ch in text)


class SaveEditorTests(unittest.TestCase):
    def test_decrypt_and_apply_roundtrip(self) -> None:
        blob = (
            encode_minus1("FrontDays")
            + b"\x00\x00\x00\x00"
            + struct.pack("<i", 120)
            + b"\x00\x00"
        )
        with tempfile.TemporaryDirectory() as tmp:
            save = Path(tmp) / "continue_save_game_pww"
            save.write_bytes(blob)
            out = editor.decrypt_save(save, Path(tmp) / "out")

            self.assertTrue((out / "editable_values.json").exists())
            self.assertTrue((out / "decoded_strings.txt").exists())
            text = (out / "decoded_strings.txt").read_text(encoding="utf-8")
            self.assertIn("FrontDays", text)

            payload = json.loads((out / "editable_values.json").read_text(encoding="utf-8"))
            self.assertTrue(payload["values"])
            # edit first matching 120
            edited = False
            for row in payload["values"]:
                if row["current_value"] == 120:
                    row["new_value"] = 9999999
                    edited = True
                    break
            self.assertTrue(edited)
            (out / "editable_values.json").write_text(
                json.dumps(payload, indent=2), encoding="utf-8"
            )

            save_path, logs = editor.apply_edits(out)
            self.assertEqual(save_path, save)
            self.assertIn(struct.pack("<i", 9999999), save.read_bytes())
            self.assertTrue(any("SET" in line for line in logs))


if __name__ == "__main__":
    unittest.main()
