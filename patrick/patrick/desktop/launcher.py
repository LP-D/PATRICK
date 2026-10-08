"""Le lanceur : ce qui se passe quand on double-clique sur l'icône PATRICK.

    mise à jour -> assistant de premier démarrage -> fusion avec les autres PC -> serveur -> fenêtre
    -> (fenêtre fermée) arrêt du serveur -> publication de ce PC

Chaque étape lit ses réglages (page Réglages) et ne bloque jamais le démarrage : une mise à jour ou une
synchronisation qui échoue est journalisée (`~/.patrick/logs`), PATRICK s'ouvre quand même.
"""
from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil

from patrick import sync
from patrick.desktop import prefs, runtime, share, update
from patrick.desktop.ui import Reporter

SERVER_START_TIMEOUT_S = 120
WINDOW_APPEAR_TIMEOUT_S = 30
WINDOW_APPEAR_POLL_S = 1
WINDOW_POLL_S = 3
WINDOW_CLOSED_CHECKS = 3          # contrôles « fenêtre absente » d'affilée avant de considérer PATRICK fermé
SYNC_TIMEOUT_S = 4 * 3600
LAST_LAUNCH = "last_launch.json"
RELAUNCH_STATE = "relaunch.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(message: str) -> None:
    try:
        with open(runtime.log_dir() / "launcher.log", "a", encoding="utf-8") as f:
            # heure locale voulue : c'est celle que l'utilisateur lira dans le journal
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}\n")  # noqa: DTZ005
    except OSError:
        pass


def _write_json(name: str, data: dict) -> None:
    path = runtime.data_dir() / name
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def read_json(name: str) -> dict:
    try:
        data = json.loads((runtime.data_dir() / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _record_launch(**fields) -> None:
    with contextlib.suppress(OSError):
        _write_json(LAST_LAUNCH, {**read_json(LAST_LAUNCH), **fields, "at": _now()})


class SingleInstance:
    """Un seul lanceur « gardien » à la fois (fichier verrou : PID + heure de création du processus)."""

    def __init__(self, name: str = "launcher") -> None:
        self.path = runtime.data_dir() / f"{name}.lock"
        self._mine = False

    @staticmethod
    def _token(pid: int) -> str | None:
        try:
            return f"{pid}:{psutil.Process(pid).create_time():.0f}"
        except psutil.Error:
            return None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    owner = self.path.read_text(encoding="utf-8").strip()
                except OSError:
                    owner = ""
                pid = owner.split(":")[0]
                if pid.isdigit() and self._token(int(pid)) == owner:
                    return False
                with contextlib.suppress(OSError):
                    self.path.unlink()            # verrou périmé (lanceur tué)
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(self._token(os.getpid()) or str(os.getpid()))
            self._mine = True
            return True
        return False

    def release(self) -> None:
        if self._mine:
            with contextlib.suppress(OSError):
                self.path.unlink()
            self._mine = False


# --- synchronisation --------------------------------------------------------------------------------------------

def _sync_args(mode: str) -> list[str]:
    return [runtime.console_python(), "-m", "patrick.cli", "sync", "auto", "--only", mode, "--log-file",
            str(runtime.log_dir() / "sync.log")]


def run_sync(mode: str, on_tick=None) -> dict:
    """`patrick sync auto --only <mode>` dans un sous-processus. Renvoie `{"code", "lines", "seconds"}`."""
    started = time.monotonic()
    try:
        proc = subprocess.Popen(_sync_args(mode), cwd=runtime.project_dir(), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                errors="replace", creationflags=runtime.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except OSError as exc:
        return {"code": -1, "lines": [str(exc)], "seconds": 0}
    while True:
        try:
            out, _ = proc.communicate(timeout=1)
            break
        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - started
            if elapsed > SYNC_TIMEOUT_S:
                runtime.kill_process_tree(proc.pid)
                return {"code": -1, "lines": ["délai dépassé"], "seconds": round(elapsed)}
            if on_tick:
                on_tick(elapsed)
    return {"code": proc.returncode, "lines": [ln for ln in (out or "").splitlines() if ln.strip()],
            "seconds": round(time.monotonic() - started)}


def start_push_background() -> None:
    """Publie ce PC en arrière-plan (reporté par `sync auto` s'il y a un entraînement en cours)."""
    runtime.spawn_detached(_sync_args("push"), cwd=runtime.project_dir())
    log("synchronisation (publication) lancée en arrière-plan")


def _elapsed_text(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes} min {secs:02d} s" if minutes else f"{secs} s"


# --- étapes -----------------------------------------------------------------------------------------------------

def step_update(rep: Reporter, port: int) -> str:
    """Renvoie `updated` si le code a changé (il faut alors redémarrer le lanceur avec le nouveau code)."""
    if not prefs.get_bool(prefs.KEY_AUTO_UPDATE):
        return "disabled"
    rep.status("Recherche de mises à jour…")
    result = update.apply(progress=rep.status, stop_server=lambda: runtime.stop_server(port))
    log(f"mise à jour : {result['status']} - {result['message']}")
    _record_launch(update={"status": result["status"], "message": result["message"]})
    if result["status"] == "failed":
        rep.error(result["message"] + f"\n\nJournal : {runtime.log_dir() / 'launcher.log'}")
    return result["status"]


def step_first_run(rep: Reporter) -> None:
    if prefs.setup_done():
        return
    if sync.configured_folder():           # installation existante déjà réglée : rien à demander
        prefs.mark_setup_done()
        return
    rep.hide()
    choice = rep.ask_setup()
    if choice is None:
        log("assistant : reporté (Plus tard)")
        return
    try:
        result = share.apply(choice["folder"], wealth_reference=choice["wealth_reference"],
                             schedule=choice["schedule"])
    except share.ShareError as exc:
        rep.error(str(exc))
        return
    for warning in result["warnings"]:
        rep.error(f"Dossier enregistré, mais : {warning}")
    log(f"assistant : dossier partagé = {result['folder'] or 'aucun'}")


def step_sync_pull(rep: Reporter) -> None:
    folder = sync.configured_folder()
    if not folder or not prefs.get_bool(prefs.KEY_SYNC_ON_START):
        return
    rep.status("Synchronisation avec tes autres PC…")
    result = run_sync("pull", on_tick=lambda s: rep.status(
        f"Synchronisation avec tes autres PC… {_elapsed_text(s)}\n(la première fois peut durer plusieurs minutes)"))
    log(f"synchronisation (fusion) : code {result['code']} en {result['seconds']} s, détail dans sync.log")
    _record_launch(sync={"mode": "pull", "code": result["code"], "lines": result["lines"][-6:]})


def start_and_wait_for_server(rep: Reporter, port: int) -> bool:
    """Démarre le serveur s'il ne tourne pas. Renvoie False (et affiche l'erreur) s'il ne répond pas."""
    if runtime.port_open(port):
        return True
    rep.status("PATRICK démarre… un instant.")
    proc = runtime.start_server(port)
    if runtime.wait_for_port(port, SERVER_START_TIMEOUT_S, alive=lambda: proc.poll() is None):
        return True
    rep.error("Le serveur n'a pas démarré.\n\n"
              f"Journal : {runtime.log_dir() / 'serve-stable.log.err'}\n\n{runtime.server_error_tail()}")
    return False


def wait_window_closed(app_window_check=None) -> bool:
    """Attend l'apparition de la fenêtre puis sa fermeture. Renvoie False si elle n'est jamais apparue."""
    app_window_check = app_window_check or runtime.window_count
    deadline = time.monotonic() + WINDOW_APPEAR_TIMEOUT_S
    appeared = False
    while time.monotonic() < deadline and not appeared:
        time.sleep(WINDOW_APPEAR_POLL_S)
        appeared = app_window_check() > 0
    if not appeared:
        return False
    empty = 0
    while empty < WINDOW_CLOSED_CHECKS:
        time.sleep(WINDOW_POLL_S)
        empty = empty + 1 if app_window_check() == 0 else 0
    return True


# --- scénarios --------------------------------------------------------------------------------------------------

def run(rep: Reporter, *, skip_update: bool = False) -> int:
    """Lance PATRICK et reste là jusqu'à la fermeture de la fenêtre. Renvoie le code de sortie."""
    port = prefs.get_port()
    url = f"http://127.0.0.1:{port}/"
    instance = SingleInstance()
    if not instance.acquire():
        return _second_click(rep, port, url)
    try:
        if not skip_update:
            try:
                status = step_update(rep, port)
            except Exception as exc:  # noqa: BLE001 -- une mise à jour ne doit jamais empêcher PATRICK de s'ouvrir
                log(f"mise à jour : erreur inattendue : {exc}")
                status = "error"
            if status == "updated":
                instance.release()
                restart_launcher()
                return 0
        try:
            step_first_run(rep)
        except Exception as exc:  # noqa: BLE001
            log(f"assistant : erreur inattendue : {exc}")
        if not runtime.port_open(port):
            try:
                step_sync_pull(rep)
            except Exception as exc:  # noqa: BLE001
                log(f"synchronisation : erreur inattendue : {exc}")
        if not start_and_wait_for_server(rep, port):
            return 1
        rep.hide()
        if not runtime.open_window(url, app_window=prefs.get_bool(prefs.KEY_APP_WINDOW)):
            return 0                         # navigateur par défaut : fermeture non détectable
        if wait_window_closed():
            runtime.stop_server(port)
            log("fenêtre fermée : serveur arrêté")
            if sync.configured_folder() and prefs.get_bool(prefs.KEY_SYNC_ON_CLOSE):
                with contextlib.suppress(OSError):
                    start_push_background()
        return 0
    finally:
        instance.release()


def restart_launcher() -> None:
    """Relance le lanceur avec le code fraîchement mis à jour (celui-ci a encore l'ancien code en mémoire)."""
    exe = Path(sys.executable)
    runtime.spawn_detached([str(exe), "-m", "patrick.desktop", "launch", "--no-update"], cwd=runtime.project_dir())
    log("lanceur relancé après mise à jour")


def _second_click(rep: Reporter, port: int, url: str) -> int:
    if not runtime.port_open(port):
        rep.status("PATRICK démarre… un instant.")
        runtime.wait_for_port(port, SERVER_START_TIMEOUT_S)
    rep.hide()
    runtime.open_window(url, app_window=prefs.get_bool(prefs.KEY_APP_WINDOW))
    return 0


def stop() -> int:
    """Arrête le serveur PATRICK (un entraînement lancé continue en arrière-plan)."""
    return runtime.stop_server(prefs.get_port())


# --- relance demandée depuis la page Réglages --------------------------------------------------------------------

def relaunch(*, do_sync: bool = False, do_update: bool = False, server_pid: int | None = None) -> int:
    """Processus détaché lancé par la page Réglages : arrête le serveur, met à jour et/ou fusionne le partage,
    relance le serveur. La fenêtre reste ouverte : la page attend que le serveur revienne puis se recharge.
    L'avancement est écrit dans `~/.patrick/relaunch.json`."""
    port = prefs.get_port()
    steps: list[str] = []

    def state(value: str, message: str = "") -> None:
        with contextlib.suppress(OSError):
            _write_json(RELAUNCH_STATE, {"state": value, "message": message, "steps": steps, "at": _now()})

    state("running", "Arrêt de PATRICK…")
    time.sleep(1.0)                              # laisse partir la réponse HTTP qui a lancé cette relance
    if server_pid:
        runtime.kill_process_tree(server_pid)
    runtime.stop_server(port)
    code = 0
    try:
        if do_update:
            state("running", "Mise à jour…")
            res = update.apply(progress=lambda text: state("running", text))
            steps.append(res["message"])
            log(f"mise à jour (Réglages) : {res['status']} - {res['message']}")
        if do_sync and sync.configured_folder():
            state("running", "Synchronisation avec tes autres PC…")
            res = run_sync("pull", on_tick=lambda s: state(
                "running", f"Synchronisation avec tes autres PC… {_elapsed_text(s)}"))
            steps.extend(res["lines"][-4:] or ["Synchronisation terminée."])
            log(f"synchronisation (Réglages) : code {res['code']} en {res['seconds']} s")
            _record_launch(sync={"mode": "pull", "code": res["code"], "lines": res["lines"][-6:]})
    except Exception as exc:  # noqa: BLE001 -- on relance le serveur quoi qu'il arrive
        steps.append(f"Erreur : {exc}")
        log(f"relance : erreur inattendue : {exc}")
        code = 1
    state("running", "Redémarrage de PATRICK…")
    proc = runtime.start_server(port)
    if not runtime.wait_for_port(port, SERVER_START_TIMEOUT_S, alive=lambda: proc.poll() is None):
        state("error", "Le serveur n'a pas redémarré : " + runtime.server_error_tail())
        return 1
    if do_sync and sync.configured_folder():
        with contextlib.suppress(OSError):
            start_push_background()
    state("done" if code == 0 else "error", "Terminé.")
    return code
