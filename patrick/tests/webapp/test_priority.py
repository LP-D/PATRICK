"""Naviguer dans l'app passe avant l'entraînement des modèles : worker d'entraînement en priorité basse (processeur et disque, héritée par
ses processus de calcul), passe live de l'app qui laisse la main à la navigation."""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import psutil
import pytest
from fastapi.testclient import TestClient

from patrick.live import refresh as live_refresh
from patrick.system import priority
from patrick.webapp.app import app

CHILD = textwrap.dedent("""
    import subprocess, sys
    import psutil
    from patrick.system import priority

    done = priority.lower_for_training()
    own = psutil.Process().nice()
    grandchild = subprocess.run(
        [sys.executable, "-c", "import psutil; print(psutil.Process().nice())"], capture_output=True, text=True).stdout.strip()
    print(sorted(done), own, grandchild)
""")


def _run_child(extra_env: dict) -> list[str]:
    env = {**os.environ, **extra_env}
    out = subprocess.run([sys.executable, "-c", CHILD], capture_output=True, text=True, env=env, timeout=60, check=True)
    return out.stdout.strip().rsplit(" ", 2)


@pytest.mark.skipif(sys.platform != "win32", reason="classes de priorité Windows")
def test_the_training_worker_runs_below_normal_and_so_do_its_compute_processes():
    done, own, grandchild = _run_child({priority.ENV_DISABLE: "0"})
    assert "cpu" in done
    assert int(own) == psutil.BELOW_NORMAL_PRIORITY_CLASS
    assert int(grandchild) == psutil.BELOW_NORMAL_PRIORITY_CLASS         # joblib / loky héritent de la priorité du worker


@pytest.mark.skipif(sys.platform == "win32", reason="niceness Unix")
def test_the_training_worker_is_niced_on_unix():
    _, own, grandchild = _run_child({priority.ENV_DISABLE: "0"})
    assert int(own) >= 10 and int(grandchild) >= 10


def test_priorities_can_be_left_alone(monkeypatch):
    monkeypatch.setenv(priority.ENV_DISABLE, "1")
    assert priority.lower_for_training() == {}                            # c'est ce qui protège le processus de pytest


def test_a_refusal_from_the_system_never_breaks_the_worker(monkeypatch):
    monkeypatch.delenv(priority.ENV_DISABLE, raising=False)

    class Refusing:
        def nice(self, *args):
            raise psutil.AccessDenied(1)

        def ionice(self, *args):
            raise psutil.AccessDenied(1)

    monkeypatch.setattr(priority.psutil, "Process", Refusing)
    assert priority.lower_for_training() == {}


class _Clock:
    """Horloge et sommeil factices : `sleep` fait avancer le temps."""

    def __init__(self):
        self.now = 1000.0
        self.slept: list[float] = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def test_background_work_waits_until_navigation_has_been_quiet(monkeypatch):
    fake = _Clock()
    monkeypatch.setattr(priority, "_last_navigation", fake.now - 1.0)         # une page demandée il y a 1 s
    waited = priority.wait_for_idle(idle_s=3.0, max_wait_s=30.0, sleep=fake.sleep, clock=fake.clock)
    assert 1.9 <= waited <= 2.6 and fake.slept                                # il reste ~2 s de silence à attendre


def test_background_work_does_not_wait_when_nobody_is_navigating(monkeypatch):
    fake = _Clock()
    monkeypatch.setattr(priority, "_last_navigation", 0.0)                    # jamais de page
    assert priority.wait_for_idle(sleep=fake.sleep, clock=fake.clock) == 0.0 and not fake.slept
    monkeypatch.setattr(priority, "_last_navigation", fake.now - 60.0)        # dernière page il y a une minute
    assert priority.wait_for_idle(sleep=fake.sleep, clock=fake.clock) == 0.0 and not fake.slept


def test_background_work_still_advances_when_navigation_never_stops(monkeypatch):
    fake = _Clock()

    def navigate_again(seconds):
        fake.sleep(seconds)
        monkeypatch.setattr(priority, "_last_navigation", fake.now)           # une nouvelle page à chaque pause

    monkeypatch.setattr(priority, "_last_navigation", fake.now)
    waited = priority.wait_for_idle(idle_s=3.0, max_wait_s=10.0, sleep=navigate_again, clock=fake.clock)
    assert 9.9 <= waited <= 10.1                                              # plafonné : elle reprend malgré tout


@pytest.mark.parametrize("scope, expected", [
    ({"type": "http", "method": "GET", "path": "/predictions"}, True),
    ({"type": "http", "method": "GET", "path": "/fragments/predictions"}, True),
    ({"type": "http", "method": "GET", "path": "/static/patrick.css"}, False),
    ({"type": "http", "method": "GET", "path": "/api/jobs/progress"}, False),   # les interrogations d'une page ouverte ne sont pas de la navigation
    ({"type": "http", "method": "POST", "path": "/runs"}, False),
    ({"type": "websocket", "path": "/ws"}, False),
])
def test_only_pages_and_fragments_count_as_navigation(scope, expected):
    assert priority._is_navigation(scope) is expected


def test_the_app_notes_each_page_but_not_static_files_or_polling(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr(priority, "_last_navigation", 0.0)
    client.get("/static/patrick.css")
    client.get("/api/predictions/reliability")
    assert priority._last_navigation == 0.0
    client.get("/")
    assert priority._last_navigation > 0.0


def test_the_in_app_live_pass_yields_to_navigation_before_each_model():
    paced: list[str] = []
    seen: list[str] = []

    def fake_predict(run_id, db_path=None):
        seen.append(run_id)
        assert len(paced) == len(seen)                                         # `pace` est passée avant CE modèle
        return {"y_pred": 1, "y_proba": 0.5, "n_outcomes_updated": 0}

    candidates = [live_refresh.PredictCandidate("^VIX", 5, f"r{i}", i, "x.joblib") for i in range(3)]
    live_refresh.run_daily_predictions(candidates, predict_live_fn=fake_predict, pace=lambda: paced.append("wait"))
    assert paced == ["wait"] * 3 and seen == ["r0", "r1", "r2"]
