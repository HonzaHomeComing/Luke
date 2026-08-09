#!/usr/bin/env python3
"""
Project Wunderwaffe — Save Decrypt / Edit Tool (ALL-IN-ONE)

Your saves store text with each byte = real_byte - 1
  Example in file:  F`ld.Ldbg`mhbr
  Real text:        Game/Mechanics

This app does NOT auto-cheat for you. It:
  1) Decrypts a save into easy files
  2) Lets YOU edit the numbers in a JSON file (Notepad)
  3) Writes your edits back into the save (with .bak backup)

HOW TO USE:
  1. Close the game
  2. Double-click this file
  3. Click "Decrypt save…" and pick a file from SaveGame
  4. Open editable_values.json in Notepad
  5. Change "new_value" (e.g. 120 → 9999999)
  6. Click "Apply edits…"
  7. Start the game and load that save

No pip packages. Python 3.10+ only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path

VERSION = "3.0.0"

DEFAULT_GAME_ROOTS = [
    r"C:\Program Files (x86)\Steam\steamapps\common\Project Wunderwaffe",
    r"C:\Program Files\Steam\steamapps\common\Project Wunderwaffe",
    r"D:\SteamLibrary\steamapps\common\Project Wunderwaffe",
    r"E:\SteamLibrary\steamapps\common\Project Wunderwaffe",
]

INTERESTING_RE = re.compile(
    rb"(?i)(front|days|day|timer|deadline|invasion|countdown|"
    rb"east|west|soviet|allied|time.?limit|remaining)"
)


def guess_game_root() -> Path:
    for c in DEFAULT_GAME_ROOTS:
        p = Path(c)
        if p.exists():
            return p
    return Path(DEFAULT_GAME_ROOTS[0])


def guess_save_dir() -> Path:
    root = guess_game_root()
    for candidate in (
        root / "ProjectWunderwaffe" / "SaveGame",
        root / "SaveGame",
    ):
        if candidate.exists():
            return candidate
    return root / "ProjectWunderwaffe" / "SaveGame"


def decode_plus1(data: bytes) -> bytes:
    return bytes((b + 1) & 0xFF for b in data)


def encode_minus1(data: bytes) -> bytes:
    return bytes((b - 1) & 0xFF for b in data)


def extract_decoded_strings(data: bytes, min_len: int = 4) -> list[tuple[int, str]]:
    """Find ASCII-ish runs in +1-decoded view."""
    decoded = decode_plus1(data)
    out: list[tuple[int, str]] = []
    pattern = re.compile(rb"[\x20-\x7e]{%d,}" % min_len)
    for m in pattern.finditer(decoded):
        text = m.group().decode("ascii", errors="ignore")
        out.append((m.start(), text))
    return out


def _ctx(decoded: bytes, offset: int, radius: int = 40) -> str:
    a = max(0, offset - radius)
    b = min(len(decoded), offset + radius)
    return "".join(chr(x) if 32 <= x < 127 else "." for x in decoded[a:b])


def find_editable_values(data: bytes) -> list[dict]:
    """Build a list of int32 values the user may want to edit."""
    decoded = decode_plus1(data)
    values: list[dict] = []
    seen_offsets: set[int] = set()

    def add_int(offset: int, value: int, why: str, score: int) -> None:
        if offset in seen_offsets:
            return
        if offset < 0 or offset + 4 > len(data):
            return
        seen_offsets.add(offset)
        values.append(
            {
                "offset": offset,
                "type": "int32_le",
                "current_value": value,
                "new_value": value,  # user changes this
                "score": score,
                "why": why,
                "context": _ctx(decoded, offset),
            }
        )

    # 1) Ints near interesting decoded strings
    for m in INTERESTING_RE.finditer(decoded):
        name = m.group().decode("ascii", errors="ignore")
        start = max(0, m.start() - 64)
        end = min(len(data), m.end() + 96)
        for off in range(start, max(start, end - 3)):
            if off < m.end() and off + 4 > m.start():
                continue  # inside the string itself
            raw = data[off : off + 4]
            val = struct.unpack("<i", raw)[0]
            if val == 120 or 1 <= val <= 5000:
                if raw in (b"\x00\x00\x80\x3f", b"\x3f\x80\x00\x00"):
                    continue
                score = 50
                if val == 120:
                    score += 40
                if "day" in name.lower() or "front" in name.lower():
                    score += 30
                add_int(off, val, f"near decoded text '{name}'", score)

    # 2) Every literal int32 120 in the file (tagged)
    needle = struct.pack("<i", 120)
    start = 0
    count = 0
    while count < 300:
        idx = data.find(needle, start)
        if idx < 0:
            break
        count += 1
        start = idx + 1
        ctx = _ctx(decoded, idx).lower()
        score = 40
        if any(w in ctx for w in ("day", "front", "timer", "invas")):
            score = 90
        add_int(idx, 120, "raw int32 120 in save", score)

    values.sort(key=lambda v: (-v["score"], v["offset"]))
    # Cap to keep Notepad usable; keep high scores + a sample of the rest
    high = [v for v in values if v["score"] >= 70]
    rest = [v for v in values if v["score"] < 70][:80]
    trimmed = high + rest
    for i, v in enumerate(trimmed, 1):
        v["id"] = i
    return trimmed


def decrypt_save(save_path: Path, out_dir: Path | None = None) -> Path:
    """Decrypt one save into a folder the user can edit."""
    save_path = save_path.resolve()
    data = save_path.read_bytes()
    if out_dir is None:
        out_dir = save_path.parent / f"{save_path.name}_decrypted"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Raw backup of original bytes
    shutil.copy2(save_path, out_dir / "original_save.bak")

    # Human-readable decoded strings
    strings = extract_decoded_strings(data)
    lines = [
        "Project Wunderwaffe — decoded strings from save",
        f"Source: {save_path}",
        f"Size:   {len(data)} bytes",
        f"Cipher: each text byte in the save is stored as (real - 1)",
        "",
        "Browse this for names like Front / Days / Timer.",
        "Edit numbers in editable_values.json (not in this file).",
        "",
        "=" * 60,
        "",
    ]
    for off, text in strings:
        if any(k in text.lower() for k in ("day", "front", "timer", "invas", "time", "game", "east", "west")):
            mark = " << INTERESTING"
        else:
            mark = ""
        lines.append(f"@{off:08}  {text}{mark}")
    (out_dir / "decoded_strings.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Full decoded binary (string cipher applied to whole file).
    # Useful for hex editors; binary numbers may look shifted — prefer JSON edits.
    (out_dir / "full_plus1_decoded.bin").write_bytes(decode_plus1(data))

    editable = {
        "tool_version": VERSION,
        "save_file": str(save_path),
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "instructions": [
            "1. Change new_value on the rows you care about (example: 120 -> 9999999).",
            "2. Do NOT change offset or type.",
            "3. Save this JSON file.",
            "4. In the app, click Apply edits and select this folder (or this JSON).",
            "5. Load the save in-game.",
            "Higher score = more likely related to days/fronts.",
        ],
        "values": find_editable_values(data),
    }
    (out_dir / "editable_values.json").write_text(
        json.dumps(editable, indent=2), encoding="utf-8"
    )

    readme = f"""HOW TO EDIT THIS SAVE
=====================

Save file:
  {save_path}

Files in this folder:
  editable_values.json   ← EDIT THIS in Notepad
  decoded_strings.txt    ← search for Front / Days text
  original_save.bak      ← untouched copy of your save
  full_plus1_decoded.bin ← optional hex-editor view (advanced)

Steps:
  1. Open editable_values.json
  2. Find rows with score 70+ (or context mentioning days/front)
  3. Change "new_value"  (example 120 -> 9999999)
  4. Save the JSON
  5. Run the app again → Apply edits → pick this folder
  6. Start the game and load the save

If the game rejects the save, copy original_save.bak back over the save file.
"""
    (out_dir / "READ_ME.txt").write_text(readme, encoding="utf-8")

    # Pointer file so Apply can find the target save even if moved
    (out_dir / "source_path.txt").write_text(str(save_path), encoding="utf-8")
    return out_dir


def apply_edits(json_or_dir: Path) -> tuple[Path, list[str]]:
    """Apply editable_values.json back onto the save. Returns (save, log lines)."""
    json_or_dir = json_or_dir.resolve()
    if json_or_dir.is_dir():
        json_path = json_or_dir / "editable_values.json"
    else:
        json_path = json_or_dir
    if not json_path.exists():
        raise FileNotFoundError(f"Missing editable_values.json: {json_path}")

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    save_path = Path(payload.get("save_file") or "")
    if not save_path.exists():
        # fallback to source_path.txt next to json
        alt = json_path.parent / "source_path.txt"
        if alt.exists():
            save_path = Path(alt.read_text(encoding="utf-8").strip())
    if not save_path.exists():
        raise FileNotFoundError(
            f"Save file not found: {payload.get('save_file')}. "
            "Did it move? Update save_file in the JSON."
        )

    data = bytearray(save_path.read_bytes())
    bak = save_path.with_name(save_path.name + ".bak")
    if not bak.exists():
        shutil.copy2(save_path, bak)

    logs: list[str] = [f"Target save: {save_path}", f"Backup: {bak}"]
    changed = 0
    for row in payload.get("values", []):
        try:
            offset = int(row["offset"])
            old = int(row["current_value"])
            new = int(row["new_value"])
            typ = row.get("type", "int32_le")
        except Exception as exc:  # noqa: BLE001
            logs.append(f"SKIP bad row: {exc}")
            continue
        if new == old:
            continue
        if typ != "int32_le":
            logs.append(f"SKIP @{offset}: unsupported type {typ}")
            continue
        if offset < 0 or offset + 4 > len(data):
            logs.append(f"SKIP @{offset}: out of range")
            continue
        present = struct.unpack("<i", data[offset : offset + 4])[0]
        if present != old:
            logs.append(
                f"SKIP @{offset}: expected current_value {old}, file has {present}"
            )
            continue
        data[offset : offset + 4] = struct.pack("<i", new)
        changed += 1
        logs.append(f"SET @{offset}: {old} -> {new}  ({row.get('why', '')})")

    save_path.write_bytes(data)
    logs.append(f"Done. Wrote {changed} change(s) to {save_path}")
    return save_path, logs


def open_path(path: Path) -> None:
    path = path.resolve()
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------


def run_gui() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    class App(tk.Tk):
        def __init__(self) -> None:
            super().__init__()
            self.title("Project Wunderwaffe — Save Decrypt / Edit")
            self.geometry("780x480")
            self.minsize(640, 400)
            self.last_dir = guess_save_dir()
            self._build()

        def _build(self) -> None:
            pad = {"padx": 12, "pady": 8}
            frm = ttk.Frame(self)
            frm.pack(fill=tk.BOTH, expand=True)

            ttk.Label(
                frm,
                text="Decrypt a save → edit JSON yourself → apply",
                font=("Segoe UI", 14, "bold"),
            ).pack(anchor=tk.W, **pad)

            ttk.Label(
                frm,
                text=(
                    "Close the game first. Pick a file from SaveGame. "
                    "Then edit editable_values.json in Notepad "
                    "(change new_value, e.g. 120 → 9999999)."
                ),
                wraplength=740,
            ).pack(anchor=tk.W, **pad)

            btns = ttk.Frame(frm)
            btns.pack(fill=tk.X, **pad)
            ttk.Button(btns, text="1) Decrypt save…", command=self._decrypt).pack(
                side=tk.LEFT
            )
            ttk.Button(btns, text="2) Apply edits…", command=self._apply).pack(
                side=tk.LEFT, padx=8
            )
            ttk.Button(btns, text="Open SaveGame folder", command=self._open_saves).pack(
                side=tk.LEFT, padx=8
            )

            self.log = tk.Text(frm, wrap=tk.WORD)
            self.log.pack(fill=tk.BOTH, expand=True, **pad)
            self._append("Ready. Start with Decrypt save.")
            self._append(f"Default SaveGame: {self.last_dir}")

        def _append(self, text: str) -> None:
            self.log.insert(tk.END, text + "\n")
            self.log.see(tk.END)

        def _open_saves(self) -> None:
            d = guess_save_dir()
            d.mkdir(parents=True, exist_ok=True)
            open_path(d)

        def _decrypt(self) -> None:
            initial = str(self.last_dir if self.last_dir.exists() else Path.cwd())
            path = filedialog.askopenfilename(
                title="Select a Project Wunderwaffe save file",
                initialdir=initial,
                filetypes=[("All files", "*.*")],
            )
            if not path:
                return
            try:
                out = decrypt_save(Path(path))
                self.last_dir = Path(path).parent
                self._append(f"Decrypted → {out}")
                self._append("Open editable_values.json and change new_value, then Apply.")
                open_path(out)
                messagebox.showinfo(
                    "Decrypted",
                    f"Created folder:\n{out}\n\n"
                    "Edit editable_values.json in Notepad,\n"
                    "then click Apply edits.",
                )
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("Decrypt failed", str(exc))
                self._append(f"ERROR: {exc}")

        def _apply(self) -> None:
            initial = str(self.last_dir if self.last_dir.exists() else Path.cwd())
            # allow picking the json or the folder via a json file
            path = filedialog.askopenfilename(
                title="Select editable_values.json",
                initialdir=initial,
                filetypes=[("JSON", "*.json"), ("All files", "*.*")],
            )
            if not path:
                return
            try:
                save_path, logs = apply_edits(Path(path))
                for line in logs:
                    self._append(line)
                messagebox.showinfo(
                    "Applied",
                    f"Changes written to:\n{save_path}\n\n"
                    "A .bak backup was kept beside it.\n"
                    "Load this save in the game.",
                )
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("Apply failed", str(exc))
                self._append(f"ERROR: {exc}")

    App().mainloop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Decrypt Project Wunderwaffe saves for manual editing."
    )
    parser.add_argument("--decrypt", metavar="SAVE", help="Decrypt one save file")
    parser.add_argument(
        "--out",
        metavar="DIR",
        help="Output folder for --decrypt (default: <save>_decrypted)",
    )
    parser.add_argument(
        "--apply",
        metavar="JSON_OR_DIR",
        help="Apply editable_values.json back to the save",
    )
    args = parser.parse_args(argv)

    if args.decrypt:
        out = decrypt_save(Path(args.decrypt), Path(args.out) if args.out else None)
        print(f"Decrypted to: {out}")
        print("Edit editable_values.json, then run with --apply")
        return 0
    if args.apply:
        save_path, logs = apply_edits(Path(args.apply))
        print("\n".join(logs))
        print(f"Updated: {save_path}")
        return 0

    try:
        run_gui()
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"GUI failed ({exc})", file=sys.stderr)
        print('Try: python wunderwaffe_save_editor.py --decrypt "SAVEFILE"', file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
