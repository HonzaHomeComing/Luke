"""Simple desktop UI for the Wunderwaffe Phase 1 scanner."""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .scanner import scan_game_root, write_logs

DEFAULT_STEAM_CANDIDATES = [
    r"C:\Program Files (x86)\Steam\steamapps\common\Project Wunderwaffe",
    r"C:\Program Files\Steam\steamapps\common\Project Wunderwaffe",
    r"D:\SteamLibrary\steamapps\common\Project Wunderwaffe",
    r"E:\SteamLibrary\steamapps\common\Project Wunderwaffe",
]


def _guess_default_root() -> str:
    for candidate in DEFAULT_STEAM_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return DEFAULT_STEAM_CANDIDATES[0]


class ScannerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Project Wunderwaffe — Timer Scanner (Phase 1)")
        self.geometry("820x560")
        self.minsize(700, 480)

        self.game_var = tk.StringVar(value=_guess_default_root())
        self.out_var = tk.StringVar(value=str(Path.cwd() / "scan_logs"))
        self.status_var = tk.StringVar(value="Select your game folder, then Start Scan.")
        self.progress_var = tk.DoubleVar(value=0.0)
        self._worker: threading.Thread | None = None

        self._build()

    def _build(self) -> None:
        pad = {"padx": 12, "pady": 6}
        frm = ttk.Frame(self)
        frm.pack(fill=tk.BOTH, expand=True)

        title = ttk.Label(
            frm,
            text="Phase 1: find the 120-day timer and write a log",
            font=("Segoe UI", 14, "bold"),
        )
        title.pack(anchor=tk.W, **pad)

        help_txt = (
            "Point this at your Steam install folder "
            "(…\\steamapps\\common\\Project Wunderwaffe). "
            "It also helps to scan the SaveGame folder if you keep saves elsewhere. "
            "Nothing is modified — only a report is written."
        )
        ttk.Label(frm, text=help_txt, wraplength=780, justify=tk.LEFT).pack(
            anchor=tk.W, **pad
        )

        path_row = ttk.Frame(frm)
        path_row.pack(fill=tk.X, **pad)
        ttk.Label(path_row, text="Game folder:").pack(side=tk.LEFT)
        ttk.Entry(path_row, textvariable=self.game_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=8
        )
        ttk.Button(path_row, text="Browse…", command=self._browse_game).pack(
            side=tk.LEFT
        )

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

        self.bar = ttk.Progressbar(frm, variable=self.progress_var, maximum=1.0)
        self.bar.pack(fill=tk.X, **pad)
        ttk.Label(frm, textvariable=self.status_var).pack(anchor=tk.W, **pad)

        self.log = tk.Text(frm, height=18, wrap=tk.WORD)
        self.log.pack(fill=tk.BOTH, expand=True, **pad)
        self._append(
            "After the scan finishes, send BOTH generated files "
            "(.txt and .json) back so Phase 2 (patcher: 120 → 9999999 days) can be built.\n"
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
            import os
            import subprocess
            import sys

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
            except Exception as exc:  # noqa: BLE001 — surface to UI
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


def run() -> None:
    app = ScannerApp()
    app.mainloop()
