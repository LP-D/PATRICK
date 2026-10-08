"""Processus de l'application : ports, arrêt du serveur, détection de la fenêtre."""
from __future__ import annotations

import socket
import subprocess
import sys
import time
from types import SimpleNamespace

import psutil
import pytest

from patrick.desktop import runtime


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def listener():
    """Un processus fils qui écoute sur un port (comme le serveur PATRICK)."""
    port = free_port()
    code = (f"import socket, time\ns = socket.socket()\ns.bind(('127.0.0.1', {port}))\ns.listen()\n"
            "print('ready', flush=True)\ntime.sleep(120)")
    proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    proc.stdout.readline()
    yield port, proc
    if proc.poll() is None:
        proc.kill()
    proc.wait()


def test_port_open_and_wait_for_port(listener):
    port, _ = listener
    assert runtime.port_open(port) is True
    assert runtime.wait_for_port(port, 1) is True
    assert runtime.port_open(free_port()) is False


def test_wait_for_port_gives_up_when_the_server_died():
    started = time.monotonic()
    assert runtime.wait_for_port(free_port(), 30, alive=lambda: False) is False
    assert time.monotonic() - started < 5


def test_listening_pids_finds_the_listener(listener):
    port, proc = listener
    assert proc.pid in runtime.listening_pids(port) or any(
        psutil.Process(p).ppid() == proc.pid for p in runtime.listening_pids(port))


def test_stop_server_kills_what_listens_on_the_port(listener):
    port, proc = listener
    assert runtime.stop_server(port) >= 1
    proc.wait(timeout=10)
    assert runtime.port_open(port) is False
    assert runtime.stop_server(port) == 0                      # rien à arrêter : pas d'erreur


def test_stop_server_never_kills_the_calling_process(monkeypatch):
    killed = []
    monkeypatch.setattr(runtime, "listening_pids", lambda port: [__import__("os").getpid(), 99999999])
    monkeypatch.setattr(runtime, "kill_process_tree", lambda pid, **kw: killed.append(pid) or True)
    runtime.stop_server(8000)
    assert killed == [99999999]


def test_console_python_maps_pythonw_to_python(tmp_path, monkeypatch):
    (tmp_path / "python.exe").write_text("")
    (tmp_path / "pythonw.exe").write_text("")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "pythonw.exe"))
    assert runtime.console_python() == str(tmp_path / "python.exe")


def _fake_processes(*procs):
    return lambda attrs=None: [SimpleNamespace(info=p) for p in procs]


def test_window_count_only_counts_the_dedicated_profile(monkeypatch):
    monkeypatch.setattr(psutil, "process_iter", _fake_processes(
        {"name": "chrome.exe", "cmdline": ["chrome.exe", f"--user-data-dir=C:/x/{runtime.APP_PROFILE_NAME}"]},
        {"name": "chrome.exe", "cmdline": ["chrome.exe", "--user-data-dir=C:/autre"]},
        {"name": "msedge.exe", "cmdline": ["msedge.exe", f"--app=http://x --user-data-dir={runtime.APP_PROFILE_NAME}"]},
        {"name": "notepad.exe", "cmdline": [runtime.APP_PROFILE_NAME]},
    ))
    assert runtime.window_count() == 2


def test_worker_running_detects_the_training_process(monkeypatch):
    monkeypatch.setattr(psutil, "process_iter", _fake_processes(
        {"cmdline": ["python.exe", "-m", "patrick.cli", "serve"]}))
    assert runtime.worker_running() is False
    monkeypatch.setattr(psutil, "process_iter", _fake_processes(
        {"cmdline": ["python.exe", "-m", "patrick.cli", "worker", "--idle-timeout", "600"]}, {"cmdline": None}))
    assert runtime.worker_running() is True


def test_open_window_falls_back_to_the_default_browser(monkeypatch):
    opened = []
    monkeypatch.setattr(runtime.webbrowser, "open", opened.append)
    assert runtime.open_window("http://127.0.0.1:8000/", app_window=False) is False
    assert opened == ["http://127.0.0.1:8000/"]


def test_open_window_uses_a_dedicated_profile(monkeypatch, tmp_path):
    launched = []
    monkeypatch.setattr(runtime, "find_browser", lambda: tmp_path / "chrome.exe")
    monkeypatch.setattr(runtime.subprocess, "Popen", lambda args, **kw: launched.append(args))
    assert runtime.open_window("http://127.0.0.1:8000/") is True
    assert "--app=http://127.0.0.1:8000/" in launched[0]
    assert any(a.startswith("--user-data-dir=") and runtime.APP_PROFILE_NAME in a for a in launched[0])


def test_run_hidden_never_raises():
    assert runtime.run_hidden(["programme-inexistant-xyz"]).returncode == -1
    out = runtime.run_hidden([sys.executable, "-c", "print('ok')"])
    assert out.returncode == 0 and out.stdout.strip() == "ok"
    slow = runtime.run_hidden([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.5)
    assert slow.returncode == -1 and "délai" in slow.stderr


def test_kill_process_tree_spares_the_caller_even_when_it_is_a_descendant(tmp_path):
    """Régression : l'assistant de relance est lancé PAR le serveur qu'il arrête. Il ne doit pas se tuer avant lui."""
    marker = tmp_path / "survivor.txt"
    child = ("import os, time\nfrom patrick.desktop import runtime\n"
             "runtime.kill_process_tree(os.getppid())\n"
             f"open({str(marker)!r}, 'w').write('alive')\n")
    parent = f"import subprocess, sys, time\nsubprocess.Popen([sys.executable, '-c', {child!r}])\ntime.sleep(60)\n"
    proc = subprocess.Popen([sys.executable, "-c", parent])
    try:
        proc.wait(timeout=20)                                    # le parent (« serveur ») a été arrêté
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        assert marker.read_text() == "alive"                    # l'enfant (« assistant ») a survécu
    finally:
        if proc.poll() is None:
            proc.kill()
