#!/usr/bin/env python3
"""
Project Wunderwaffe — Phase 2 Day Timer Patcher (ALL-IN-ONE)

From your Phase 1 scan:
  - Game is Unreal Engine
  - Important data is in SaveGame + the big .pak / Shipping.exe
  - Save strings are stored with each byte = real_byte - 1
    (e.g. F`ld.Ldbg`mhbr → Game/Mechanics)

WHAT THIS DOES:
  1. Finds your save files
  2. Decodes them and looks for Front / Days fields
  3. Patches those day values to 9999999
  4. Makes a .bak backup first
  5. Can launch the game

HOW TO USE:
  1. Close the game
  2. Double-click this file (or: python wunderwaffe_patcher.py)
  3. Click Analyze → review hits → Patch saves → Launch game

No pip packages needed. Python 3.10+ only.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import struct
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

VERSION = "2.0.0"
NEW_DAYS = 9_999_999
TARGET_DEFAULT = 120

DEFAULT_GAME_ROOTS = [
    r"C:\Program Files (x86)\Steam\steamapps\common\Project Wunderwaffe",
    r"C:\Program Files\Steam\steamapps\common\Project Wunderwaffe",
    r"D:\SteamLibrary\steamapps\common\Project Wunderwaffe",
    r"E:\SteamLibrary\steamapps\common\Project Wunderwaffe",
]

DAY_NAME_RE = re.compile(
    rb"(?i)(front.?days|days.?left|day.?left|max.?days|game.?days|"
    rb"days.?remaining|time.?limit|deadline|invasion.?days|"
    rb"start.?days|remaining.?days|daysuntil|daycount|"
    rb"east.?front|west.?front|north.?west|south.?west|"
    rb"frontday|daystogo|timer.?days)"
)

# Broader names still worth showing
SOFT_NAME_RE = re.compile(
    rb"(?i)(front|days|day|timer|deadline|invasion|countdown)"
)


@dataclass
class Candidate:
    path: str
    offset: int
    size: int  # 4 or 8
    endian: str  # '<' or '>'
    old_value: int
    score: int
    reason: str
    context: str


def guess_game_root() -> str:
    for c in DEFAULT_GAME_ROOTS:
        if Path(c).exists():
            return c
    return DEFAULT_GAME_ROOTS[0]


def save_dir_for(game_root: Path) -> Path:
    direct = game_root / "ProjectWunderwaffe" / "SaveGame"
    if direct.exists():
        return direct
    alt = game_root / "SaveGame"
    return alt if alt.exists() else direct


def shipping_exe(game_root: Path) -> Path | None:
    p = (
        game_root
        / "ProjectWunderwaffe"
        / "Binaries"
        / "Win64"
        / "ProjectWunderwaffe-Win64-Shipping.exe"
    )
    return p if p.exists() else None


def launcher_exe(game_root: Path) -> Path | None:
    for name in ("ProjectWunderwaffe.exe", "Project Wunderwaffe.exe"):
        p = game_root / name
        if p.exists():
            return p
    return shipping_exe(game_root)


def decode_plus1(data: bytes) -> bytes:
    """Save strings appear stored as (real_byte - 1)."""
    return bytes((b + 1) & 0xFF for b in data)


def _ascii_ctx(data: bytes, center: int, radius: int = 48) -> str:
    start = max(0, center - radius)
    end = min(len(data), center + radius)
    return "".join(chr(b) if 32 <= b < 127 else "." for b in data[start:end])


def _find_ints_near(
    data: bytes,
    center: int,
    window: int = 96,
    prefer_values: set[int] | None = None,
) -> list[tuple[int, int, str, int]]:
    """Return list of (offset, size, endian, value) near center.

    Windows Unreal saves are little-endian — do not accept big-endian
    false positives (e.g. padding+0x78 looking like BE 120).
    """
    prefer_values = prefer_values or set()
    start = max(0, center - window)
    end = min(len(data), center + window + 4)
    found: list[tuple[int, int, str, int]] = []
    endian = "<"
    for off in range(start, max(start, end - 3)):
        raw = data[off : off + 4]
        if len(raw) < 4:
            continue
        val = struct.unpack(f"{endian}i", raw)[0]
        # Plausible day counters / the known default
        if val == TARGET_DEFAULT or 1 <= val <= 5000 or val in prefer_values:
            # skip obvious float32 bit patterns commonly around 1.0
            if raw in (b"\x00\x00\x80\x3f", b"\x3f\x80\x00\x00"):
                continue
            # skip tiny letter-like leftovers (e.g. ASCII codepoints)
            if 1 <= val <= 31:
                continue
            found.append((off, 4, endian, val))
    # prefer exact 120, then values in typical remaining-day range
    found.sort(
        key=lambda t: (
            0 if t[3] == TARGET_DEFAULT else 1,
            0 if 1 <= t[3] <= 365 else 1,
            abs(t[0] - center),
        )
    )
    # dedupe offsets
    seen = set()
    out = []
    for item in found:
        if item[0] in seen:
            continue
        seen.add(item[0])
        out.append(item)
    return out[:12]


def analyze_save(path: Path) -> list[Candidate]:
    data = path.read_bytes()
    decoded = decode_plus1(data)
    cands: list[Candidate] = []

    # Strong matches on decoded strings
    for cre, base_score, label in (
        (DAY_NAME_RE, 100, "strong day/front name"),
        (SOFT_NAME_RE, 55, "soft day/front name"),
    ):
        for m in cre.finditer(decoded):
            name = m.group().decode("ascii", errors="ignore")
            ints = _find_ints_near(data, m.start())
            for off, size, endian, val in ints:
                # ignore ints that overlap the name bytes themselves
                if off < m.end() and off + size > m.start():
                    continue
                score = base_score
                if val == TARGET_DEFAULT:
                    score += 40
                if 1 <= val <= 200:
                    score += 15
                if "front" in name.lower() and "day" in name.lower():
                    score += 30
                cands.append(
                    Candidate(
                        path=str(path),
                        offset=off,
                        size=size,
                        endian=endian,
                        old_value=val,
                        score=score,
                        reason=f"{label}: '{name}' (save decode +1)",
                        context=_ascii_ctx(decoded, m.start()),
                    )
                )

    # Also: raw ASCII "120" next to decoded front/day context is rare; scan for
    # exact int32 120 occurrences whose decoded neighborhood mentions front/day.
    needle = struct.pack("<i", TARGET_DEFAULT)
    start = 0
    hits = 0
    while hits < 200:
        idx = data.find(needle, start)
        if idx < 0:
            break
        hits += 1
        start = idx + 1
        ctx = _ascii_ctx(decoded, idx).lower()
        if "front" in ctx or "day" in ctx or "timer" in ctx or "invas" in ctx:
            cands.append(
                Candidate(
                    path=str(path),
                    offset=idx,
                    size=4,
                    endian="<",
                    old_value=TARGET_DEFAULT,
                    score=90,
                    reason="int32_LE=120 near decoded front/day text",
                    context=_ascii_ctx(decoded, idx),
                )
            )

    # Dedup by offset, keep best score
    best: dict[int, Candidate] = {}
    for c in cands:
        prev = best.get(c.offset)
        if prev is None or c.score > prev.score:
            best[c.offset] = c
    return sorted(best.values(), key=lambda c: (-c.score, c.offset))


def analyze_exe_defaults(exe: Path, max_bytes: int | None = None) -> list[Candidate]:
    """Search shipping exe for Front/Days strings near immediate value 120."""
    size = exe.stat().st_size
    # Read in chunks to handle ~84MB exe
    cands: list[Candidate] = []
    chunk = 8 * 1024 * 1024
    overlap = 4096
    keywords = [
        b"FrontDays",
        b"DaysLeft",
        b"MaxDays",
        b"GameDays",
        b"DaysRemaining",
        b"front days",
        b"FrontDay",
        b"TimeLimit",
        "FrontDays".encode("utf-16le"),
        "DaysLeft".encode("utf-16le"),
        "MaxDays".encode("utf-16le"),
        "Days".encode("utf-16le"),
        "Front".encode("utf-16le"),
    ]
    imm120 = [
        (b"\xb8\x78\x00\x00\x00", "mov eax,120"),  # B8 78 00 00 00
        (b"\xb9\x78\x00\x00\x00", "mov ecx,120"),
        (b"\xba\x78\x00\x00\x00", "mov edx,120"),
        (b"\xbf\x78\x00\x00\x00", "mov edi,120"),
        (b"\xbe\x78\x00\x00\x00", "mov esi,120"),
        (b"\x41\xb8\x78\x00\x00\x00", "mov r8d,120"),
        (b"\x41\xb9\x78\x00\x00\x00", "mov r9d,120"),
        (b"\xc7\x00\x78\x00\x00\x00", "mov [rax],120 approx"),
        (struct.pack("<i", 120), "raw int32 120"),
    ]

    pos = 0
    buf = b""
    with exe.open("rb") as fh:
        while True:
            piece = fh.read(chunk)
            if not piece:
                break
            data = buf + piece
            base = pos - len(buf)
            # keyword hits
            for kw in keywords:
                start = 0
                local = 0
                while local < 30:
                    idx = data.find(kw, start)
                    if idx < 0:
                        break
                    local += 1
                    start = idx + 1
                    abs_off = base + idx
                    # look for 120 immediates nearby in this window
                    window = data[max(0, idx - 128) : idx + 128]
                    for needle, why in imm120:
                        j = window.find(needle)
                        if j >= 0:
                            # offset of the 120 value bytes inside needle
                            if needle == struct.pack("<i", 120):
                                val_off = base + max(0, idx - 128) + j
                                patch_size = 4
                            else:
                                # value starts after opcode byte(s)
                                # find 78 00 00 00 inside needle
                                rel = needle.find(b"\x78\x00\x00\x00")
                                val_off = base + max(0, idx - 128) + j + rel
                                patch_size = 4
                            try:
                                name = kw.decode("utf-16le") if b"\x00" in kw[:4] else kw.decode()
                            except Exception:
                                name = repr(kw)
                            cands.append(
                                Candidate(
                                    path=str(exe),
                                    offset=val_off,
                                    size=patch_size,
                                    endian="<",
                                    old_value=TARGET_DEFAULT,
                                    score=120,
                                    reason=f"exe '{name}' near {why}",
                                    context=_ascii_ctx(data, idx),
                                )
                            )
            buf = data[-overlap:]
            pos += len(piece)
            if max_bytes and pos >= max_bytes:
                break

    best: dict[int, Candidate] = {}
    for c in cands:
        prev = best.get(c.offset)
        if prev is None or c.score > prev.score:
            best[c.offset] = c
    return sorted(best.values(), key=lambda c: (-c.score, c.offset))


def patch_candidates(
    cands: list[Candidate],
    new_value: int = NEW_DAYS,
    min_score: int = 80,
) -> list[str]:
    """Patch files in-place (with .bak). Returns log lines."""
    logs: list[str] = []
    by_file: dict[str, list[Candidate]] = {}
    for c in cands:
        if c.score < min_score:
            continue
        by_file.setdefault(c.path, []).append(c)

    for fpath, items in by_file.items():
        path = Path(fpath)
        bak = path.with_suffix(path.suffix + ".bak")
        if not bak.exists():
            shutil.copy2(path, bak)
            logs.append(f"Backup: {bak}")
        else:
            logs.append(f"Backup exists: {bak}")

        data = bytearray(path.read_bytes())
        patched = 0
        # Avoid overlapping writes; patch highest score first
        used = set()
        ordered = sorted(items, key=lambda x: (-x.score, 0 if x.endian == "<" else 1, x.offset))
        for c in ordered:
            if any(o in used for o in range(c.offset, c.offset + c.size)):
                continue
            old = struct.unpack(f"{c.endian}i", data[c.offset : c.offset + 4])[0]
            if old != c.old_value:
                logs.append(
                    f"SKIP {path.name} @{c.offset}: expected {c.old_value}, found {old}"
                )
                continue
            data[c.offset : c.offset + 4] = struct.pack(f"{c.endian}i", new_value)
            for o in range(c.offset, c.offset + 4):
                used.add(o)
            patched += 1
            logs.append(
                f"PATCH {path.name} @{c.offset}: {old} -> {new_value} ({c.reason})"
            )
        path.write_bytes(data)
        logs.append(f"Wrote {path} ({patched} values)")
    return logs


def iter_saves(save_root: Path) -> list[Path]:
    if not save_root.exists():
        return []
    out: list[Path] = []
    for p in save_root.rglob("*"):
        if not p.is_file():
            continue
        if p.name.endswith(".bak") or p.suffix.lower() == ".vdf":
            continue
        if p.stat().st_size < 64:
            continue
        out.append(p)
    return sorted(out)


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------


def run_gui() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    class App(tk.Tk):
        def __init__(self) -> None:
            super().__init__()
            self.title("Project Wunderwaffe — Day Patcher (Phase 2)")
            self.geometry("900x620")
            self.minsize(760, 520)
            self.game_var = tk.StringVar(value=guess_game_root())
            self.status_var = tk.StringVar(value="Click Analyze saves.")
            self.candidates: list[Candidate] = []
            self._worker: threading.Thread | None = None
            self._build()

        def _build(self) -> None:
            pad = {"padx": 12, "pady": 6}
            frm = ttk.Frame(self)
            frm.pack(fill=tk.BOTH, expand=True)

            ttk.Label(
                frm,
                text="Phase 2: set front/day timer to 9999999",
                font=("Segoe UI", 14, "bold"),
            ).pack(anchor=tk.W, **pad)
            ttk.Label(
                frm,
                text=(
                    "Close the game first. This patches SaveGame files (and optionally "
                    "the exe default). Backups are created as *.bak."
                ),
                wraplength=860,
            ).pack(anchor=tk.W, **pad)

            row = ttk.Frame(frm)
            row.pack(fill=tk.X, **pad)
            ttk.Label(row, text="Game folder:").pack(side=tk.LEFT)
            ttk.Entry(row, textvariable=self.game_var).pack(
                side=tk.LEFT, fill=tk.X, expand=True, padx=8
            )
            ttk.Button(row, text="Browse…", command=self._browse).pack(side=tk.LEFT)

            btns = ttk.Frame(frm)
            btns.pack(fill=tk.X, **pad)
            self.analyze_btn = ttk.Button(
                btns, text="1) Analyze saves", command=self._analyze_saves
            )
            self.analyze_btn.pack(side=tk.LEFT)
            self.exe_btn = ttk.Button(
                btns, text="Analyze exe default", command=self._analyze_exe
            )
            self.exe_btn.pack(side=tk.LEFT, padx=8)
            self.patch_btn = ttk.Button(
                btns, text="2) Patch selected/high scores", command=self._patch
            )
            self.patch_btn.pack(side=tk.LEFT, padx=8)
            ttk.Button(btns, text="3) Launch game", command=self._launch).pack(
                side=tk.LEFT, padx=8
            )

            ttk.Label(frm, textvariable=self.status_var).pack(anchor=tk.W, **pad)

            self.list = tk.Listbox(frm, height=14)
            self.list.pack(fill=tk.BOTH, expand=True, **pad)

            self.log = tk.Text(frm, height=10, wrap=tk.WORD)
            self.log.pack(fill=tk.BOTH, expand=True, **pad)
            self._append(
                "Tip: start with Analyze saves. High-score rows (80+) are patched.\n"
                "If a patch breaks a save, restore the .bak file next to it."
            )

        def _append(self, text: str) -> None:
            self.log.insert(tk.END, text + "\n")
            self.log.see(tk.END)

        def _browse(self) -> None:
            chosen = filedialog.askdirectory(title="Select Project Wunderwaffe folder")
            if chosen:
                self.game_var.set(chosen)

        def _set_busy(self, busy: bool) -> None:
            state = tk.DISABLED if busy else tk.NORMAL
            self.analyze_btn.configure(state=state)
            self.exe_btn.configure(state=state)
            self.patch_btn.configure(state=state)

        def _refresh_list(self) -> None:
            self.list.delete(0, tk.END)
            for i, c in enumerate(self.candidates[:300], 1):
                self.list.insert(
                    tk.END,
                    f"{i:03d} score={c.score:3d}  val={c.old_value:<8}  "
                    f"@{c.offset:<8}  {Path(c.path).name}  | {c.reason}",
                )

        def _analyze_saves(self) -> None:
            if self._worker and self._worker.is_alive():
                return
            root = Path(self.game_var.get().strip())
            sdir = save_dir_for(root)
            if not sdir.exists():
                messagebox.showerror("Missing", f"SaveGame folder not found:\n{sdir}")
                return
            self._set_busy(True)
            self.status_var.set(f"Analyzing {sdir} …")

            def work() -> None:
                try:
                    saves = iter_saves(sdir)
                    all_c: list[Candidate] = []
                    for sp in saves:
                        all_c.extend(analyze_save(sp))
                    all_c.sort(key=lambda c: (-c.score, c.path, c.offset))
                    self.after(0, lambda: self._done_analyze(all_c, None))
                except Exception as exc:  # noqa: BLE001
                    self.after(0, lambda: self._done_analyze([], exc))

            self._worker = threading.Thread(target=work, daemon=True)
            self._worker.start()

        def _analyze_exe(self) -> None:
            if self._worker and self._worker.is_alive():
                return
            root = Path(self.game_var.get().strip())
            exe = shipping_exe(root)
            if exe is None:
                messagebox.showerror("Missing", "Shipping exe not found.")
                return
            self._set_busy(True)
            self.status_var.set(f"Scanning {exe.name} (can take a minute)…")

            def work() -> None:
                try:
                    found = analyze_exe_defaults(exe)
                    self.after(0, lambda: self._done_analyze(found, None, append=True))
                except Exception as exc:  # noqa: BLE001
                    self.after(0, lambda: self._done_analyze([], exc))

            self._worker = threading.Thread(target=work, daemon=True)
            self._worker.start()

        def _done_analyze(
            self, cands: list[Candidate], err, append: bool = False
        ) -> None:
            self._set_busy(False)
            if err is not None:
                self.status_var.set("Analyze failed")
                self._append(f"ERROR: {err}")
                messagebox.showerror("Analyze failed", str(err))
                return
            if append:
                self.candidates.extend(cands)
                self.candidates.sort(key=lambda c: (-c.score, c.path, c.offset))
            else:
                self.candidates = cands
            self._refresh_list()
            hi = sum(1 for c in self.candidates if c.score >= 80)
            self.status_var.set(
                f"Found {len(self.candidates)} candidates ({hi} high-score ≥80)."
            )
            self._append(self.status_var.get())
            if not self.candidates:
                self._append(
                    "No clear day fields found. Try Analyze exe default, "
                    "or send a save file for manual inspection."
                )

        def _patch(self) -> None:
            if not self.candidates:
                messagebox.showinfo("Nothing to patch", "Run Analyze first.")
                return
            hi = [c for c in self.candidates if c.score >= 80]
            if not hi:
                if not messagebox.askyesno(
                    "Low confidence",
                    "No high-score candidates (≥80).\nPatch ALL listed candidates anyway?",
                ):
                    return
                hi = list(self.candidates)
            elif not messagebox.askyesno(
                "Confirm patch",
                f"Patch {len(hi)} high-score value(s) to {NEW_DAYS}?\n"
                "Backups (*.bak) will be created.",
            ):
                return
            try:
                logs = patch_candidates(hi, NEW_DAYS, min_score=min(c.score for c in hi))
                for line in logs:
                    self._append(line)
                self.status_var.set("Patch complete.")
                messagebox.showinfo("Done", "Patch complete.\nYou can Launch game now.")
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("Patch failed", str(exc))
                self._append(f"ERROR: {exc}")

        def _launch(self) -> None:
            root = Path(self.game_var.get().strip())
            exe = launcher_exe(root)
            if exe is None:
                messagebox.showerror("Missing", "Game exe not found.")
                return
            try:
                if sys.platform.startswith("win"):
                    os.startfile(str(exe))  # type: ignore[attr-defined]
                else:
                    subprocess.Popen([str(exe)])
                self._append(f"Launched: {exe}")
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("Launch failed", str(exc))

    App().mainloop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Patch Project Wunderwaffe front/day timer to 9999999."
    )
    parser.add_argument("--game", default=guess_game_root(), help="Game install folder")
    parser.add_argument(
        "--cli-analyze",
        action="store_true",
        help="Analyze saves and print candidates (no GUI)",
    )
    parser.add_argument(
        "--cli-patch",
        action="store_true",
        help="Analyze + patch high-score save candidates (no GUI)",
    )
    parser.add_argument("--exe-scan", action="store_true", help="Also scan shipping exe")
    parser.add_argument("--launch", action="store_true", help="Launch game after patch")
    args = parser.parse_args(argv)

    if not args.cli_analyze and not args.cli_patch:
        try:
            run_gui()
            return 0
        except Exception as exc:  # noqa: BLE001
            print(f"GUI failed ({exc}). Use --cli-analyze / --cli-patch.", file=sys.stderr)
            return 1

    root = Path(args.game)
    sdir = save_dir_for(root)
    print(f"Game: {root}")
    print(f"Saves: {sdir}")
    cands: list[Candidate] = []
    for sp in iter_saves(sdir):
        print(f"Analyzing {sp.name} …")
        cands.extend(analyze_save(sp))
    if args.exe_scan:
        exe = shipping_exe(root)
        if exe:
            print(f"Scanning {exe.name} …")
            cands.extend(analyze_exe_defaults(exe))
    cands.sort(key=lambda c: (-c.score, c.path, c.offset))
    print(f"\nCandidates: {len(cands)}")
    for i, c in enumerate(cands[:80], 1):
        print(
            f"{i:02d}. score={c.score} val={c.old_value} @{c.offset} "
            f"{Path(c.path).name} | {c.reason}"
        )
        print(f"    {c.context[:120]}")

    if args.cli_patch:
        hi = [c for c in cands if c.score >= 80]
        print(f"\nPatching {len(hi)} high-score candidates → {NEW_DAYS}")
        for line in patch_candidates(hi):
            print(line)

    if args.launch:
        exe = launcher_exe(root)
        if exe:
            print(f"Launching {exe}")
            if sys.platform.startswith("win"):
                os.startfile(str(exe))  # type: ignore[attr-defined]
            else:
                subprocess.Popen([str(exe)])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
