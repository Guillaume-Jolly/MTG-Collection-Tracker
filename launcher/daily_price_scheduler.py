"""Planificateur local — archivage quotidien des prix (popup + progression).

Usage:
  python launcher/daily_price_scheduler.py          # check léger + popup si besoin
  python launcher/daily_price_scheduler.py --check-only
  python launcher/daily_price_scheduler.py --force-run   # lance l'UI de progression directement
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = REPO_ROOT / "data" / "daily_price_scheduler_state.json"
SNOOZE_HOURS = 1
UI_POLL_MS = 250
RAM_POLL_MS = 1500

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mtg_pwa.cardmarket_export import LAST_CARDMARKET_ARCHIVE_DATE_KEY  # noqa: E402
from mtg_pwa.database import connect, get_app_metadata, init_db  # noqa: E402
from mtg_pwa.price_archive import archive_daily_prices  # noqa: E402


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def archive_completed_today(*, db_path: Path | None = None) -> bool:
    db = connect(db_path) if db_path else connect()
    init_db(db)
    try:
        last_date = get_app_metadata(db, LAST_CARDMARKET_ARCHIVE_DATE_KEY)
    finally:
        db.close()
    return last_date == date.today().isoformat()


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(payload: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def clear_snooze() -> None:
    state = load_state()
    state.pop("snooze_until", None)
    save_state(state)


def snooze_for_one_hour() -> None:
    until = datetime.now(timezone.utc) + timedelta(hours=SNOOZE_HOURS)
    state = load_state()
    state["snooze_until"] = until.replace(microsecond=0).isoformat()
    state["snoozed_at"] = utc_now_iso()
    save_state(state)


def is_snoozed() -> bool:
    raw = load_state().get("snooze_until")
    if not raw:
        return False
    try:
        until = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return False
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) < until


def should_show_prompt() -> bool:
    if archive_completed_today():
        clear_snooze()
        return False
    if is_snoozed():
        return False
    return True


def get_system_memory() -> dict[str, int | float]:
    if sys.platform == "win32":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            total_mb = int(status.ullTotalPhys // (1024 * 1024))
            avail_mb = int(status.ullAvailPhys // (1024 * 1024))
            used_mb = max(0, total_mb - avail_mb)
            return {
                "total_mb": total_mb,
                "used_mb": used_mb,
                "avail_mb": avail_mb,
                "percent": float(status.dwMemoryLoad),
            }
    return {}


def get_process_memory_mb() -> int | None:
    if sys.platform != "win32":
        return None
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"(Get-Process -Id {os.getpid()} -ErrorAction SilentlyContinue).WorkingSet64",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        value = (result.stdout or "").strip()
        if value.isdigit():
            return int(value) // (1024 * 1024)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return None


def estimate_progress_percent(status: dict[str, Any]) -> float:
    phase = str(status.get("phase") or status.get("cardmarket_phase") or "idle")
    if phase in {"done", "skipped", "idle"}:
        return 100.0
    if phase == "error":
        return 0.0
    if phase == "preparing":
        return 3.0
    if phase == "downloading":
        return 12.0
    if phase == "parsing":
        total = max(int(status.get("uuids_total") or 1), 1)
        found = int(status.get("uuids_found") or 0)
        return 15.0 + (found / total) * 30.0
    if phase == "writing":
        total = max(int(status.get("cards_total") or status.get("uuids_found") or 1), 1)
        done = int(status.get("cards_processed") or 0)
        return 45.0 + (done / total) * 30.0
    cm_phase = str(status.get("cardmarket_phase") or "")
    if cm_phase == "mapping":
        return 78.0
    if cm_phase == "downloading":
        return 82.0
    if cm_phase == "writing":
        total = max(int(status.get("cardmarket_products_tracked") or 1), 1)
        done = int(status.get("cardmarket_rows_written") or 0)
        return 85.0 + min(done / total, 1.0) * 14.0
    if phase == "cardmarket" or cm_phase:
        return 80.0
    return 5.0


def format_eta(seconds: float | None) -> str:
    if seconds is None or seconds < 0 or seconds > 86400:
        return "estimation indisponible"
    if seconds < 60:
        return f"~{int(seconds)} s restantes"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    if minutes >= 120:
        return f"~{minutes // 60} h {(minutes % 60):02d} min restantes"
    return f"~{minutes} min {secs:02d} s restantes"


def format_elapsed(seconds: float) -> str:
    seconds = max(0, int(seconds))
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} h {minutes:02d} min {secs:02d} s"
    if minutes:
        return f"{minutes} min {secs:02d} s"
    return f"{secs} s"


class PromptApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("MTG Tracker — Archivage des prix")
        self.root.geometry("460x220")
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)
        self.root.protocol("WM_DELETE_WINDOW", self.on_decline)

        frame = ttk.Frame(self.root, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frame,
            text="Archivage quotidien des prix",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor=tk.W)
        ttk.Label(
            frame,
            text=(
                "Les prix Cardmarket du jour ne sont pas encore archives.\n"
                "Lancer la mise a jour maintenant ?"
            ),
            wraplength=420,
        ).pack(anchor=tk.W, pady=(10, 16))

        actions = ttk.Frame(frame)
        actions.pack(fill=tk.X)
        ttk.Button(actions, text="Oui, lancer", command=self.on_accept).pack(side=tk.LEFT)
        ttk.Button(actions, text="Non, plus tard", command=self.on_decline).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(
            frame,
            text=f"En cas de refus : nouvelle proposition dans {SNOOZE_HOURS} h.",
            style="TLabel",
        ).pack(anchor=tk.W, pady=(14, 0))

        self.accepted = False

    def on_accept(self) -> None:
        self.accepted = True
        self.root.destroy()

    def on_decline(self) -> None:
        snooze_for_one_hour()
        self.root.destroy()

    def run(self) -> bool:
        self.root.mainloop()
        return self.accepted


class ArchiveProgressApp:
    def __init__(self, *, force: bool = False) -> None:
        self.force = force
        self.root = tk.Tk()
        self.root.title("MTG Tracker — Mise a jour des prix")
        self.root.geometry("760x560")
        self.root.minsize(640, 480)

        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.status: dict[str, Any] = {"phase": "starting", "message": "Demarrage..."}
        self.log_lines: list[str] = []
        self.started_at = time.monotonic()
        self.worker = threading.Thread(target=self._run_archive, daemon=True)

        self._build_ui()
        self.worker.start()
        self.root.after(UI_POLL_MS, self._poll)
        self.root.after(RAM_POLL_MS, self._poll_memory)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)

        self.phase_var = tk.StringVar(value="Phase : demarrage")
        self.detail_var = tk.StringVar(value="Preparation...")
        self.progress_var = tk.DoubleVar(value=0.0)
        self.percent_var = tk.StringVar(value="0 %")
        self.elapsed_var = tk.StringVar(value="Ecoule : 0 s")
        self.eta_var = tk.StringVar(value="Temps restant : —")
        self.ram_system_var = tk.StringVar(value="RAM systeme : —")
        self.ram_process_var = tk.StringVar(value="RAM processus : —")
        self.stats_var = tk.StringVar(value="Cartes : — · Snapshots : — · Cardmarket : —")

        ttk.Label(outer, textvariable=self.phase_var, font=("Segoe UI", 11, "bold")).pack(anchor=tk.W)
        ttk.Label(outer, textvariable=self.detail_var, wraplength=700).pack(anchor=tk.W, pady=(4, 8))

        bar_frame = ttk.Frame(outer)
        bar_frame.pack(fill=tk.X, pady=(0, 4))
        self.progress = ttk.Progressbar(bar_frame, maximum=100, variable=self.progress_var, length=680)
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(bar_frame, textvariable=self.percent_var, width=8).pack(side=tk.LEFT, padx=(8, 0))

        meta = ttk.Frame(outer)
        meta.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(meta, textvariable=self.elapsed_var).pack(side=tk.LEFT)
        ttk.Label(meta, textvariable=self.eta_var).pack(side=tk.LEFT, padx=(16, 0))

        ttk.Label(outer, textvariable=self.stats_var).pack(anchor=tk.W, pady=(0, 4))
        ttk.Label(outer, textvariable=self.ram_system_var).pack(anchor=tk.W)
        ttk.Label(outer, textvariable=self.ram_process_var).pack(anchor=tk.W, pady=(0, 8))

        ttk.Label(outer, text="Journal").pack(anchor=tk.W)
        self.log_box = scrolledtext.ScrolledText(outer, height=16, state=tk.DISABLED, wrap=tk.WORD)
        self.log_box.pack(fill=tk.BOTH, expand=True, pady=(4, 8))

        self.close_button = ttk.Button(outer, text="Fermer", command=self.root.destroy, state=tk.DISABLED)
        self.close_button.pack(anchor=tk.E)

    def _run_archive(self) -> None:
        def on_status(updates: dict[str, Any]) -> None:
            self.events.put(("status", updates))

        def on_log(message: str) -> None:
            self.events.put(("log", message))

        try:
            result = archive_daily_prices(force=self.force, on_status=on_status, on_log=on_log)
            if not result.get("skipped"):
                clear_snooze()
            self.events.put(("done", result))
        except Exception as error:  # noqa: BLE001 - surface archive failure in UI
            self.events.put(("error", str(error)))

    def _append_log(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{stamp}] {message}"
        self.log_lines.append(line)
        self.log_box.configure(state=tk.NORMAL)
        self.log_box.insert(tk.END, line + "\n")
        self.log_box.see(tk.END)
        self.log_box.configure(state=tk.DISABLED)

    def _refresh_status(self) -> None:
        phase = str(self.status.get("phase") or self.status.get("cardmarket_phase") or "idle")
        message = str(self.status.get("message") or "")
        percent = estimate_progress_percent(self.status)
        elapsed = time.monotonic() - self.started_at
        eta_seconds = None
        if 0 < percent < 100:
            eta_seconds = elapsed * (100.0 - percent) / percent

        self.phase_var.set(f"Phase : {phase}")
        self.detail_var.set(message or "En cours...")
        self.progress_var.set(percent)
        self.percent_var.set(f"{percent:.0f} %")
        self.elapsed_var.set(f"Ecoule : {format_elapsed(elapsed)}")
        self.eta_var.set(f"Temps restant : {format_eta(eta_seconds)}")

        cards = self.status.get("cards_processed")
        cards_total = self.status.get("cards_total")
        snapshots = self.status.get("snapshots_written")
        cm_rows = self.status.get("cardmarket_rows_written")
        cm_total = self.status.get("cardmarket_products_tracked")
        stats_parts = []
        if cards_total:
            stats_parts.append(f"Cartes {cards or 0}/{cards_total}")
        if snapshots is not None:
            stats_parts.append(f"Snapshots {snapshots}")
        if cm_total:
            stats_parts.append(f"Cardmarket {cm_rows or 0}/{cm_total}")
        self.stats_var.set(" · ".join(stats_parts) if stats_parts else "Cartes : — · Snapshots : — · Cardmarket : —")

    def _poll_memory(self) -> None:
        mem = get_system_memory()
        if mem:
            self.ram_system_var.set(
                f"RAM systeme : {mem['used_mb']} / {mem['total_mb']} Mo ({mem['percent']:.0f} %)"
            )
        rss = get_process_memory_mb()
        self.ram_process_var.set(
            f"RAM processus (PID {os.getpid()}) : {rss} Mo" if rss is not None else "RAM processus : —"
        )
        if self.close_button["state"] == str(tk.DISABLED):
            self.root.after(RAM_POLL_MS, self._poll_memory)

    def _poll(self) -> None:
        while True:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "status":
                self.status.update(payload if isinstance(payload, dict) else {})
                self._refresh_status()
            elif kind == "log":
                self._append_log(str(payload))
            elif kind == "done":
                result = payload if isinstance(payload, dict) else {}
                self.status.update({"phase": "done", "message": "Archivage termine."})
                self._refresh_status()
                self._append_log(
                    "Termine: Cardmarket "
                    f"{result.get('cardmarket_rows_written', 0)} lignes "
                    f"({result.get('archive_date', '')})."
                )
                self.close_button.configure(state=tk.NORMAL)
                messagebox.showinfo("MTG Tracker", "Archivage des prix termine.", parent=self.root)
                return
            elif kind == "error":
                self.status.update({"phase": "error", "message": str(payload)})
                self._refresh_status()
                self._append_log(f"Erreur: {payload}")
                self.close_button.configure(state=tk.NORMAL)
                messagebox.showerror("MTG Tracker", f"Erreur d'archivage:\n{payload}", parent=self.root)
                return

        if self.worker.is_alive():
            self._refresh_status()
            self.root.after(UI_POLL_MS, self._poll)
        else:
            self.close_button.configure(state=tk.NORMAL)

    def run(self) -> None:
        self.root.mainloop()


def run_prompt_flow() -> int:
    if not should_show_prompt():
        return 0
    if PromptApp().run():
        ArchiveProgressApp().run()
    return 0


def run_manual_flow() -> int:
    """Lancement manuel (barre des taches) : ignore le snooze automatique."""
    if archive_completed_today():
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        retry = messagebox.askyesno(
            "MTG Tracker — Archivage des prix",
            (
                f"L archivage du jour est deja fait ({date.today().isoformat()}).\n\n"
                "Relancer quand meme une mise a jour complete ?"
            ),
            parent=root,
        )
        root.destroy()
        if not retry:
            return 0
        ArchiveProgressApp(force=True).run()
        return 0

    if PromptApp().run():
        ArchiveProgressApp().run()
    else:
        snooze_for_one_hour()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Planificateur local d'archivage des prix MTG Tracker.")
    parser.add_argument("--check-only", action="store_true", help="Sortie 0 si rien a faire, 2 si popup requise.")
    parser.add_argument("--force-run", action="store_true", help="Ouvre directement l'UI de progression.")
    parser.add_argument(
        "--manual",
        action="store_true",
        help="Lancement manuel (ignore le snooze, propose de forcer si deja archive).",
    )
    args = parser.parse_args()

    if args.check_only:
        if archive_completed_today():
            return 0
        if is_snoozed():
            return 1
        return 2

    if args.force_run:
        ArchiveProgressApp(force=True).run()
        return 0

    if args.manual:
        return run_manual_flow()

    return run_prompt_flow()


if __name__ == "__main__":
    raise SystemExit(main())
