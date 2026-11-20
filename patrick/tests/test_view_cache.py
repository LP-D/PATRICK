"""Cache persistant « lu d'abord, recalculé ensuite » des vues lourdes (`webapp/view_cache.py`) et avancement de leur recalcul."""
from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta

import pytest

from patrick.tracking import db
from patrick.webapp import view_cache
from patrick.webapp.view_cache import CachedView, Snapshot


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "patrick.db")
    db.connect(path).close()
    return path


def _view(compute, **kwargs):
    kwargs.setdefault("min_interval", timedelta(0))
    return CachedView(f"test-{id(compute)}", compute, **kwargs)


def _wait_idle(view, db_path, key=None, timeout=5.0):
    deadline = time.monotonic() + timeout
    while view.status(key, db_path)["running"] and time.monotonic() < deadline:
        time.sleep(0.02)


def test_first_get_computes_then_every_other_get_reads_the_file(db_path):
    calls = []
    view = _view(lambda path, key, progress: calls.append(1) or {"n": len(calls)})

    first = view.get(None, db_path, wait_first=10)
    again = view.get(None, db_path, wait_first=10)

    assert first.value == {"n": 1} and again.value == {"n": 1} and again.computed_at == first.computed_at
    assert len(calls) == 1                                       # la seconde lecture ne calcule rien


def test_each_key_has_its_own_snapshot(db_path):
    view = _view(lambda path, key, progress: {"key": key})
    assert view.get(0.1, db_path, wait_first=10).value == {"key": 0.1}
    assert view.get(0.2, db_path, wait_first=10).value == {"key": 0.2}
    assert view.path(0.1, db_path) != view.path(0.2, db_path) and view.get(0.1, db_path).value == {"key": 0.1}


def test_an_old_snapshot_is_served_at_once_and_recomputed_in_the_background(db_path):
    calls = []
    view = _view(lambda path, key, progress: calls.append(1) or {"n": len(calls)}, max_age=timedelta(hours=1))
    view.save(Snapshot({"n": 0}, datetime.now(UTC) - timedelta(hours=3)), None, db_path)         # vieux de 3 h

    served = view.get(None, db_path)                                                               # ne bloque pas

    assert served.value == {"n": 0}
    _wait_idle(view, db_path)
    assert view.load(None, db_path).value == {"n": 1} and len(calls) == 1


def test_a_changed_database_triggers_a_background_refresh_but_never_while_a_live_pass_runs(db_path):
    state = {"marker": (1,), "calls": 0}

    def compute(path, key, progress):
        state["calls"] += 1
        return state["calls"]

    view = _view(compute, marker=lambda conn: state["marker"])
    view.refresh_sync(None, db_path)
    state["marker"] = (2,)                                                                        # la base a bougé

    assert view.get(None, db_path, live_running=True).value == 1                                   # actualisation en cours : on attend sa fin
    assert state["calls"] == 1
    assert view.get(None, db_path).value == 1                                                      # l'ancien est servi tout de suite
    _wait_idle(view, db_path)
    assert view.load(None, db_path).value == 2


def test_a_change_made_by_the_user_is_waited_for_instead_of_showing_the_old_state(db_path):
    state = {"orders": 1, "calls": 0}

    def compute(path, key, progress):
        state["calls"] += 1
        return f"état avec {state['orders']} ordre(s)"

    view = _view(compute, hard_marker=lambda conn: (state["orders"],))
    assert view.get(None, db_path, wait_first=10).value == "état avec 1 ordre(s)"
    state["orders"] = 2                                                                            # l'utilisateur passe un ordre

    fresh = view.get(None, db_path, hard_wait=10)

    assert fresh.value == "état avec 2 ordre(s)"                                                   # jamais l'ancien état
    assert view.get(None, db_path).value == "état avec 2 ordre(s)" and state["calls"] == 2         # puis relu sans recalcul


def test_a_change_by_the_user_that_is_not_ready_in_time_returns_nothing_rather_than_the_old_state(db_path):
    release = threading.Event()
    state = {"orders": 1}

    def compute(path, key, progress):
        if state["orders"] == 2:
            release.wait(5)
        return state["orders"]

    view = _view(compute, hard_marker=lambda conn: (state["orders"],))
    view.get(None, db_path, wait_first=10)
    state["orders"] = 2

    assert view.get(None, db_path, hard_wait=0.3) is None
    release.set()
    _wait_idle(view, db_path)


def test_a_refresh_requested_during_a_run_triggers_one_more_pass_not_two(db_path):
    started, release, runs = threading.Event(), threading.Event(), []

    def compute(path, key, progress):
        runs.append(1)
        started.set()
        release.wait(5)
        return len(runs)

    view = _view(compute)
    view.request_refresh(None, db_path)
    assert started.wait(5)
    view.request_refresh(None, db_path)                          # les données ont bougé pendant le calcul
    view.request_refresh(None, db_path)                          # ... une fois, pas deux
    release.set()
    _wait_idle(view, db_path)
    assert len(runs) == 2


def test_a_page_opening_does_not_stack_a_pass_on_a_running_one(db_path):
    started, release, runs = threading.Event(), threading.Event(), []

    def compute(path, key, progress):
        runs.append(1)
        started.set()
        release.wait(5)
        return 1

    view = _view(compute)
    view.get(None, db_path)                                      # aucun instantané : lance le premier calcul
    assert started.wait(5)
    for _ in range(3):
        view.get(None, db_path)                                  # des ouvertures pendant le calcul : aucune passe de plus
    release.set()
    _wait_idle(view, db_path)
    assert len(runs) == 1


def test_a_failed_computation_is_reported_and_never_replaces_the_good_snapshot(db_path):
    state = {"fail": False}

    def compute(path, key, progress):
        if state["fail"]:
            raise RuntimeError("source en panne")
        return "bon"

    view = _view(compute)
    view.refresh_sync(None, db_path)
    state["fail"] = True
    view.request_refresh(None, db_path)
    _wait_idle(view, db_path)

    assert view.load(None, db_path).value == "bon"
    assert "source en panne" in view.status(None, db_path)["error"]


def test_the_progress_of_a_planned_computation_follows_the_steps_weighted_by_their_last_duration(db_path):
    seen = []

    def compute(path, key, progress):
        progress.plan({"lecture": 1.0, "calcul": 3.0})
        progress.step("lecture")
        seen.append(view.status(None, db_path))
        progress.step("calcul")
        seen.append(view.status(None, db_path))
        return "ok"

    view = _view(compute)
    view.refresh_sync(None, db_path)

    reading, computing = seen
    assert reading["running"] and reading["label"] == "lecture" and reading["fraction"] < 0.05
    assert computing["label"] == "calcul" and 0.24 <= computing["fraction"] < 0.40                  # « lecture » pèse 1/4 du total
    done = view.status(None, db_path)
    assert done["running"] is False and done["fraction"] is None and done["computed_at"]
    assert set(view.load(None, db_path).timings) == {"lecture", "calcul"}                           # durées gardées pour pondérer le suivant


def test_the_second_run_weights_the_steps_by_the_durations_measured_on_the_first(db_path):
    def compute(path, key, progress):
        progress.plan({"rapide": 1.0, "lente": 1.0})                                                # attendues égales...
        progress.step("rapide")
        progress.step("lente")
        time.sleep(0.2)                                                                             # ... mais la 2e est bien plus longue
        return 1

    view = _view(compute)
    view.refresh_sync(None, db_path)
    timings = view.load(None, db_path).timings
    assert timings["lente"] > 10 * timings["rapide"]
    progress = view_cache.Progress({"plan": {}, "done": 0.0, "current": None, "step_started": 0.0}, timings)
    progress.plan({"rapide": 1.0, "lente": 1.0})
    assert progress._state["plan"]["lente"] > 10 * progress._state["plan"]["rapide"]               # la mesure remplace l'attente


def test_an_unplanned_computation_is_estimated_from_its_last_duration_and_indeterminate_the_first_time():
    base = {"plan": {}, "current": None, "step_started": 0.0, "done": 0.0, "started_mono": 100.0, "expected_s": None}
    assert view_cache._fraction(base, 105.0) is None                                                 # premier calcul : on ne sait pas
    estimated = view_cache._fraction({**base, "expected_s": 20.0}, 110.0)
    assert 0.49 < estimated < 0.51
    assert view_cache._fraction({**base, "expected_s": 20.0}, 500.0) == 0.95                         # jamais « terminé » avant de l'être


def test_all_status_lists_the_known_computations(db_path):
    view = _view(lambda path, key, progress: 1)
    view.refresh_sync("clé", db_path)
    entries = [s for s in view_cache.all_status(db_path) if s["name"] == view.name]
    assert entries and entries[0]["key"] == "clé" and entries[0]["running"] is False


def test_progress_is_ignored_outside_a_view():
    view_cache.current_progress().plan({"a": 1.0})                                                   # aucune erreur : une fonction partagée peut s'en passer
    view_cache.current_progress().step("a")
    view_cache.current_progress().finish()


def test_a_snapshot_of_another_version_is_ignored(db_path):
    view = _view(lambda path, key, progress: 1)
    view.refresh_sync(None, db_path)
    view.version += 1
    assert view.load(None, db_path) is None


def test_the_nightly_refresh_only_recomputes_when_something_changed(db_path):
    state = {"marker": (1,), "calls": 0}

    def compute(path, key, progress):
        state["calls"] += 1
        return state["calls"]

    view = _view(compute, marker=lambda conn: state["marker"])
    assert view.refresh_if_stale_sync(None, db_path) is True                                         # rien : il calcule
    assert view.refresh_if_stale_sync(None, db_path) is False                                        # rien de neuf : pas de second calcul
    state["marker"] = (2,)
    assert view.refresh_if_stale_sync(None, db_path) is True
    assert state["calls"] == 2
