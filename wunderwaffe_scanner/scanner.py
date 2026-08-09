"""Scan Project Wunderwaffe install / save folders for the day timer."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import time
import zlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from .patterns import (
    HIGH_SIGNAL_PHRASES,
    TARGET_DAYS,
    build_binary_needles,
    keyword_bytes,
)

ProgressCb = Callable[[str, float], None]

# Skip huge/unhelpful blobs by default (still logged as skipped)
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
    ".assets",  # sometimes text YAML in Unity
}

MAX_CONTEXT = 96
MAX_HITS_PER_FILE = 80
MAX_FILE_BYTES = 80 * 1024 * 1024  # 80 MiB soft cap for full reads
CHUNK_SIZE = 4 * 1024 * 1024


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


def guess_engine(root: Path) -> list[str]:
    guesses: list[str] = []
    names = {p.name.lower() for p in root.rglob("*") if p.is_file()}
    # Limit cost: also check shallow listings
    shallow = {p.name.lower() for p in root.glob("*")}
    shallow |= {p.name.lower() for p in root.glob("*/*")}
    names |= shallow

    if "unityplayer.dll" in names or any(n.endswith("_data") for n in shallow):
        guesses.append("Unity")
    if "unrealengine" in str(root).lower() or any(n.endswith(".pak") for n in names):
        guesses.append("Unreal (possible)")
    if "godot" in names or "project.godot" in names:
        guesses.append("Godot")
    if any(n.endswith(".uasset") for n in names):
        guesses.append("Unreal assets")
    if "projectwunderwaffe" in str(root).lower() or "wunderwaffe" in str(root).lower():
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
    if suffix in {".assets", ".resource", ".resS", ".ress"}:
        return "unity_asset"
    if name in {"globalgamemanagers", "level0", "resources.assets"}:
        return "unity_asset"
    if suffix in {".pak", ".uasset", ".uexp", ".ubulk"}:
        return "unreal_asset"
    if suffix in {".sav", ".save", ".dat", ".bin"}:
        return "save_or_data"
    if "save" in name:
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
    """Try common decompressions that wrap config blobs."""
    out: list[tuple[str, bytes]] = []
    if len(data) >= 2 and data[:2] == b"\x1f\x8b":
        try:
            out.append(("gzip", gzip.decompress(data)))
        except Exception:
            pass
    # zlib / deflate with various wbits
    for label, wbits in (("zlib", 15), ("raw_deflate", -15), ("gzip_stream", 31)):
        try:
            out.append((label, zlib.decompress(data, wbits)))
        except Exception:
            continue
    # Scan for embedded zlib headers (78 01 / 78 9C / 78 DA)
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

    # Prefer text decode when plausible
    text = None
    for enc in ("utf-8", "utf-16le", "utf-16be", "latin-1"):
        try:
            candidate = data.decode(enc)
            # Heuristic: mostly printable
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
        # JSON / key-value style lines mentioning days + 120
        for match in re.finditer(
            r".{0,80}\b120\b.{0,80}", text, flags=re.IGNORECASE | re.DOTALL
        ):
            snippet = " ".join(match.group().split())
            score = 70 + _score_boost_for_context(snippet.lower())
            hits.append(
                Hit(
                    path=path,
                    offset=match.start(),
                    kind="text_120_context",
                    score=score,
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

        # key: 120 style (JSON / ini / yaml-ish)
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

    # Binary needles
    for needle in needles:
        for offset in _find_all(data, needle.data, limit=20):
            snippet = _ascii_preview(data, offset)
            score = needle.score + _score_boost_for_context(snippet.lower())
            # Avoid flooding with bare uint16 120 in media-like noise
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

    # Keyword presence (especially useful in DLLs / assets)
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

    # Decompressed layers
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

    # For assemblies / saves, harvest interesting strings containing day+number
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

    # Dedup similar hits
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
        # Skip noisy caches
        dirnames[:] = [
            d
            for d in dirnames
            if d.lower()
            not in {
                ".git",
                "node_modules",
                "__pycache__",
                ".vs",
                "logs",
            }
        ]
        for name in filenames:
            yield Path(dirpath) / name


def scan_game_root(
    game_root: str | Path,
    progress: ProgressCb | None = None,
    max_file_bytes: int = MAX_FILE_BYTES,
) -> ScanReport:
    from . import __version__

    root = Path(game_root).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"Path does not exist: {root}")

    files = list(iter_files(root))
    total = max(len(files), 1)
    reports: list[FileReport] = []
    skipped = 0
    notes: list[str] = [
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
                FileReport(
                    path=rel,
                    size=0,
                    sha256_prefix="",
                    kind=kind,
                    errors=[str(exc)],
                )
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
            # Still sample head+tail for huge files
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
                        path=rel,
                        size=size,
                        sha256_prefix="",
                        kind=kind,
                        errors=[str(exc)],
                    )
                )
            continue

        try:
            data = path.read_bytes()
        except OSError as exc:
            reports.append(
                FileReport(
                    path=rel,
                    size=size,
                    sha256_prefix="",
                    kind=kind,
                    errors=[str(exc)],
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
    top = all_hits[:75]

    if progress:
        progress("Scan complete", 1.0)

    return ScanReport(
        created_utc=_utc_now(),
        game_root=str(root),
        scanner_version=__version__,
        target_days=TARGET_DAYS,
        engine_guess=guess_engine(root),
        files_scanned=len(files) - skipped,
        files_skipped=skipped,
        total_hits=len(all_hits),
        top_candidates=top,
        files=reports,
        notes=notes,
    )


def write_logs(report: ScanReport, out_dir: str | Path) -> tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    json_path = out / f"wunderwaffe_scan_{stamp}.json"
    txt_path = out / f"wunderwaffe_scan_{stamp}.txt"

    payload = asdict(report)
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines: list[str] = []
    lines.append("Project Wunderwaffe — Phase 1 Scan Log")
    lines.append("=" * 60)
    lines.append(f"Created (UTC): {report.created_utc}")
    lines.append(f"Scanner:      {report.scanner_version}")
    lines.append(f"Game root:    {report.game_root}")
    lines.append(f"Engine guess: {', '.join(report.engine_guess)}")
    lines.append(f"Target days:  {report.target_days}")
    lines.append(f"Files scanned/skipped: {report.files_scanned}/{report.files_skipped}")
    lines.append(f"Total hits:   {report.total_hits}")
    lines.append("")
    lines.append("NOTES")
    lines.append("-" * 40)
    for n in report.notes:
        lines.append(f"- {n}")
    lines.append("")
    lines.append("TOP CANDIDATES (send this whole log back)")
    lines.append("-" * 40)
    if not report.top_candidates:
        lines.append("No strong candidates found. Still send this log.")
    for i, hit in enumerate(report.top_candidates, 1):
        lines.append(
            f"{i:02d}. score={hit.score:3d}  kind={hit.kind}  offset={hit.offset}"
        )
        lines.append(f"    file: {hit.path}")
        lines.append(f"    notes: {hit.notes}")
        lines.append(f"    snippet: {hit.snippet}")
        lines.append("")

    lines.append("FILES WITH HITS")
    lines.append("-" * 40)
    for fr in report.files:
        if not fr.hits:
            continue
        lines.append(
            f"* {fr.path}  ({fr.kind}, {fr.size} bytes, sha256~{fr.sha256_prefix})"
        )
        if fr.decoded_as:
            lines.append(f"  decoded_as: {', '.join(fr.decoded_as)}")
        for hit in sorted(fr.hits, key=lambda h: -h.score)[:15]:
            lines.append(
                f"  - [{hit.score}] {hit.kind} @{hit.offset}: {hit.snippet[:160]}"
            )
            if hit.notes:
                lines.append(f"    ({hit.notes})")
        lines.append("")

    lines.append("FILE INVENTORY (short)")
    lines.append("-" * 40)
    for fr in report.files:
        flag = "HIT" if fr.hits else ("SKIP" if fr.skipped_reason else "ok")
        lines.append(f"[{flag}] {fr.path}  size={fr.size}  kind={fr.kind}")

    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, txt_path
