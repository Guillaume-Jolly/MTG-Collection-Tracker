from __future__ import annotations

import ctypes
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

REPO_ROOT = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parents[1]
)
SETTINGS_PATH = REPO_ROOT / "launcher" / "dev_launcher_settings.json"
POLL_INTERVAL_MS = 2000
RAM_WARN_PERCENT = 85
RAM_POLL_MS = 3000


def python_executable() -> str:
    if getattr(sys, "frozen", False):
        for candidate in ("python", "python3", "py"):
            resolved = shutil.which(candidate)
            if resolved:
                return resolved
    return sys.executable


def read_json_file(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def load_local_version() -> str:
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from mtg_pwa.version import app_version_label

        return app_version_label()
    except Exception:
        return "?"


def load_settings() -> dict:
    defaults = {
        "port": 8000,
        "open_browser": True,
        "run_warmup": False,
        "host": "127.0.0.1",
        "browser": "brave",
    }
    if not SETTINGS_PATH.exists():
        return defaults
    try:
        payload = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return defaults
    return {**defaults, **payload}


def save_settings(settings: dict) -> None:
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def fetch_json(url: str, *, timeout: float = 2.5) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def brave_executable() -> Path | None:
    candidates = [
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
        / "BraveSoftware/Brave-Browser/Application/brave.exe",
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "BraveSoftware/Brave-Browser/Application/brave.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
        / "BraveSoftware/Brave-Browser/Application/brave.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    resolved = shutil.which("brave")
    return Path(resolved) if resolved else None


def open_url_in_browser(url: str, browser: str = "brave") -> bool:
    if browser == "brave":
        exe = brave_executable()
        if exe is not None:
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            subprocess.Popen([str(exe), url, "--new-tab"], creationflags=flags)
            return True
    webbrowser.open(url)
    return False


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
            percent = float(status.dwMemoryLoad)
            return {"total_mb": total_mb, "used_mb": used_mb, "avail_mb": avail_mb, "percent": percent}
    try:
        import psutil

        vm = psutil.virtual_memory()
        return {
            "total_mb": int(vm.total // (1024 * 1024)),
            "used_mb": int(vm.used // (1024 * 1024)),
            "avail_mb": int(vm.available // (1024 * 1024)),
            "percent": float(vm.percent),
        }
    except ImportError:
        return {}


def get_process_memory_mb(pid: int | None) -> int | None:
    if not pid or pid <= 0:
        return None
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"(Get-Process -Id {int(pid)} -ErrorAction SilentlyContinue).WorkingSet64",
                ],
                capture_output=True,
                text=True,
                timeout=3,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            value = (result.stdout or "").strip()
            if value.isdigit():
                return int(value) // (1024 * 1024)
        except (OSError, subprocess.SubprocessError, ValueError):
            return None
        return None
    try:
        import psutil

        return int(psutil.Process(pid).memory_info().rss // (1024 * 1024))
    except Exception:
        return None


def git_branch() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=3,
        )
        branch = (result.stdout or "").strip()
        return branch or "?"
    except (OSError, subprocess.SubprocessError):
        return "?"


def git_short_hash() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=3,
        )
        return (result.stdout or "").strip() or "?"
    except (OSError, subprocess.SubprocessError):
        return "?"


def git_dirty() -> bool:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=3,
        )
        return bool((result.stdout or "").strip())
    except (OSError, subprocess.SubprocessError):
        return False


class DevControlPanel:
    def __init__(self) -> None:
        self.settings = load_settings()
        self.local_version = load_local_version()
        self.process: subprocess.Popen[str] | None = None
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.reader_thread: threading.Thread | None = None
        self.managed_by_panel = False
        self._closing = False
        self._server_started_at: float | None = None

        self.root = tk.Tk()
        self.root.title("MTG Tracker — Dev Launcher")
        self.root.geometry("920x640")
        self.root.minsize(760, 520)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.status_var = tk.StringVar(value="Arrêté")
        self.version_var = tk.StringVar(value=self.local_version)
        self.url_var = tk.StringVar(value=self.app_url())
        self.warmup_var = tk.StringVar(value="Warmup : inactif")
        self.port_var = tk.StringVar(value=str(self.settings["port"]))
        self.open_browser_var = tk.BooleanVar(value=bool(self.settings["open_browser"]))
        self.run_warmup_var = tk.BooleanVar(value=bool(self.settings["run_warmup"]))
        self.browser_var = tk.StringVar(value=str(self.settings.get("browser") or "brave"))
        self.pid_var = tk.StringVar(value="—")
        self.uptime_var = tk.StringVar(value="—")
        self.ram_system_var = tk.StringVar(value="RAM système : —")
        self.ram_server_var = tk.StringVar(value="RAM serveur : —")
        self.build_meta_var = tk.StringVar(value="")
        self.semver_var = tk.StringVar(value="")
        self.project_slug_var = tk.StringVar(value="")

        self._build_ui()
        self.refresh_build_panel()
        self.root.after(200, self.drain_log_queue)
        self.root.after(500, self.poll_server)
        self.root.after(RAM_POLL_MS, self.poll_memory)
        self.root.after(800, self.auto_start_if_needed)

    def app_url(self) -> str:
        host = str(self.settings.get("host") or "127.0.0.1")
        port = int(self.settings.get("port") or 8000)
        return f"http://{host}:{port}/"

    def api_url(self, path: str) -> str:
        return f"{self.app_url().rstrip('/')}{path}"

    def _build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(frame)
        header.pack(fill=tk.X)
        ttk.Label(header, text="MTG Tracker Dev Launcher", font=("Segoe UI", 16, "bold")).pack(side=tk.LEFT)
        ttk.Label(
            header,
            text="Serveur Python local · monitoring RAM",
            foreground="#666",
        ).pack(side=tk.LEFT, padx=(10, 0))
        self.status_badge = ttk.Label(header, textvariable=self.status_var, font=("Segoe UI", 10, "bold"))
        self.status_badge.pack(side=tk.RIGHT)

        cards = ttk.Frame(frame)
        cards.pack(fill=tk.X, pady=(12, 8))
        cards.columnconfigure(0, weight=1)
        cards.columnconfigure(1, weight=1)

        version_card = ttk.LabelFrame(cards, text="VERSION & BUILD", padding=10)
        version_card.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        ttk.Label(version_card, textvariable=self.version_var, font=("Segoe UI", 22, "bold")).pack(anchor=tk.W)
        ttk.Label(version_card, textvariable=self.semver_var, foreground="#444").pack(anchor=tk.W, pady=(2, 0))
        ttk.Label(version_card, textvariable=self.project_slug_var, foreground="#666").pack(anchor=tk.W)
        ttk.Label(version_card, textvariable=self.build_meta_var, foreground="#444", wraplength=360).pack(
            anchor=tk.W, pady=(8, 0)
        )

        server_card = ttk.LabelFrame(cards, text="SERVEUR", padding=10)
        server_card.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        meta = ttk.Frame(server_card)
        meta.pack(fill=tk.X)
        ttk.Label(meta, text="PID").grid(row=0, column=0, sticky=tk.W)
        ttk.Label(meta, textvariable=self.pid_var).grid(row=0, column=1, sticky=tk.W, padx=(8, 0))
        ttk.Label(meta, text="Uptime").grid(row=1, column=0, sticky=tk.W, pady=(4, 0))
        ttk.Label(meta, textvariable=self.uptime_var).grid(row=1, column=1, sticky=tk.W, padx=(8, 0), pady=(4, 0))
        ttk.Label(meta, text="URL").grid(row=2, column=0, sticky=tk.W, pady=(4, 0))
        ttk.Label(meta, textvariable=self.url_var).grid(row=2, column=1, sticky=tk.W, padx=(8, 0), pady=(4, 0))

        ram_frame = ttk.Frame(server_card)
        ram_frame.pack(fill=tk.X, pady=(10, 0))
        self.ram_system_label = ttk.Label(ram_frame, textvariable=self.ram_system_var)
        self.ram_system_label.pack(anchor=tk.W)
        self.ram_server_label = ttk.Label(ram_frame, textvariable=self.ram_server_var)
        self.ram_server_label.pack(anchor=tk.W, pady=(2, 0))
        self.ram_progress = ttk.Progressbar(ram_frame, maximum=100, length=280)
        self.ram_progress.pack(anchor=tk.W, pady=(6, 0))

        buttons = ttk.Frame(frame)
        buttons.pack(fill=tk.X, pady=(0, 8))
        ttk.Button(buttons, text="Ouvrir dans Brave", command=self.open_browser).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Démarrer", command=self.start_server).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(buttons, text="Redémarrer", command=self.restart_server).pack(side=tk.LEFT, padx=6)
        ttk.Button(buttons, text="Arrêter", command=self.stop_server).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Warmup forcé", command=self.force_warmup).pack(side=tk.LEFT, padx=6)
        ttk.Button(buttons, text="Copier l'URL", command=self.copy_url).pack(side=tk.LEFT)

        ttk.Label(frame, textvariable=self.warmup_var, foreground="#444").pack(anchor=tk.W, pady=(0, 6))

        options = ttk.LabelFrame(frame, text="Options", padding=10)
        options.pack(fill=tk.X, pady=(0, 8))
        port_row = ttk.Frame(options)
        port_row.pack(fill=tk.X)
        ttk.Label(port_row, text="Port").pack(side=tk.LEFT)
        ttk.Entry(port_row, textvariable=self.port_var, width=8).pack(side=tk.LEFT, padx=(8, 16))
        ttk.Checkbutton(
            options,
            text="Ouvrir Brave au démarrage",
            variable=self.open_browser_var,
            command=self.persist_settings,
        ).pack(anchor=tk.W)
        ttk.Checkbutton(
            options,
            text="Lancer le warmup au démarrage",
            variable=self.run_warmup_var,
            command=self.persist_settings,
        ).pack(anchor=tk.W)
        browser_row = ttk.Frame(options)
        browser_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(browser_row, text="Navigateur").pack(side=tk.LEFT)
        ttk.Combobox(
            browser_row,
            textvariable=self.browser_var,
            values=("brave", "default"),
            width=12,
            state="readonly",
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(browser_row, text="Appliquer", command=self.persist_settings).pack(side=tk.LEFT, padx=8)
        if brave_executable() is None:
            ttk.Label(
                options,
                text="Brave introuvable — repli sur le navigateur par défaut.",
                foreground="#b8860b",
            ).pack(anchor=tk.W, pady=(6, 0))

        log_header = ttk.Frame(frame)
        log_header.pack(fill=tk.X)
        ttk.Label(log_header, text="LOGS").pack(side=tk.LEFT)
        ttk.Button(log_header, text="Vider", command=self.clear_logs).pack(side=tk.RIGHT)
        self.log_box = scrolledtext.ScrolledText(frame, height=14, state=tk.DISABLED, wrap=tk.WORD)
        self.log_box.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

    def refresh_build_panel(self) -> None:
        build_info = read_json_file(REPO_ROOT / "public" / "build-info.json")
        revision = read_json_file(REPO_ROOT / "build-revision.json")
        source = build_info or revision
        label = str(source.get("label") or self.local_version)
        self.version_var.set(label)
        semver = str(source.get("semver") or read_json_file(REPO_ROOT / "package.json").get("version") or "?")
        self.semver_var.set(f"Semver package : {semver}")
        slug = str(source.get("projectSlug") or "mtg-tracker")
        pack = str(source.get("versionPackId") or "cursor-xy-havre-v1")
        self.project_slug_var.set(f"{slug} · {pack}")
        dirty = "modifications locales" if git_dirty() else "propre"
        updated = str(source.get("updatedAt") or "—")[:19].replace("T", " ")
        self.build_meta_var.set(
            f"Commit {git_short_hash()} · branche {git_branch()}\n"
            f"Arbre git : {dirty} · révision {updated}"
        )

    def clear_logs(self) -> None:
        self.log_box.configure(state=tk.NORMAL)
        self.log_box.delete("1.0", tk.END)
        self.log_box.configure(state=tk.DISABLED)

    def append_log(self, line: str) -> None:
        self.log_box.configure(state=tk.NORMAL)
        self.log_box.insert(tk.END, line.rstrip() + "\n")
        self.log_box.see(tk.END)
        self.log_box.configure(state=tk.DISABLED)

    def drain_log_queue(self) -> None:
        while True:
            try:
                line = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self.append_log(line)
        if not self._closing:
            self.root.after(200, self.drain_log_queue)

    def persist_settings(self) -> None:
        try:
            port = int(self.port_var.get().strip() or "8000")
        except ValueError:
            port = 8000
        browser = self.browser_var.get().strip() or "brave"
        if browser not in {"brave", "default"}:
            browser = "brave"
        self.settings.update(
            {
                "port": port,
                "open_browser": bool(self.open_browser_var.get()),
                "run_warmup": bool(self.run_warmup_var.get()),
                "browser": browser,
            }
        )
        self.url_var.set(self.app_url())
        save_settings(self.settings)

    def set_status(self, text: str, *, online: bool = False, external: bool = False) -> None:
        self.status_var.set(text)
        color = "#1b8f3b" if online else "#b33a3a"
        if external:
            color = "#b8860b"
        self.status_badge.configure(foreground=color)

    def server_online(self) -> bool:
        return fetch_json(self.api_url("/api/health")) is not None

    def active_server_pid(self) -> int | None:
        if self.process is not None and self.process.poll() is None:
            return self.process.pid
        return None

    def format_uptime(self) -> str:
        if self._server_started_at is None:
            return "—"
        seconds = int(time.time() - self._server_started_at)
        minutes, sec = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}h {minutes:02d}m {sec:02d}s"
        return f"{minutes}m {sec:02d}s"

    def poll_memory(self) -> None:
        if self._closing:
            return
        mem = get_system_memory()
        if mem:
            percent = float(mem["percent"])
            self.ram_system_var.set(
                f"RAM système : {mem['used_mb']} / {mem['total_mb']} Mo ({percent:.0f} %)"
            )
            self.ram_progress["value"] = percent
            color = "#b33a3a" if percent >= RAM_WARN_PERCENT else "#444"
            self.ram_system_label.configure(foreground=color)
        pid = self.active_server_pid()
        if pid:
            rss = get_process_memory_mb(pid)
            if rss is not None:
                warn = " ⚠" if rss >= 512 else ""
                self.ram_server_var.set(f"RAM serveur (PID {pid}) : {rss} Mo{warn}")
            else:
                self.ram_server_var.set(f"RAM serveur (PID {pid}) : —")
        else:
            self.ram_server_var.set("RAM serveur : —")
        self.pid_var.set(str(pid) if pid else "—")
        self.uptime_var.set(self.format_uptime() if pid else "—")
        self.root.after(RAM_POLL_MS, self.poll_memory)

    def auto_start_if_needed(self) -> None:
        if self.server_online():
            self.set_status("En ligne (externe)", online=True, external=True)
            self.refresh_remote_info()
            if self.open_browser_var.get():
                self.open_browser()
            return
        self.start_server()

    def _read_process_output(self) -> None:
        proc = self.process
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            self.log_queue.put(line)
        code = proc.wait()
        self.log_queue.put(f"[launcher] Processus terminé (code {code})")
        self._server_started_at = None

    def start_server(self) -> None:
        self.persist_settings()
        if self.process is not None and self.process.poll() is None:
            messagebox.showinfo("MTG Tracker", "Le serveur est déjà démarré par ce panneau.")
            return
        if self.server_online():
            self.set_status("En ligne (externe)", online=True, external=True)
            self.refresh_remote_info()
            if self.open_browser_var.get():
                self.open_browser()
            return

        port = int(self.settings["port"])
        host = str(self.settings.get("host") or "127.0.0.1")
        cmd = [python_executable(), "run_mvp.py", "--host", host, "--port", str(port)]
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        self.append_log(f"[launcher] Démarrage : {' '.join(cmd)}")
        self.set_status("Démarrage...", online=False)
        try:
            self.process = subprocess.Popen(
                cmd,
                cwd=REPO_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=creationflags,
            )
        except OSError as error:
            messagebox.showerror("MTG Tracker", f"Impossible de démarrer le serveur :\n{error}")
            self.set_status("Erreur", online=False)
            return

        self.managed_by_panel = True
        self._server_started_at = time.time()
        self.reader_thread = threading.Thread(target=self._read_process_output, daemon=True)
        self.reader_thread.start()
        self.root.after(1000, self.wait_until_online)

    def wait_until_online(self, attempt: int = 0) -> None:
        if self._closing:
            return
        if self.server_online():
            self.set_status("En ligne", online=True)
            self.refresh_remote_info()
            self.refresh_build_panel()
            if self.open_browser_var.get():
                self.open_browser()
            if self.run_warmup_var.get():
                self.force_warmup()
            return
        if attempt >= 45:
            self.set_status("Démarrage lent...", online=False)
            return
        self.root.after(1000, lambda: self.wait_until_online(attempt + 1))

    def stop_server(self) -> None:
        if self.process is not None and self.process.poll() is None:
            pid = self.process.pid
            self.append_log(f"[launcher] Arrêt du serveur (PID {pid})...")
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                )
            else:
                self.process.terminate()
            self.process = None
            self.managed_by_panel = False
            self._server_started_at = None
            self.set_status("Arrêté", online=False)
            self.warmup_var.set("Warmup : inactif")
            return

        if self.server_online():
            if not messagebox.askyesno(
                "MTG Tracker",
                "Un serveur externe tourne sur ce port.\nVoulez-vous tenter de l'arrêter via le port réseau ?",
            ):
                return
            self.kill_process_on_port(int(self.settings["port"]))
            time.sleep(0.8)
            if self.server_online():
                messagebox.showwarning("MTG Tracker", "Impossible d'arrêter le serveur externe.")
            else:
                self.set_status("Arrêté", online=False)
            return

        self.set_status("Arrêté", online=False)

    def kill_process_on_port(self, port: int) -> None:
        if sys.platform != "win32":
            return
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            check=False,
        )
        target_pids: set[str] = set()
        for line in result.stdout.splitlines():
            if f":{port} " in line and "LISTENING" in line:
                parts = line.split()
                if parts:
                    target_pids.add(parts[-1])
        for pid in target_pids:
            if pid.isdigit() and int(pid) > 0:
                subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True, text=True)

    def restart_server(self) -> None:
        self.stop_server()

        def delayed_start() -> None:
            time.sleep(0.8)
            if not self._closing:
                self.root.after(0, self.start_server)

        threading.Thread(target=delayed_start, daemon=True).start()

    def open_browser(self) -> None:
        browser = str(self.settings.get("browser") or "brave")
        url = self.app_url()
        if browser == "brave" and brave_executable() is None:
            self.append_log("[launcher] Brave introuvable — ouverture navigateur par défaut.")
            webbrowser.open(url)
            return
        used_brave = open_url_in_browser(url, browser=browser)
        label = "Brave" if used_brave and browser == "brave" else "navigateur par défaut"
        self.append_log(f"[launcher] Ouverture {label} : {url}")

    def copy_url(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self.app_url())
        self.append_log(f"[launcher] URL copiée : {self.app_url()}")

    def force_warmup(self) -> None:
        payload = json.dumps({"force": True}).encode("utf-8")
        request = urllib.request.Request(
            self.api_url("/api/startup/warmup"),
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                response.read()
            self.append_log("[launcher] Warmup forcé démarré.")
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            messagebox.showwarning("MTG Tracker", f"Warmup indisponible : {error}")

    def refresh_remote_info(self) -> None:
        health = fetch_json(self.api_url("/api/health"))
        if health:
            remote_version = str(health.get("app_version") or self.local_version)
            slug = health.get("projectSlug")
            if slug:
                self.version_var.set(f"{remote_version} · {slug}")
            else:
                self.version_var.set(f"{remote_version} (live)")
        else:
            self.version_var.set(self.local_version)

        warmup = fetch_json(self.api_url("/api/startup/status"))
        if warmup:
            if warmup.get("running"):
                progress = warmup.get("progress")
                message = warmup.get("message") or "Warmup en cours"
                self.warmup_var.set(f"Warmup : {message} ({progress}%)")
            else:
                self.warmup_var.set(f"Warmup : {warmup.get('message') or 'inactif'}")
        elif health:
            self.warmup_var.set("Warmup : inactif")

    def poll_server(self) -> None:
        if self._closing:
            return
        online = self.server_online()
        if online:
            if self.managed_by_panel and self.process is not None and self.process.poll() is None:
                self.set_status("En ligne", online=True)
            elif self.process is None or self.process.poll() is not None:
                self.set_status("En ligne (externe)", online=True, external=True)
            self.refresh_remote_info()
        elif self.process is not None and self.process.poll() is None:
            self.set_status("Démarrage...", online=False)
        else:
            self.set_status("Arrêté", online=False)
            self.version_var.set(self.local_version)
            self.warmup_var.set("Warmup : inactif")
            self.refresh_build_panel()
        self.root.after(POLL_INTERVAL_MS, self.poll_server)

    def on_close(self) -> None:
        self._closing = True
        self.persist_settings()
        if self.process is not None and self.process.poll() is None:
            if messagebox.askyesno(
                "MTG Tracker",
                "Arrêter le serveur avant de fermer le panneau ?",
            ):
                self.stop_server()
        self.root.destroy()


def main() -> None:
    app = DevControlPanel()
    app.root.mainloop()


if __name__ == "__main__":
    main()
