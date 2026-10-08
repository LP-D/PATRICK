"""Processus de l'application : serveur web, fenêtre, ports. Rien ici ne dépend de l'interface graphique."""
from __future__ import annotations

import contextlib
import os
import socket
import subprocess
import sys
import time
import webbrowser
from collections.abc import Callable
from pathlib import Path

import psutil

from patrick import settings

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
APP_PROFILE_NAME = "app-profile-stable"      # profil dédié : n'interfère pas avec le Chrome habituel
WINDOW_SIZE = "1440,900"


def project_dir() -> Path:
    """Dossier du projet Python (celui de `pyproject.toml`)."""
    return Path(__file__).resolve().parents[2]


def repo_root() -> Path:
    """Racine du dépôt git (le dossier qui contient `patrick/`, `app/`, `docs/`)."""
    return project_dir().parent


def data_dir() -> Path:
    return settings.settings_path().parent


def log_dir() -> Path:
    path = data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def profile_dir() -> Path:
    return data_dir() / APP_PROFILE_NAME


def console_python() -> str:
    """Interpréteur avec console (`python.exe`) même quand on tourne sous `pythonw.exe` : pour les sous-processus
    dont on capture la sortie."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        console = exe.with_name("python.exe")
        if console.exists():
            return str(console)
    return str(exe)


def _no_window() -> int:
    return CREATE_NO_WINDOW if os.name == "nt" else 0


def run_hidden(args: list[str], *, cwd: str | Path | None = None, timeout: float = 60,
               env: dict | None = None) -> subprocess.CompletedProcess:
    """Lance un programme sans fenêtre, avec délai maximum. Ne lève jamais : code -1 si délai dépassé / introuvable."""
    try:
        return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False,
                              encoding="utf-8", errors="replace", creationflags=_no_window(),
                              env={**os.environ, **(env or {})})
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, -1, "", "délai dépassé")
    except OSError as exc:
        return subprocess.CompletedProcess(args, -1, "", str(exc))


def spawn_detached(args: list[str], *, cwd: str | Path | None = None, log: Path | None = None) -> subprocess.Popen:
    """Lance un processus qui survit à celui qui l'a lancé (sans fenêtre)."""
    flags = (DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW) if os.name == "nt" else 0
    common = {"cwd": cwd, "stdin": subprocess.DEVNULL, "creationflags": flags, "close_fds": True,
              "start_new_session": os.name != "nt"}
    if log is None:
        return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **common)
    with open(log, "ab") as out:
        return subprocess.Popen(args, stdout=out, stderr=out, **common)


# --- ports et serveur -------------------------------------------------------------------------------------------

def port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.3) -> bool:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.settimeout(timeout)
        return s.connect_ex((host, port)) == 0


def wait_for_port(port: int, timeout_s: float, *, alive: Callable[[], bool] | None = None,
                  tick: Callable[[], None] | None = None) -> bool:
    """Attend que `port` accepte les connexions. `alive` : abandonne dès qu'il renvoie False (serveur mort)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if port_open(port):
            return True
        if alive is not None and not alive():
            return False
        if tick:
            tick()
        time.sleep(0.2)
    return port_open(port)


def listening_pids(port: int) -> list[int]:
    pids: set[int] = set()
    try:
        connections = psutil.net_connections(kind="tcp")
    except (psutil.AccessDenied, OSError):
        return []
    for conn in connections:
        # Socket en écoute = pas d'adresse distante. Le statut LISTEN, lui, n'est pas fiable sous certaines
        # versions de Windows (psutil renvoie « NONE » pour une socket pourtant en écoute).
        if conn.laddr and conn.laddr.port == port and not conn.raddr and conn.pid:
            pids.add(conn.pid)
    return sorted(pids)


def kill_process_tree(pid: int, *, wait_s: float = 5.0) -> bool:
    """Arrête `pid` et ses descendants, SAUF le processus appelant : l'assistant de relance est lancé par le
    serveur qu'il doit arrêter, donc il en est un descendant (il s'arrêterait lui-même avant le serveur)."""
    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return False
    me = os.getpid()
    victims = [p for p in (*proc.children(recursive=True), proc) if p.pid != me]
    for p in victims:
        with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
            p.terminate()
    _, alive = psutil.wait_procs(victims, timeout=wait_s)
    for p in alive:
        with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
            p.kill()
    return True


def stop_server(port: int) -> int:
    """Arrête ce qui écoute sur `port` (le serveur web; le « worker » d'entraînement continue). Renvoie le nombre
    de processus arrêtés."""
    count = 0
    for pid in listening_pids(port):
        if pid != os.getpid() and kill_process_tree(pid):
            count += 1
    return count


def start_server(port: int) -> subprocess.Popen:
    log = log_dir() / "serve-stable.log"
    with open(log, "ab") as out, open(f"{log}.err", "ab") as err:
        return subprocess.Popen([console_python(), "-m", "patrick.cli", "serve", "--port", str(port)],
                                cwd=project_dir(), stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                creationflags=_no_window())


def server_error_tail(lines: int = 8) -> str:
    path = log_dir() / "serve-stable.log.err"
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return ""


def worker_running() -> bool:
    """Un entraînement (processus `patrick.cli worker`) est-il en cours ?"""
    for proc in psutil.process_iter(["cmdline"]):
        cmd = proc.info.get("cmdline") or []
        if "patrick.cli" in cmd and "worker" in cmd:
            return True
    return False


# --- fenêtre ----------------------------------------------------------------------------------------------------

def browser_candidates() -> list[Path]:
    env = os.environ
    bases = [env.get("ProgramFiles"), env.get("ProgramFiles(x86)"), env.get("LOCALAPPDATA")]
    paths = [Path(b) / rel for b in bases if b for rel in (r"Google\Chrome\Application\chrome.exe",)]
    paths += [Path(b) / r"Microsoft\Edge\Application\msedge.exe" for b in bases[:2] if b]
    return paths


def find_browser() -> Path | None:
    return next((p for p in browser_candidates() if p.exists()), None)


def open_window(url: str, *, app_window: bool = True) -> bool:
    """Ouvre PATRICK. Renvoie True si la fenêtre est une fenêtre dédiée dont on peut détecter la fermeture."""
    browser = find_browser() if app_window else None
    if browser is None:
        webbrowser.open(url)
        return False
    subprocess.Popen([str(browser), f"--app={url}", f"--user-data-dir={profile_dir()}", "--no-first-run",
                      "--no-default-browser-check", "--disable-background-mode", f"--window-size={WINDOW_SIZE}"],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def window_count() -> int:
    """Nombre de processus Chrome/Edge qui utilisent le profil dédié (0 = fenêtre fermée)."""
    needle = APP_PROFILE_NAME.lower()
    count = 0
    for proc in psutil.process_iter(["name", "cmdline"]):
        if (proc.info.get("name") or "").lower() not in ("chrome.exe", "msedge.exe"):
            continue
        if any(needle in arg.lower() for arg in proc.info.get("cmdline") or []):
            count += 1
    return count
