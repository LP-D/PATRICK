"""Le lanceur de bureau : l'enchaînement mise à jour -> assistant -> fusion -> serveur -> fenêtre -> publication,
et chaque réglage qui en désactive une étape. Tout ce qui touche au système (ports, processus, fenêtre,
sous-processus de synchronisation) est remplacé : seul l'ordre et les décisions du lanceur sont testés."""
from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from patrick import settings, sync
from patrick.desktop import launcher, prefs, runtime, share, update
from patrick.desktop.ui import Reporter


class FakeReporter(Reporter):
    def __init__(self, setup_choice=None):
        self.statuses: list[str] = []
        self.errors: list[str] = []
        self.hidden = 0
        self.setup_asked = 0
        self.setup_choice = setup_choice

    def status(self, text):
        self.statuses.append(text)

    def hide(self):
        self.hidden += 1

    def error(self, text):
        self.errors.append(text)

    def ask_setup(self):
        self.setup_asked += 1
        return self.setup_choice


class Env:
    """Un « système » factice : enregistre ce que le lanceur lui demande."""

    def __init__(self, monkeypatch):
        self.events: list[str] = []
        self.server_up = False
        self.window_trackable = True
        self.update_result = {"status": "uptodate", "message": "PATRICK est à jour."}
        self.sync_result = {"code": 0, "lines": ["fusion : 3 run(s) importé(s)"], "seconds": 1}
        self.start_ok = True
        mp = monkeypatch
        mp.setattr(launcher, "WINDOW_POLL_S", 0)
        mp.setattr(launcher, "WINDOW_APPEAR_POLL_S", 0)
        mp.setattr(runtime, "port_open", lambda port, *a, **k: self.server_up)
        mp.setattr(runtime, "stop_server", self._stop)
        mp.setattr(runtime, "start_server", self._start)
        mp.setattr(runtime, "wait_for_port", lambda port, timeout, **k: self.start_ok)
        mp.setattr(runtime, "open_window", self._open)
        mp.setattr(runtime, "server_error_tail", lambda lines=8: "trace")
        mp.setattr(update, "apply", self._update)
        mp.setattr(launcher, "run_sync", self._sync)
        mp.setattr(launcher, "start_push_background", lambda: self.events.append("push"))
        mp.setattr(launcher, "restart_launcher", lambda: self.events.append("restart_launcher"))
        self.counts = iter([])
        mp.setattr(runtime, "window_count", lambda: next(self.counts, 0))

    def _stop(self, port):
        self.events.append("stop_server")
        self.server_up = False
        return 1

    def _start(self, port):
        self.events.append("start_server")
        self.server_up = True
        return SimpleNamespace(poll=lambda: None)

    def _open(self, url, app_window=True):
        self.events.append(f"open_window:{'app' if app_window else 'browser'}")
        self.counts = iter([1, 0, 0, 0])                      # la fenêtre apparaît puis se ferme tout de suite
        return self.window_trackable

    def _update(self, **kw):
        self.events.append("update")
        return self.update_result

    def _sync(self, mode, on_tick=None):
        self.events.append(f"sync:{mode}")
        return self.sync_result


@pytest.fixture
def env(monkeypatch):
    return Env(monkeypatch)


def configure(tmp_path, *, folder=True, **prefs_changes):
    if folder:
        share.apply(str(tmp_path / "PATRICK"), wealth_reference=False)
    prefs.mark_setup_done()
    if prefs_changes:
        prefs.update(prefs_changes)


@pytest.fixture(autouse=True)
def _own_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_SETTINGS_PATH", str(tmp_path / "pc" / ".patrick" / "settings.json"))


def test_normal_launch_runs_every_step_in_order(env, tmp_path):
    configure(tmp_path)
    rep = FakeReporter()
    assert launcher.run(rep) == 0
    assert env.events == ["update", "sync:pull", "start_server", "open_window:app", "stop_server", "push"]
    assert rep.errors == []


def test_launch_records_what_happened_for_the_settings_page(env, tmp_path):
    configure(tmp_path)
    launcher.run(FakeReporter())
    last = launcher.read_json(launcher.LAST_LAUNCH)
    assert last["sync"]["lines"] == ["fusion : 3 run(s) importé(s)"] and last["update"]["status"] == "uptodate"


def test_without_a_shared_folder_nothing_is_synchronised(env, tmp_path):
    configure(tmp_path, folder=False)
    launcher.run(FakeReporter())
    assert env.events == ["update", "start_server", "open_window:app", "stop_server"]


@pytest.mark.parametrize("pref, absent", [("auto_update", "update"), ("sync_on_start", "sync:pull"),
                                          ("sync_on_close", "push")])
def test_each_preference_switches_its_step_off(env, tmp_path, pref, absent):
    configure(tmp_path, **{pref: False})
    launcher.run(FakeReporter())
    assert absent not in env.events and "start_server" in env.events


def test_window_preference_opens_the_default_browser(env, tmp_path):
    configure(tmp_path, app_window=False)
    env.window_trackable = False
    assert launcher.run(FakeReporter()) == 0
    assert "open_window:browser" in env.events and "stop_server" not in env.events and "push" not in env.events


def test_a_running_server_is_reused_and_not_merged_under_its_feet(env, tmp_path):
    configure(tmp_path)
    env.server_up = True
    launcher.run(FakeReporter())
    assert "start_server" not in env.events and "sync:pull" not in env.events


def test_updated_code_restarts_the_launcher_instead_of_continuing(env, tmp_path):
    configure(tmp_path)
    env.update_result = {"status": "updated", "message": "Mis à jour"}
    assert launcher.run(FakeReporter()) == 0
    assert env.events == ["update", "restart_launcher"]


def test_failed_update_is_reported_but_patrick_still_opens(env, tmp_path):
    configure(tmp_path)
    env.update_result = {"status": "failed", "message": "pip a échoué"}
    rep = FakeReporter()
    launcher.run(rep)
    assert "pip a échoué" in rep.errors[0] and "open_window:app" in env.events


def test_an_exception_in_update_never_prevents_startup(env, tmp_path, monkeypatch):
    configure(tmp_path)
    monkeypatch.setattr(update, "apply", lambda **kw: (_ for _ in ()).throw(RuntimeError("réseau")))
    assert launcher.run(FakeReporter()) == 0 and "open_window:app" in env.events


def test_server_that_does_not_start_is_reported(env, tmp_path):
    configure(tmp_path)
    env.start_ok = False
    rep = FakeReporter()
    assert launcher.run(rep) == 1
    assert "n'a pas démarré" in rep.errors[0] and "trace" in rep.errors[0]
    assert not any(e.startswith("open_window") for e in env.events)


def test_first_run_asks_for_the_shared_folder_and_applies_the_choice(env, tmp_path):
    folder = str(tmp_path / "OneDrive" / "PATRICK")
    (tmp_path / "OneDrive").mkdir()
    rep = FakeReporter(setup_choice={"folder": folder, "wealth_reference": True, "schedule": True})
    launcher.run(rep)
    assert rep.setup_asked == 1 and sync.configured_folder() == folder and prefs.setup_done()
    assert sync.is_wealth_reference() is True
    assert "sync:pull" in env.events                          # la fusion se fait dans la foulée


def test_first_run_with_no_shared_folder_choice(env):
    rep = FakeReporter(setup_choice={"folder": None, "wealth_reference": False, "schedule": False})
    launcher.run(rep)
    assert sync.configured_folder() is None and prefs.setup_done() is True
    assert "sync:pull" not in env.events and "push" not in env.events


def test_later_leaves_the_assistant_for_next_time(env):
    rep = FakeReporter(setup_choice=None)
    launcher.run(rep)
    assert prefs.setup_done() is False and "start_server" in env.events
    launcher.run(rep)
    assert rep.setup_asked == 2


def test_existing_installation_is_not_asked_again(env, tmp_path):
    share.apply(str(tmp_path / "PATRICK"))
    settings.save({"setup_done": None})                          # installation d'avant l'assistant
    rep = FakeReporter()
    launcher.run(rep)
    assert rep.setup_asked == 0 and prefs.setup_done() is True


def test_invalid_choice_from_the_assistant_is_reported(env):
    rep = FakeReporter(setup_choice={"folder": str(share.data_dir()), "wealth_reference": False, "schedule": False})
    launcher.run(rep)
    assert rep.errors and prefs.setup_done() is False and "start_server" in env.events


def test_second_click_only_opens_another_window(env, tmp_path):
    configure(tmp_path)
    other = launcher.SingleInstance()
    assert other.acquire()
    try:
        env.server_up = True
        assert launcher.run(FakeReporter()) == 0
        assert env.events == ["open_window:app"]
    finally:
        other.release()


def test_lock_is_released_after_a_normal_run(env, tmp_path):
    configure(tmp_path)
    launcher.run(FakeReporter())
    assert not (runtime.data_dir() / "launcher.lock").exists()


def test_stale_lock_from_a_dead_process_is_taken_over():
    lock = runtime.data_dir() / "launcher.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("99999999:123", encoding="utf-8")
    instance = launcher.SingleInstance()
    assert instance.acquire() is True
    assert launcher.SingleInstance().acquire() is False
    instance.release()


# --- fermeture de la fenêtre ---------------------------------------------------------------------------------------

def test_window_closed_needs_three_empty_checks_in_a_row(monkeypatch):
    monkeypatch.setattr(launcher, "WINDOW_POLL_S", 0)
    monkeypatch.setattr(launcher, "WINDOW_APPEAR_POLL_S", 0)
    counts = iter([1, 1, 0, 0, 1, 0, 0, 0])               # un « 0 » isolé (rechargement) ne compte pas
    seen = []
    assert launcher.wait_window_closed(lambda: seen.append(1) or next(counts)) is True
    assert len(seen) == 8


def test_window_that_never_appears_returns_false(monkeypatch):
    monkeypatch.setattr(launcher, "WINDOW_APPEAR_TIMEOUT_S", 0.05)
    monkeypatch.setattr(launcher, "WINDOW_APPEAR_POLL_S", 0.01)
    assert launcher.wait_window_closed(lambda: 0) is False


# --- relance depuis la page Réglages -------------------------------------------------------------------------------

def _relaunch_state() -> dict:
    return json.loads((runtime.data_dir() / launcher.RELAUNCH_STATE).read_text(encoding="utf-8"))


def test_relaunch_with_sync_stops_merges_restarts_then_publishes(env, tmp_path, monkeypatch):
    configure(tmp_path)
    monkeypatch.setattr(launcher.time, "sleep", lambda s: None)
    assert launcher.relaunch(do_sync=True) == 0
    assert env.events == ["stop_server", "sync:pull", "start_server", "push"]
    state = _relaunch_state()
    assert state["state"] == "done" and "fusion : 3 run(s) importé(s)" in state["steps"]


def test_relaunch_with_update_applies_the_update_before_restarting(env, tmp_path, monkeypatch):
    configure(tmp_path)
    monkeypatch.setattr(launcher.time, "sleep", lambda s: None)
    env.update_result = {"status": "updated", "message": "Mis à jour : a -> b"}
    launcher.relaunch(do_update=True)
    assert env.events == ["stop_server", "update", "start_server"]


def test_relaunch_kills_the_given_server_pid_and_survives_a_failed_step(env, tmp_path, monkeypatch):
    configure(tmp_path)
    killed = []
    monkeypatch.setattr(launcher.time, "sleep", lambda s: None)
    monkeypatch.setattr(runtime, "kill_process_tree", lambda pid, **k: killed.append(pid))
    monkeypatch.setattr(launcher, "run_sync", lambda mode, on_tick=None: (_ for _ in ()).throw(OSError("disque")))
    assert launcher.relaunch(do_sync=True, server_pid=4242) == 1
    assert killed == [4242] and "start_server" in env.events        # le serveur revient quoi qu'il arrive
    assert _relaunch_state()["state"] == "error"


def test_relaunch_reports_a_server_that_does_not_come_back(env, tmp_path, monkeypatch):
    configure(tmp_path)
    monkeypatch.setattr(launcher.time, "sleep", lambda s: None)
    env.start_ok = False
    assert launcher.relaunch() == 1
    state = _relaunch_state()
    assert state["state"] == "error" and "trace" in state["message"]


# --- sous-processus de synchronisation (réel) ---------------------------------------------------------------------

def test_run_sync_captures_output_and_exit_code(monkeypatch):
    monkeypatch.setattr(launcher, "_sync_args", lambda mode: [
        sys.executable, "-c", f"print('fusion {mode}'); print(); raise SystemExit(3)"])
    out = launcher.run_sync("pull")
    assert out["code"] == 3 and out["lines"] == ["fusion pull"]


def test_run_sync_reports_a_missing_interpreter(monkeypatch):
    monkeypatch.setattr(launcher, "_sync_args", lambda mode: ["programme-inexistant-xyz"])
    assert launcher.run_sync("pull")["code"] == -1
