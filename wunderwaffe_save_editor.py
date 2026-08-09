#!/usr/bin/env python3
"""
Project Wunderwaffe — Save Decrypt / Edit Tool (ALL-IN-ONE)

WHAT WENT WRONG BEFORE:
  Mid-game saves usually do NOT still contain the number 120.
  Also, naively "+1 every byte" turns random binary into garbage text.

WHAT THIS VERSION DOES:
  1. Finds real game path strings (stored as byte-1) and decodes them cleanly
  2. Lists LOTS of editable numbers (ints + floats) with nearby text
  3. You edit new_value in editable_values.json, then Apply

HOW TO USE:
  1. Close the game
  2. Double-click this file
  3. Decrypt save…  (pick a SaveGame file)
  4. Read readable_report.txt
  5. Edit editable_values.json  (change new_value)
  6. Apply edits…
  7. Load the save in-game

No pip packages. Python 3.10+.
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

VERSION = "3.1.0"

DEFAULT_GAME_ROOTS = [
    r"C:\Program Files (x86)\Steam\steamapps\common\Project Wunderwaffe",
    r"C:\Program Files\Steam\steamapps\common\Project Wunderwaffe",
    r"D:\SteamLibrary\steamapps\common\Project Wunderwaffe",
    r"E:\SteamLibrary\steamapps\common\Project Wunderwaffe",
]


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


def _looks_like_game_text(s: str) -> bool:
    if len(s) < 4:
        return False
    # paths / asset names after +1 decode
    if "/" in s or s.startswith("BP_") or s.startswith("/Game"):
        return True
    letters = sum(ch.isalpha() or ch in "_/." for ch in s)
    return letters / len(s) >= 0.75 and any(ch.isalpha() for ch in s)


def extract_real_strings(data: bytes) -> list[tuple[int, str, str]]:
    """Return (offset, raw_ascii, decoded_plus1) for likely game strings only."""
    # Find printable runs in the RAW file first (how they are stored)
    raw_re = re.compile(rb"[\x20-\x7e]{4,}")
    out: list[tuple[int, str, str]] = []
    seen: set[int] = set()
    for m in raw_re.finditer(data):
        raw = m.group().decode("ascii", errors="ignore")
        dec = decode_plus1(m.group()).decode("ascii", errors="ignore")
        if _looks_like_game_text(dec) or _looks_like_game_text(raw):
            if m.start() in seen:
                continue
            seen.add(m.start())
            out.append((m.start(), raw, dec))
    return out


def _nearest_string(
    strings: list[tuple[int, str, str]], offset: int, limit: int = 120
) -> str:
    best = ""
    best_dist = 10**9
    for off, _raw, dec in strings:
        dist = abs(off - offset)
        if dist < best_dist and dist <= limit:
            best_dist = dist
            best = dec
    return best


def find_editable_values(data: bytes) -> list[dict]:
    strings = extract_real_strings(data)
    values: list[dict] = []
    seen: set[tuple[int, str]] = set()

    def add(
        offset: int,
        typ: str,
        value: float | int,
        why: str,
        score: int,
    ) -> None:
        key = (offset, typ)
        if key in seen:
            return
        seen.add(key)
        nearby = _nearest_string(strings, offset)
        # boost if near useful words
        boost = 0
        low = nearby.lower()
        for word, pts in (
            ("day", 40),
            ("front", 40),
            ("timer", 35),
            ("time", 15),
            ("invas", 30),
            ("grid", 5),
            ("resource", 5),
            ("tile", 5),
        ):
            if word in low:
                boost += pts
        if value == 120 or value == 120.0:
            boost += 50
        # filename often embeds current day like pww_2100
        if isinstance(value, int) and 1000 <= value <= 5000:
            boost += 10
        values.append(
            {
                "offset": offset,
                "type": typ,
                "current_value": value if typ.startswith("float") else int(value),
                "new_value": value if typ.startswith("float") else int(value),
                "score": score + boost,
                "why": why,
                "nearby_text": nearby,
            }
        )

    # Exact day-ish constants at any alignment
    for const in (119, 120, 121):
        needle = struct.pack("<i", const)
        start = 0
        n = 0
        while n < 500:
            idx = data.find(needle, start)
            if idx < 0:
                break
            n += 1
            start = idx + 1
            score = 60 if const == 120 else 45
            add(idx, "int32_le", const, f"exact int {const}", score)

    for const in (119.0, 120.0, 121.0):
        needle = struct.pack("<f", const)
        start = 0
        n = 0
        while n < 500:
            idx = data.find(needle, start)
            if idx < 0:
                break
            n += 1
            start = idx + 1
            score = 70 if const == 120.0 else 50
            add(idx, "float32_le", const, f"exact float {const}", score)

    # Broad aligned scan for remaining plausible day counters
    for off in range(0, len(data) - 3, 4):
        val = struct.unpack_from("<i", data, off)[0]
        if val in (119, 120, 121):
            continue  # already added
        if 1 <= val <= 400:
            add(off, "int32_le", val, "aligned int32 1..400", 30)
        elif 1000 <= val <= 5000:
            add(off, "int32_le", val, "aligned int32 possible day#", 22)

    for off in range(0, len(data) - 3, 4):
        val = struct.unpack_from("<f", data, off)[0]
        if val != val or val in (float("inf"), float("-inf")):
            continue
        if val in (119.0, 120.0, 121.0) or val == 1.0:
            continue
        if 1.0 < val <= 400.0:
            add(off, "float32_le", round(val, 5), "aligned float 1..400", 28)

    values.sort(key=lambda v: (-v["score"], v["offset"]))

    # Keep: all high score, then a generous sample so the list is never empty
    # if the save has any numbers at all
    high = [v for v in values if v["score"] >= 50]
    mid = [v for v in values if 30 <= v["score"] < 50][:200]
    low = [v for v in values if v["score"] < 30][:100]
    trimmed = high + mid + low

    # If still somehow empty, dump first 50 ints in 1..10000 raw
    if not trimmed:
        for off in range(0, min(len(data) - 3, 200000), 4):
            val = struct.unpack_from("<i", data, off)[0]
            if 1 <= val <= 10000:
                add(off, "int32_le", val, "fallback scan", 10)
        trimmed = sorted(values, key=lambda v: (-v["score"], v["offset"]))[:300]

    for i, v in enumerate(trimmed, 1):
        v["id"] = i
    return trimmed


def write_readable_report(
    out_dir: Path,
    save_path: Path,
    data: bytes,
    strings: list[tuple[int, str, str]],
    values: list[dict],
) -> None:
    lines: list[str] = []
    lines.append("Project Wunderwaffe — READABLE SAVE REPORT")
    lines.append("=" * 60)
    lines.append(f"Save: {save_path}")
    lines.append(f"Size: {len(data)} bytes")
    lines.append(f"Tool: {VERSION}")
    lines.append("")
    lines.append("IMPORTANT")
    lines.append("-" * 40)
    lines.append("If this is a mid-game save, the timer is probably NOT 120 anymore.")
    lines.append("Look for small numbers near front/day text, or day numbers ~1000-5000.")
    lines.append("Edit editable_values.json (change new_value), then Apply.")
    lines.append("")
    lines.append("DECODED GAME STRINGS (clean)")
    lines.append("-" * 40)
    if not strings:
        lines.append("(none found — save may use a different encoding)")
    for off, raw, dec in strings[:500]:
        mark = ""
        low = dec.lower()
        if any(w in low for w in ("day", "front", "timer", "time", "invas")):
            mark = "  << LOOK HERE"
        lines.append(f"@{off:08}  {dec}{mark}")
        if raw != dec:
            lines.append(f"           (stored as: {raw})")
    lines.append("")
    lines.append("TOP EDIT CANDIDATES")
    lines.append("-" * 40)
    if not values:
        lines.append("(no candidates — send this save file to the developer)")
    for v in values[:80]:
        lines.append(
            f"id={v['id']:4} score={v['score']:3}  {v['type']:11}  "
            f"value={v['current_value']!s:<12} @{v['offset']}"
        )
        if v.get("nearby_text"):
            lines.append(f"         near: {v['nearby_text'][:100]}")
        lines.append(f"         why:  {v['why']}")
    lines.append("")
    lines.append("HEADER HEX (first 256 bytes)")
    lines.append("-" * 40)
    header = data[:256]
    for i in range(0, len(header), 16):
        chunk = header[i : i + 16]
        hx = " ".join(f"{b:02x}" for b in chunk)
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{i:08x}  {hx:<48}  {asc}")

    (out_dir / "readable_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def decrypt_save(save_path: Path, out_dir: Path | None = None) -> Path:
    save_path = save_path.resolve()
    data = save_path.read_bytes()
    if out_dir is None:
        out_dir = save_path.parent / f"{save_path.name}_decrypted"
    out_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy2(save_path, out_dir / "original_save.bak")
    strings = extract_real_strings(data)
    values = find_editable_values(data)
    write_readable_report(out_dir, save_path, data, strings, values)

    # Clean strings-only file
    s_lines = ["decoded_text\traw_stored\toffsets", "-" * 40]
    for off, raw, dec in strings:
        s_lines.append(f"{dec}\t{raw}\t@{off}")
    (out_dir / "decoded_strings.txt").write_text("\n".join(s_lines) + "\n", encoding="utf-8")

    editable = {
        "tool_version": VERSION,
        "save_file": str(save_path),
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "instructions": [
            "Read readable_report.txt first.",
            "Change new_value on rows you want (example: 45 -> 9999999).",
            "Do NOT change offset or type.",
            "Save this JSON, then click Apply edits in the app.",
            "Higher score = more likely related to days/fronts.",
            "Mid-game saves often no longer contain 120.",
        ],
        "values": values,
    }
    (out_dir / "editable_values.json").write_text(
        json.dumps(editable, indent=2), encoding="utf-8"
    )

    (out_dir / "READ_ME.txt").write_text(
        f"""HOW TO EDIT
===========
1. Open readable_report.txt  (this is the clean summary)
2. Open editable_values.json in Notepad
3. Change "new_value" on the rows you want
4. Save JSON → run app → Apply edits → pick this JSON
5. Load the save in-game

Save: {save_path}
Candidates found: {len(values)}
Decoded strings found: {len(strings)}

If values is empty or nothing looks like a day timer, upload the
original save file (and this folder) so it can be reverse-engineered.
""",
        encoding="utf-8",
    )
    (out_dir / "source_path.txt").write_text(str(save_path), encoding="utf-8")
    return out_dir


def apply_edits(json_or_dir: Path) -> tuple[Path, list[str]]:
    json_or_dir = json_or_dir.resolve()
    json_path = (
        json_or_dir / "editable_values.json" if json_or_dir.is_dir() else json_or_dir
    )
    if not json_path.exists():
        raise FileNotFoundError(f"Missing editable_values.json: {json_path}")

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    save_path = Path(payload.get("save_file") or "")
    if not save_path.exists():
        alt = json_path.parent / "source_path.txt"
        if alt.exists():
            save_path = Path(alt.read_text(encoding="utf-8").strip())
    if not save_path.exists():
        raise FileNotFoundError(f"Save file not found: {payload.get('save_file')}")

    data = bytearray(save_path.read_bytes())
    bak = save_path.with_name(save_path.name + ".bak")
    if not bak.exists():
        shutil.copy2(save_path, bak)

    logs = [f"Target save: {save_path}", f"Backup: {bak}"]
    changed = 0
    for row in payload.get("values", []):
        try:
            offset = int(row["offset"])
            old = row["current_value"]
            new = row["new_value"]
            typ = row.get("type", "int32_le")
        except Exception as exc:  # noqa: BLE001
            logs.append(f"SKIP bad row: {exc}")
            continue
        if new == old:
            continue
        if offset < 0 or offset + 4 > len(data):
            logs.append(f"SKIP @{offset}: out of range")
            continue
        if typ == "int32_le":
            present = struct.unpack_from("<i", data, offset)[0]
            if present != int(old):
                logs.append(f"SKIP @{offset}: expected {old}, file has {present}")
                continue
            struct.pack_into("<i", data, offset, int(new))
        elif typ == "float32_le":
            present = struct.unpack_from("<f", data, offset)[0]
            if abs(present - float(old)) > 1e-4:
                logs.append(f"SKIP @{offset}: expected {old}, file has {present}")
                continue
            struct.pack_into("<f", data, offset, float(new))
        else:
            logs.append(f"SKIP @{offset}: unsupported type {typ}")
            continue
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


def run_gui() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    class App(tk.Tk):
        def __init__(self) -> None:
            super().__init__()
            self.title("Project Wunderwaffe — Save Decrypt / Edit")
            self.geometry("820x520")
            self.minsize(640, 400)
            self.last_dir = guess_save_dir()
            self._build()

        def _build(self) -> None:
            pad = {"padx": 12, "pady": 8}
            frm = ttk.Frame(self)
            frm.pack(fill=tk.BOTH, expand=True)
            ttk.Label(
                frm,
                text="Decrypt save → read report → edit JSON → apply",
                font=("Segoe UI", 14, "bold"),
            ).pack(anchor=tk.W, **pad)
            ttk.Label(
                frm,
                text=(
                    "Close the game first. After decrypt, open readable_report.txt. "
                    "Then edit new_value in editable_values.json."
                ),
                wraplength=780,
            ).pack(anchor=tk.W, **pad)

            btns = ttk.Frame(frm)
            btns.pack(fill=tk.X, **pad)
            ttk.Button(btns, text="1) Decrypt save…", command=self._decrypt).pack(
                side=tk.LEFT
            )
            ttk.Button(btns, text="2) Apply edits…", command=self._apply).pack(
                side=tk.LEFT, padx=8
            )
            ttk.Button(
                btns, text="Open SaveGame folder", command=self._open_saves
            ).pack(side=tk.LEFT, padx=8)

            self.log = tk.Text(frm, wrap=tk.WORD)
            self.log.pack(fill=tk.BOTH, expand=True, **pad)
            self._append("Ready.")
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
                payload = json.loads(
                    (out / "editable_values.json").read_text(encoding="utf-8")
                )
                n = len(payload.get("values", []))
                self._append(f"Decrypted → {out}")
                self._append(f"Candidates: {n}")
                self._append("Open readable_report.txt first.")
                open_path(out)
                messagebox.showinfo(
                    "Decrypted",
                    f"Created:\n{out}\n\n"
                    f"Editable candidates: {n}\n\n"
                    "Open readable_report.txt, then edit editable_values.json.",
                )
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("Decrypt failed", str(exc))
                self._append(f"ERROR: {exc}")

        def _apply(self) -> None:
            initial = str(self.last_dir if self.last_dir.exists() else Path.cwd())
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
                    f"Changes written to:\n{save_path}\n\nLoad this save in the game.",
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
    parser.add_argument("--out", metavar="DIR", help="Output folder for --decrypt")
    parser.add_argument(
        "--apply", metavar="JSON_OR_DIR", help="Apply editable_values.json"
    )
    args = parser.parse_args(argv)

    if args.decrypt:
        out = decrypt_save(Path(args.decrypt), Path(args.out) if args.out else None)
        print(f"Decrypted to: {out}")
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
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
