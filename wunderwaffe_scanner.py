#!/usr/bin/env python3
"""
Project Wunderwaffe — Phase 1 Timer Scanner (ALL-IN-ONE)

HOW TO USE (Windows):
  1. Install Python 3.10+ from https://www.python.org/downloads/
     (check "Add Python to PATH")
  2. Double-click this file, OR open a terminal in this folder and run:
       python wunderwaffe_scanner.py
  3. Browse to:
       C:\\Program Files (x86)\\Steam\\steamapps\\common\\Project Wunderwaffe
  4. Click Start Scan
  5. Send BOTH log files from the scan_logs folder (.txt and .json)

This script does NOT change any game files.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import threading
import time
import zlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

VERSION = "1.1.0"
TARGET_DAYS = 120

# ---------------------------------------------------------------------------
# Search patterns
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

ProgressCb = Callable[[str, float], None]

DEFAULT_SKIP_SUFFIXES = {
    ".mp4",
    ".webm",
    ".avi",
    ".mov",
    ".wav",
    ".mp3",
    ".ogg",
    ".flac",
    ".png",
    ".jpg",
    ".jpeg",
    ".tga",
    ".dds",
    ".psd",
    ".bmp",
    ".gif",
    ".ttf",
    ".otf",
    ".woff",
    ".woff2",
}

TEXTISH_SUFFIXES = {
    ".txt",
    ".json",
    ".xml",
    ".yml",
    ".yaml",
    ".ini",
    ".cfg",
    ".conf",
    ".csv",
    ".log",
    ".md",
    ".cs",
    ".lua",
    ".js",
    ".ts",
    ".html",
    ".htm",
    ".assets",
}

MAX_CONTEXT = 96
MAX_HITS_PER_FILE = 80
MAX_FILE_BYTES = 80 * 1024 * 1024

DEFAULT_STEAM_CANDIDATES = [
    r"C:\Program Files (x86)\Steam\steamapps\common\Project Wunderwaffe",
    r"C:\Program Files\Steam\steamapps\common\Project Wunderwaffe",
    r"D:\SteamLibrary\steamapps\common\Project Wunderwaffe",
    r"E:\SteamLibrary\steamapps\common\Project Wunderwaffe",
]


@dataclass
class Hit:
    path: str
    offset: int
    kind: str
    score: int
    snippet: str
    notes: str = ""


@dataclass
class FileReport:
    path: str
    size: int
    sha256_prefix: str
    kind: str
    decoded_as: list[str] = field(default_factory=list)
    hits: list[Hit] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skipped_reason: str | None = None


@dataclass
class ScanReport:
    created_utc: str
    game_root: str
    scanner_version: str
    target_days: int
    engine_guess: list[str]
    files_scanned: int
    files_skipped: int
    total_hits: int
    top_candidates: list[Hit]
    files: list[FileReport]
    notes: list[str] = field(default_factory=list)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _script_dir() -> Path:
    return Path(__file__).resolve().parent


def guess_default_root() -> str:
    for candidate in DEFAULT_STEAM_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return DEFAULT_STEAM_CANDIDATES[0]


def guess_engine(root: Path) -> list[str]:
    guesses: list[str] = []
    shallow = {p.name.lower() for p in root.glob("*")}
    shallow |= {p.name.lower() for p in root.glob("*/*")}
    # Sample a limited set of deeper names without walking the whole tree twice
    names = set(shallow)
    try:
        for i, p in enumerate(root.rglob("*")):
            if p.is_file():
                names.add(p.name.lower())
            if i > 5000:
                break
    except OSError:
        pass

    if "unityplayer.dll" in names or any(n.endswith("_data") for n in shallow):
        guesses.append("Unity")
    if any(n.endswith(".pak") for n in names):
        guesses.append("Unreal (possible)")
    if "project.godot" in names:
        guesses.append("Godot")
    if any(n.endswith(".uasset") for n in names):
        guesses.append("Unreal assets")
    if "wunderwaffe" in str(root).lower():
        guesses.append("Project Wunderwaffe install/save tree")
    if not guesses:
        guesses.append("Unknown / custom")
    return guesses


def classify_file(path: Path) -> str:
    name = path.name.lower()
    suffix = path.suffix.lower()
    if suffix in TEXTISH_SUFFIXES:
        return "textish"
    if suffix in {".dll", ".exe"}:
        return "native_binary"
    if suffix in {".assets", ".resource", ".ress"} or name in {
        "globalgamemanagers",
        "level0",
        "resources.assets",
    }:
        return "unity_asset"
    if suffix in {".pak", ".uasset", ".uexp", ".ubulk"}:
        return "unreal_asset"
    if suffix in {".sav", ".save", ".dat", ".bin"} or "save" in name:
        return "save_or_data"
    if suffix in DEFAULT_SKIP_SUFFIXES:
        return "media_skip"
    return "binary"


def _hex_preview(data: bytes, center: int, radius: int = 24) -> str:
    start = max(0, center - radius)
    end = min(len(data), center + radius)
    return data[start:end].hex(" ")


def _ascii_preview(data: bytes, center: int, radius: int = MAX_CONTEXT) -> str:
    start = max(0, center - radius)
    end = min(len(data), center + radius)
    chunk = data[start:end]
    return "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)


def _find_all(data: bytes, needle: bytes, limit: int = 40) -> list[int]:
    out: list[int] = []
    start = 0
    while True:
        idx = data.find(needle, start)
        if idx < 0:
            break
        out.append(idx)
        if len(out) >= limit:
            break
        start = idx + 1
    return out


def _inflate_candidates(data: bytes) -> list[tuple[str, bytes]]:
    out: list[tuple[str, bytes]] = []
    if len(data) >= 2 and data[:2] == b"\x1f\x8b":
        try:
            out.append(("gzip", gzip.decompress(data)))
        except Exception:
            pass
    for label, wbits in (("zlib", 15), ("raw_deflate", -15), ("gzip_stream", 31)):
        try:
            out.append((label, zlib.decompress(data, wbits)))
        except Exception:
            continue
    for magic in (b"\x78\x01", b"\x78\x9c", b"\x78\xda"):
        pos = data.find(magic)
        if 0 <= pos < len(data) - 8:
            try:
                out.append((f"embedded_zlib@{pos}", zlib.decompress(data[pos:])))
            except Exception:
                pass
    return out


def _extract_strings(data: bytes, min_len: int = 4) -> list[str]:
    ascii_re = re.compile(rb"[\x20-\x7e]{%d,}" % min_len)
    utf16_re = re.compile((rb"(?:[\x20-\x7e]\x00){%d,}" % min_len))
    strings: list[str] = []
    for m in ascii_re.finditer(data):
        strings.append(m.group().decode("ascii", errors="ignore"))
    for m in utf16_re.finditer(data):
        try:
            strings.append(m.group().decode("utf-16le", errors="ignore"))
        except Exception:
            pass
    return strings


def _score_boost_for_context(snippet_lower: str) -> int:
    boost = 0
    for phrase in HIGH_SIGNAL_PHRASES:
        if phrase in snippet_lower:
            boost += 40
    if "day" in snippet_lower and str(TARGET_DAYS) in snippet_lower:
        boost += 50
    if "front" in snippet_lower and "day" in snippet_lower:
        boost += 45
    return boost


def scan_bytes(path: str, data: bytes, kind: str) -> tuple[list[Hit], list[str]]:
    hits: list[Hit] = []
    decoded_as: list[str] = []
    needles = build_binary_needles()
    kw_needles = keyword_bytes()

    text = None
    for enc in ("utf-8", "utf-16le", "utf-16be", "latin-1"):
        try:
            candidate = data.decode(enc)
            sample = candidate[:4000]
            printable = sum(1 for ch in sample if ch.isprintable() or ch.isspace())
            if sample and printable / max(len(sample), 1) > 0.85:
                text = candidate
                decoded_as.append(enc)
                break
        except Exception:
            continue

    if text is not None:
        lower = text.lower()
        for match in re.finditer(
            r".{0,80}\b120\b.{0,80}", text, flags=re.IGNORECASE | re.DOTALL
        ):
            snippet = " ".join(match.group().split())
            hits.append(
                Hit(
                    path=path,
                    offset=match.start(),
                    kind="text_120_context",
                    score=70 + _score_boost_for_context(snippet.lower()),
                    snippet=snippet[:240],
                    notes="literal 120 in decoded text",
                )
            )
            if len(hits) >= MAX_HITS_PER_FILE:
                return hits, decoded_as

        for phrase in HIGH_SIGNAL_PHRASES:
            idx = 0
            while True:
                found = lower.find(phrase, idx)
                if found < 0:
                    break
                snippet = " ".join(text[max(0, found - 60) : found + 120].split())
                hits.append(
                    Hit(
                        path=path,
                        offset=found,
                        kind="text_phrase",
                        score=85 + _score_boost_for_context(snippet.lower()),
                        snippet=snippet[:240],
                        notes=f'phrase "{phrase}"',
                    )
                )
                if len(hits) >= MAX_HITS_PER_FILE:
                    return hits, decoded_as
                idx = found + len(phrase)

        for match in re.finditer(
            r'(?i)["\']?([A-Za-z0-9_./:-]*(?:day|front|timer|limit|deadline)[A-Za-z0-9_./:-]*)["\']?\s*[:=]\s*["\']?120\b',
            text,
        ):
            hits.append(
                Hit(
                    path=path,
                    offset=match.start(),
                    kind="keyed_120",
                    score=140,
                    snippet=match.group()[:240],
                    notes="day/front/timer key assigned to 120 — strong candidate",
                )
            )
            if len(hits) >= MAX_HITS_PER_FILE:
                return hits, decoded_as

    for needle in needles:
        for offset in _find_all(data, needle.data, limit=20):
            snippet = _ascii_preview(data, offset)
            score = needle.score + _score_boost_for_context(snippet.lower())
            if "uint16" in needle.label and score < 50:
                continue
            hits.append(
                Hit(
                    path=path,
                    offset=offset,
                    kind="binary_value",
                    score=score,
                    snippet=snippet,
                    notes=f"{needle.label}; hex={_hex_preview(data, offset)}",
                )
            )
            if len(hits) >= MAX_HITS_PER_FILE:
                return hits, decoded_as

    for label, needle, score in kw_needles:
        for offset in _find_all(data, needle, limit=8):
            snippet = _ascii_preview(data, offset)
            boosted = score + _score_boost_for_context(snippet.lower())
            if boosted < 55:
                continue
            hits.append(
                Hit(
                    path=path,
                    offset=offset,
                    kind="keyword",
                    score=boosted,
                    snippet=snippet,
                    notes=label,
                )
            )
            if len(hits) >= MAX_HITS_PER_FILE:
                return hits, decoded_as

    for label, inflated in _inflate_candidates(data):
        decoded_as.append(f"decompressed:{label}")
        nested_hits, nested_decoded = scan_bytes(f"{path}::{label}", inflated, kind)
        decoded_as.extend(nested_decoded)
        for h in nested_hits:
            h.notes = f"via {label}; {h.notes}".strip("; ")
            h.score += 15
            hits.append(h)
            if len(hits) >= MAX_HITS_PER_FILE:
                return hits, decoded_as

    if kind in {"native_binary", "save_or_data", "unity_asset", "binary"}:
        for s in _extract_strings(data, min_len=6):
            sl = s.lower()
            if "day" in sl and ("120" in sl or "front" in sl or "timer" in sl):
                hits.append(
                    Hit(
                        path=path,
                        offset=-1,
                        kind="extracted_string",
                        score=95 + _score_boost_for_context(sl),
                        snippet=s[:240],
                        notes="string table extract",
                    )
                )
                if len(hits) >= MAX_HITS_PER_FILE:
                    break

    uniq: dict[tuple[str, int, str], Hit] = {}
    for h in hits:
        key = (h.path, h.offset, h.kind)
        prev = uniq.get(key)
        if prev is None or h.score > prev.score:
            uniq[key] = h
    ranked = sorted(uniq.values(), key=lambda h: (-h.score, h.offset))
    return ranked[:MAX_HITS_PER_FILE], decoded_as


def iter_files(root: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d
            for d in dirnames
            if d.lower() not in {".git", "node_modules", "__pycache__", ".vs", "logs"}
        ]
        for name in filenames:
            yield Path(dirpath) / name


def scan_game_root(
    game_root: str | Path,
    progress: ProgressCb | None = None,
    max_file_bytes: int = MAX_FILE_BYTES,
) -> ScanReport:
    root = Path(game_root).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"Path does not exist: {root}")

    files = list(iter_files(root))
    total = max(len(files), 1)
    reports: list[FileReport] = []
    skipped = 0
    notes = [
        "Phase 1 scanner only — does not modify game files.",
        f"Looking for timer value {TARGET_DAYS} and day/front related keys.",
        "Send the generated log files back so a Phase 2 patcher can be built.",
    ]

    if progress:
        progress(f"Found {len(files)} files under {root}", 0.0)

    for i, path in enumerate(files):
        rel = str(path.relative_to(root))
        if progress and (i % 5 == 0 or i == len(files) - 1):
            progress(f"Scanning {rel}", i / total)

        kind = classify_file(path)
        try:
            size = path.stat().st_size
        except OSError as exc:
            reports.append(
                FileReport(path=rel, size=0, sha256_prefix="", kind=kind, errors=[str(exc)])
            )
            continue

        if kind == "media_skip":
            skipped += 1
            reports.append(
                FileReport(
                    path=rel,
                    size=size,
                    sha256_prefix="",
                    kind=kind,
                    skipped_reason="media/font asset skipped",
                )
            )
            continue

        if size == 0:
            skipped += 1
            reports.append(
                FileReport(
                    path=rel,
                    size=0,
                    sha256_prefix="",
                    kind=kind,
                    skipped_reason="empty file",
                )
            )
            continue

        if size > max_file_bytes:
            try:
                with path.open("rb") as fh:
                    head = fh.read(2 * 1024 * 1024)
                    fh.seek(max(0, size - 2 * 1024 * 1024))
                    tail = fh.read(2 * 1024 * 1024)
                data = head + b"\n...\n" + tail
                digest = hashlib.sha256(head).hexdigest()[:16]
                hits, decoded_as = scan_bytes(rel, data, kind)
                reports.append(
                    FileReport(
                        path=rel,
                        size=size,
                        sha256_prefix=digest,
                        kind=kind,
                        decoded_as=decoded_as + ["partial:head+tail"],
                        hits=hits,
                        errors=[
                            f"file larger than {max_file_bytes} bytes; scanned head+tail only"
                        ],
                    )
                )
            except OSError as exc:
                reports.append(
                    FileReport(
                        path=rel, size=size, sha256_prefix="", kind=kind, errors=[str(exc)]
                    )
                )
            continue

        try:
            data = path.read_bytes()
        except OSError as exc:
            reports.append(
                FileReport(
                    path=rel, size=size, sha256_prefix="", kind=kind, errors=[str(exc)]
                )
            )
            continue

        digest = hashlib.sha256(data).hexdigest()[:16]
        hits, decoded_as = scan_bytes(rel, data, kind)
        reports.append(
            FileReport(
                path=rel,
                size=size,
                sha256_prefix=digest,
                kind=kind,
                decoded_as=decoded_as,
                hits=hits,
            )
        )

    all_hits = [h for fr in reports for h in fr.hits]
    all_hits.sort(key=lambda h: (-h.score, h.path, h.offset))

    if progress:
        progress("Scan complete", 1.0)

    return ScanReport(
        created_utc=_utc_now(),
        game_root=str(root),
        scanner_version=VERSION,
        target_days=TARGET_DAYS,
        engine_guess=guess_engine(root),
        files_scanned=len(files) - skipped,
        files_skipped=skipped,
        total_hits=len(all_hits),
        top_candidates=all_hits[:75],
        files=reports,
        notes=notes,
    )


def write_logs(report: ScanReport, out_dir: str | Path) -> tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    json_path = out / f"wunderwaffe_scan_{stamp}.json"
    txt_path = out / f"wunderwaffe_scan_{stamp}.txt"

    json_path.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")

    lines = [
        "Project Wunderwaffe — Phase 1 Scan Log",
        "=" * 60,
        f"Created (UTC): {report.created_utc}",
        f"Scanner:      {report.scanner_version}",
        f"Game root:    {report.game_root}",
        f"Engine guess: {', '.join(report.engine_guess)}",
        f"Target days:  {report.target_days}",
        f"Files scanned/skipped: {report.files_scanned}/{report.files_skipped}",
        f"Total hits:   {report.total_hits}",
        "",
        "NOTES",
        "-" * 40,
    ]
    for n in report.notes:
        lines.append(f"- {n}")
    lines += ["", "TOP CANDIDATES (send this whole log back)", "-" * 40]
    if not report.top_candidates:
        lines.append("No strong candidates found. Still send this log.")
    for i, hit in enumerate(report.top_candidates, 1):
        lines.append(f"{i:02d}. score={hit.score:3d}  kind={hit.kind}  offset={hit.offset}")
        lines.append(f"    file: {hit.path}")
        lines.append(f"    notes: {hit.notes}")
        lines.append(f"    snippet: {hit.snippet}")
        lines.append("")

    lines += ["FILES WITH HITS", "-" * 40]
    for fr in report.files:
        if not fr.hits:
            continue
        lines.append(f"* {fr.path}  ({fr.kind}, {fr.size} bytes, sha256~{fr.sha256_prefix})")
        if fr.decoded_as:
            lines.append(f"  decoded_as: {', '.join(fr.decoded_as)}")
        for hit in sorted(fr.hits, key=lambda h: -h.score)[:15]:
            lines.append(f"  - [{hit.score}] {hit.kind} @{hit.offset}: {hit.snippet[:160]}")
            if hit.notes:
                lines.append(f"    ({hit.notes})")
        lines.append("")

    lines += ["FILE INVENTORY (short)", "-" * 40]
    for fr in report.files:
        flag = "HIT" if fr.hits else ("SKIP" if fr.skipped_reason else "ok")
        lines.append(f"[{flag}] {fr.path}  size={fr.size}  kind={fr.kind}")

    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, txt_path


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------


def run_gui() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    class ScannerApp(tk.Tk):
        def __init__(self) -> None:
            super().__init__()
            self.title("Project Wunderwaffe — Timer Scanner (Phase 1)")
            self.geometry("820x560")
            self.minsize(700, 480)
            self.game_var = tk.StringVar(value=guess_default_root())
            self.out_var = tk.StringVar(value=str(_script_dir() / "scan_logs"))
            self.status_var = tk.StringVar(value="Select your game folder, then Start Scan.")
            self.progress_var = tk.DoubleVar(value=0.0)
            self._worker: threading.Thread | None = None
            self._build()

        def _build(self) -> None:
            pad = {"padx": 12, "pady": 6}
            frm = ttk.Frame(self)
            frm.pack(fill=tk.BOTH, expand=True)

            ttk.Label(
                frm,
                text="Phase 1: find the 120-day timer and write a log",
                font=("Segoe UI", 14, "bold"),
            ).pack(anchor=tk.W, **pad)

            ttk.Label(
                frm,
                text=(
                    "Point this at your Steam install folder "
                    "(…\\steamapps\\common\\Project Wunderwaffe). "
                    "Nothing is modified — only a report is written."
                ),
                wraplength=780,
                justify=tk.LEFT,
            ).pack(anchor=tk.W, **pad)

            path_row = ttk.Frame(frm)
            path_row.pack(fill=tk.X, **pad)
            ttk.Label(path_row, text="Game folder:").pack(side=tk.LEFT)
            ttk.Entry(path_row, textvariable=self.game_var).pack(
                side=tk.LEFT, fill=tk.X, expand=True, padx=8
            )
            ttk.Button(path_row, text="Browse…", command=self._browse_game).pack(side=tk.LEFT)

            out_row = ttk.Frame(frm)
            out_row.pack(fill=tk.X, **pad)
            ttk.Label(out_row, text="Log output:").pack(side=tk.LEFT)
            ttk.Entry(out_row, textvariable=self.out_var).pack(
                side=tk.LEFT, fill=tk.X, expand=True, padx=8
            )
            ttk.Button(out_row, text="Browse…", command=self._browse_out).pack(side=tk.LEFT)

            btns = ttk.Frame(frm)
            btns.pack(fill=tk.X, **pad)
            self.start_btn = ttk.Button(btns, text="Start Scan", command=self._start)
            self.start_btn.pack(side=tk.LEFT)
            ttk.Button(btns, text="Open log folder", command=self._open_out).pack(
                side=tk.LEFT, padx=8
            )

            ttk.Progressbar(frm, variable=self.progress_var, maximum=1.0).pack(
                fill=tk.X, **pad
            )
            ttk.Label(frm, textvariable=self.status_var).pack(anchor=tk.W, **pad)

            self.log = tk.Text(frm, height=18, wrap=tk.WORD)
            self.log.pack(fill=tk.BOTH, expand=True, **pad)
            self._append(
                "After the scan finishes, send BOTH generated files "
                "(.txt and .json) back so Phase 2 (patcher: 120 → 9999999 days) can be built."
            )

        def _append(self, text: str) -> None:
            self.log.insert(tk.END, text + "\n")
            self.log.see(tk.END)

        def _browse_game(self) -> None:
            chosen = filedialog.askdirectory(title="Select Project Wunderwaffe folder")
            if chosen:
                self.game_var.set(chosen)

        def _browse_out(self) -> None:
            chosen = filedialog.askdirectory(title="Select log output folder")
            if chosen:
                self.out_var.set(chosen)

        def _open_out(self) -> None:
            out = Path(self.out_var.get())
            out.mkdir(parents=True, exist_ok=True)
            try:
                if sys.platform.startswith("win"):
                    os.startfile(out)  # type: ignore[attr-defined]
                elif sys.platform == "darwin":
                    subprocess.run(["open", str(out)], check=False)
                else:
                    subprocess.run(["xdg-open", str(out)], check=False)
            except Exception as exc:
                messagebox.showerror("Open folder", str(exc))

        def _start(self) -> None:
            if self._worker and self._worker.is_alive():
                return
            root = self.game_var.get().strip()
            if not root or not Path(root).exists():
                messagebox.showerror(
                    "Missing folder",
                    "Game folder not found. Browse to your Project Wunderwaffe install.",
                )
                return
            self.start_btn.configure(state=tk.DISABLED)
            self.progress_var.set(0.0)
            self.status_var.set("Scanning…")
            self._append(f"Starting scan of: {root}")

            def work() -> None:
                try:

                    def on_progress(msg: str, frac: float) -> None:
                        self.after(0, lambda: self._on_progress(msg, frac))

                    report = scan_game_root(root, progress=on_progress)
                    json_path, txt_path = write_logs(report, self.out_var.get().strip())
                    self.after(
                        0,
                        lambda: self._done(report.total_hits, json_path, txt_path, None),
                    )
                except Exception as exc:  # noqa: BLE001
                    self.after(0, lambda: self._done(0, None, None, exc))

            self._worker = threading.Thread(target=work, daemon=True)
            self._worker.start()

        def _on_progress(self, msg: str, frac: float) -> None:
            self.progress_var.set(frac)
            self.status_var.set(msg)

        def _done(self, hits: int, json_path, txt_path, err) -> None:
            self.start_btn.configure(state=tk.NORMAL)
            if err is not None:
                self.status_var.set("Scan failed")
                self._append(f"ERROR: {err}")
                messagebox.showerror("Scan failed", str(err))
                return
            self.progress_var.set(1.0)
            self.status_var.set(f"Done — {hits} hits. Send the log files back.")
            self._append(f"Hits: {hits}")
            self._append(f"JSON log: {json_path}")
            self._append(f"Text log: {txt_path}")
            self._append("Send both files back for Phase 2 (patcher).")
            messagebox.showinfo(
                "Scan complete",
                f"Found {hits} hits.\n\nLogs written to:\n{txt_path}\n{json_path}\n\n"
                "Send both files back so the patcher can be built.",
            )

    ScannerApp().mainloop()


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan Project Wunderwaffe files for the 120-day timer (Phase 1)."
    )
    parser.add_argument(
        "--cli",
        metavar="GAME_DIR",
        help="Run without GUI: scan GAME_DIR and write logs.",
    )
    parser.add_argument(
        "--out",
        default=str(_script_dir() / "scan_logs"),
        help="Directory for scan logs (default: ./scan_logs next to this script)",
    )
    args = parser.parse_args(argv)

    if args.cli:
        def progress(msg: str, frac: float) -> None:
            print(f"[{int(frac * 100):3d}%] {msg}")

        report = scan_game_root(args.cli, progress=progress)
        json_path, txt_path = write_logs(report, args.out)
        print()
        print(f"Hits: {report.total_hits}")
        print(f"Engine guess: {', '.join(report.engine_guess)}")
        print(f"JSON: {json_path}")
        print(f"TXT:  {txt_path}")
        print("Send both log files back for Phase 2.")
        return 0

    try:
        run_gui()
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"GUI failed ({exc}).", file=sys.stderr)
        print("Try CLI mode:", file=sys.stderr)
        print(
            f'  python "{Path(__file__).name}" --cli '
            r'"C:\Program Files (x86)\Steam\steamapps\common\Project Wunderwaffe"',
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
