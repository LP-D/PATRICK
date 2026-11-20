"""Actualisation live quotidienne : l'app laissée ouverte doit prédire et juger chaque jour, pas seulement au lancement."""
from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime, timedelta

import pytest
from test_fund_selection import World

from patrick import live_refresh
from patrick.clock import utc_today
from patrick.fund import autopilot, store
from patrick.tracking import db as trackdb


def test_refresh_is_due_at_launch_then_once_per_new_day():
    today = date(2026, 10, 13)
    assert live_refresh.refresh_due(None, today)                       # premier lancement
    assert not live_refresh.refresh_due(today, today)                  # déjà fait aujourd'hui
    assert live_refresh.refresh_due(date(2026, 10, 12), today)         # le jour a changé
    assert not live_refresh.refresh_due(date(2026, 10, 14), today)     # horloge qui recule : on ne refait rien


def test_loop_refreshes_once_per_day_and_survives_a_failed_refresh(monkeypatch):
    days = iter([date(2026, 10, 13), date(2026, 10, 13), date(2026, 10, 14), date(2026, 10, 15)])
    calls: list[str | None] = []

    def fake_refresh(db_path=None):
        calls.append(db_path)
        if len(calls) == 2:
            raise RuntimeError("réseau coupé")   # un échec n'arrête pas la boucle

    waits = []
    monkeypatch.setattr(live_refresh, "utc_today", lambda: next(days))
    monkeypatch.setattr(live_refresh, "_refresh_once", fake_refresh)
    monkeypatch.setattr(live_refresh._stop, "wait", lambda timeout: waits.append(timeout) or len(waits) >= 4)

    live_refresh._refresh_loop("x.db")

    assert calls == ["x.db", "x.db", "x.db"]       # 13 (lancement), 14, 15 -- pas de doublon le 13
    assert waits == [live_refresh.REFRESH_CHECK_SECONDS] * 4
    assert live_refresh.refresh_status()["running"] is False


def test_progress_counts_the_signals_judged_and_the_ones_with_the_right_direction(monkeypatch, tmp_path):
    from patrick.tracking import db

    db_path = str(tmp_path / "p.db")
    db.connect(db_path).close()
    cand = live_refresh.PredictCandidate("^VIX", 5, "r1", 1, "a.joblib")
    monkeypatch.setattr(live_refresh, "find_predictable_candidates", lambda conn: [cand, cand])
    details = iter([{"n_outcomes_updated": 3, "n_outcomes_right": 2}, {"n_outcomes_updated": 1, "n_outcomes_right": 0}])
    monkeypatch.setattr(live_refresh, "run_daily_predictions",
                        lambda candidates, db_path=None, on_item=None: [
                            on_item(live_refresh.PredictOutcome(c, True, detail=next(details))) for c in candidates])

    live_refresh._refresh_once(db_path)

    status = live_refresh.refresh_status()
    assert (status["done"], status["judged"], status["judged_right"]) == (2, 4, 2)


def test_page_says_what_the_latest_refresh_judged_and_how_many_were_right(tmp_path, monkeypatch):
    from page_support import FullPageClient as TestClient

    from patrick.tracking import db
    from patrick.webapp.app import app

    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "p.db"))
    db.connect(str(tmp_path / "p.db")).close()
    live_refresh._state.update(running=False, total=5, done=5, failed=0, judged=4, judged_right=3,
                               finished_at="2026-10-13T08:00:00+00:00")
    assert "4 signal(aux) arrivé(s) à échéance, 3 dans le bon sens (75 %)" in TestClient(app).get("/predictions").text

    live_refresh._state.update(judged=0, judged_right=0)
    assert "Dernière évaluation : aucun signal" in TestClient(app).get("/predictions").text   # l'apostrophe est échappée en HTML


@pytest.fixture(autouse=True)
def _reset_state():
    snapshot = dict(live_refresh._state)
    yield
    live_refresh._state.clear()
    live_refresh._state.update(snapshot)


# --- pilote automatique des fonds : un cycle par stratégie activée, après les prédictions du jour -------------------

def test_autopilots_run_after_the_predictions_and_a_failure_never_breaks_the_refresh(monkeypatch, tmp_path):
    from patrick.tracking import db

    db_path = str(tmp_path / "p.db")
    db.connect(db_path).close()
    order: list[str] = []
    monkeypatch.setattr(live_refresh, "find_predictable_candidates", lambda conn: [])
    monkeypatch.setattr(live_refresh, "run_daily_predictions",
                        lambda candidates, db_path=None, on_item=None: order.append("predictions"))

    def failing(path=None):
        order.append("autopilot")
        raise RuntimeError("base verrouillée")
    monkeypatch.setattr(live_refresh, "run_autopilots", failing)

    live_refresh._refresh_once(db_path)                      # ne doit rien lever

    assert order == ["predictions", "autopilot"]
    assert live_refresh.refresh_status()["running"] is False


def test_run_autopilots_cycles_every_enabled_strategy(tmp_path):
    from patrick.fund import store
    from patrick.tracking import db

    db_path = str(tmp_path / "p.db")
    conn = db.connect(db_path)
    on = store.create_strategy(conn, "Pilote", "CTO", 100_000, "2026-01-05")
    store.create_strategy(conn, "Manuelle", "CTO", 100_000, "2026-01-05")
    store.set_autopilot(conn, on, {"enabled": True, "settings": {}})
    conn.close()

    reports = live_refresh.run_autopilots(db_path)

    assert [r["strategy_id"] for r in reports] == [on] and "error" not in reports[0] and reports[0]["selected"] == 0


def test_run_autopilots_first_rolls_the_following_rules_to_the_champion(monkeypatch, tmp_path):
    from patrick.fund import autopilot, systematic
    from patrick.tracking import db

    db_path = str(tmp_path / "p.db")
    db.connect(db_path).close()
    order: list[str] = []
    monkeypatch.setattr(systematic, "roll_to_champions", lambda conn, today=None: order.append("roll") or [])
    monkeypatch.setattr(autopilot, "run_all", lambda conn, today=None: order.append("autopilot") or [])

    live_refresh.run_autopilots(db_path)

    assert order == ["roll", "autopilot"]


def test_a_failing_champion_roll_never_stops_the_autopilot_cycle(monkeypatch, tmp_path):
    from patrick.fund import autopilot, systematic
    from patrick.tracking import db

    db_path = str(tmp_path / "p.db")
    db.connect(db_path).close()
    ran: list[str] = []

    def boom(conn, today=None):
        raise RuntimeError("base verrouillée")
    monkeypatch.setattr(systematic, "roll_to_champions", boom)
    monkeypatch.setattr(autopilot, "run_all", lambda conn, today=None: ran.append("autopilot") or [])

    live_refresh.run_autopilots(db_path)

    assert ran == ["autopilot"]


# --- les modèles dont les fonds ont besoin passent en premier : leur cycle ne dépend pas des ~2 000 autres prédictions -----------

def _candidate(world_trial: int, target: str, horizon: int) -> live_refresh.PredictCandidate:
    return live_refresh.PredictCandidate(target, horizon, f"run_{target}_{horizon}", world_trial, "a.joblib")


def test_the_cells_a_fund_needs_are_predicted_first(monkeypatch, tmp_path):
    db_path = str(tmp_path / "p.db")
    conn = trackdb.connect(db_path)
    world, yesterday = World(conn, monkeypatch), (utc_today() - timedelta(days=1)).isoformat()
    live = [(yesterday, 3, 0.6)]
    cells = {"AAA": world.cell("AAA", 1, live=live, dm_p=0.01),          # retenue par le pilote (Diebold-Mariano seul, horizon 1)
             "BBB": world.cell("BBB", 5, live=live, dm_p=0.01),          # hors de l'horizon du pilote
             "CCC": world.cell("CCC", 1, live=live, dm_p=0.90),          # Diebold-Mariano non concluant : le pilote ne la retient pas
             "DDD": world.cell("DDD", 10, live=live, dm_p=0.90)}         # modèle d'une règle saisie à la main
    sid = store.create_strategy(conn, "Pilote", "CTO", 100_000, "2026-10-01")
    autopilot.configure(conn, sid, {"tier": "dm", "horizons": [1]})
    conn.execute("INSERT INTO fund_rule (rule_id, strategy_id, name, config_json, created_at) VALUES ('rule_x', ?, 'manuelle', ?, '2026-10-01')",
                 (sid, json.dumps({"trial_id": cells["DDD"]})))
    conn.commit()
    conn.close()
    candidates = [_candidate(cells[t], t, h) for t, h in (("BBB", 5), ("CCC", 1), ("AAA", 1), ("DDD", 10))]

    first, rest = live_refresh.split_for_funds(candidates, db_path)

    assert sorted((c.target, c.horizon) for c in first) == [("AAA", 1), ("DDD", 10)]
    assert [(c.target, c.horizon) for c in rest] == [("BBB", 5), ("CCC", 1)]          # l'ordre d'origine est gardé dans chaque lot


def test_without_any_fund_nothing_is_prioritised_and_a_failure_falls_back_to_the_original_order(monkeypatch, tmp_path):
    db_path = str(tmp_path / "p.db")
    trackdb.connect(db_path).close()
    candidates = [_candidate(1, "AAA", 1), _candidate(2, "BBB", 5)]

    assert live_refresh.split_for_funds(candidates, db_path) == ([], candidates)

    monkeypatch.setattr(live_refresh, "_fund_cells", lambda path: (_ for _ in ()).throw(RuntimeError("base verrouillée")))
    assert live_refresh.split_for_funds(candidates, db_path) == ([], candidates)         # une panne ne bloque pas les prédictions


def test_the_refresh_runs_the_fund_cycle_between_the_two_batches(monkeypatch, tmp_path):
    db_path = str(tmp_path / "p.db")
    trackdb.connect(db_path).close()
    first, rest = [_candidate(1, "AAA", 1)], [_candidate(2, "BBB", 5), _candidate(3, "CCC", 1)]
    events: list = []
    monkeypatch.setattr(live_refresh, "find_predictable_candidates", lambda conn: first + rest)
    monkeypatch.setattr(live_refresh, "split_for_funds", lambda candidates, path=None: (first, rest))
    monkeypatch.setattr(live_refresh, "run_daily_predictions",
                        lambda candidates, db_path=None, on_item=None: events.append(("predictions", [c.target for c in candidates])))
    monkeypatch.setattr(live_refresh, "run_autopilots", lambda path=None: events.append("autopilot") or [])

    live_refresh._refresh_once(db_path)

    assert events == [("predictions", ["AAA"]), "autopilot", ("predictions", ["BBB", "CCC"])]
    assert live_refresh.refresh_status()["total"] == 3 and live_refresh.refresh_status()["running"] is False


# --- une passe complète par jour : l'app et la tâche de nuit ne refont pas le travail l'une de l'autre ------------------

def _write_pass(**fields) -> None:
    live_refresh.pass_state_path().write_text(json.dumps(fields), encoding="utf-8")


def _hours_ago(hours: float) -> str:
    return (datetime.now(UTC) - timedelta(hours=hours)).isoformat()


def test_a_complete_pass_finished_a_few_hours_ago_makes_a_new_one_pointless():
    _write_pass(running=False, finished_at=_hours_ago(3), finished_source="nightly", total=10, done=10)

    other = live_refresh.recent_pass()

    assert other is not None and other["why"] == "recent" and other["finished_source"] == "nightly"


def test_an_old_pass_a_missing_marker_or_a_broken_one_never_dispense_from_predicting(monkeypatch):
    assert live_refresh.recent_pass() is None                                    # aucun marqueur : le premier lancement prédit
    _write_pass(running=False, finished_at=_hours_ago(13))
    assert live_refresh.recent_pass() is None                                    # au-delà de 12 h
    live_refresh.pass_state_path().write_text("{pas du json", encoding="utf-8")
    assert live_refresh.recent_pass() is None
    _write_pass(running=False, finished_at="pas une date")
    assert live_refresh.recent_pass() is None
    _write_pass(running=False, finished_at=_hours_ago(-3))                       # horloge qui recule : on ne se fie pas à la date
    assert live_refresh.recent_pass() is None


def test_the_gap_is_a_setting_and_zero_always_predicts(monkeypatch):
    _write_pass(running=False, finished_at=_hours_ago(3))
    monkeypatch.setenv(live_refresh.ENV_MIN_GAP_H, "2")
    assert live_refresh.recent_pass() is None                                    # 3 h > 2 h
    monkeypatch.setenv(live_refresh.ENV_MIN_GAP_H, "0")
    assert live_refresh.recent_pass() is None                                    # 0 : toujours refaire
    monkeypatch.setenv(live_refresh.ENV_MIN_GAP_H, "n'importe quoi")
    assert live_refresh.recent_pass() is not None                                # valeur illisible : le défaut (12 h)


def test_a_pass_running_in_another_live_process_is_waited_for_never_doubled(monkeypatch):
    other_pid = os.getpid() + 1
    _write_pass(running=True, pid=other_pid, started_at=_hours_ago(2), source="nightly")
    monkeypatch.setattr(live_refresh.jobs_db, "worker_process_alive", lambda pid, started_at=None: pid == other_pid)

    assert live_refresh.recent_pass()["why"] == "running"

    monkeypatch.setattr(live_refresh.jobs_db, "worker_process_alive", lambda pid, started_at=None: False)
    assert live_refresh.recent_pass() is None                                    # processus mort (tâche tuée) : on la refait


def test_a_running_marker_of_this_very_process_or_older_than_a_day_is_ignored(monkeypatch):
    monkeypatch.setattr(live_refresh.jobs_db, "worker_process_alive", lambda pid, started_at=None: True)
    _write_pass(running=True, pid=os.getpid(), started_at=_hours_ago(1))
    assert live_refresh.recent_pass() is None
    _write_pass(running=True, pid=os.getpid() + 1, started_at=_hours_ago(live_refresh.MAX_RUNNING_H + 1))
    assert live_refresh.recent_pass() is None                                    # numéro de processus réutilisé après un redémarrage du PC


def test_the_app_does_not_redo_a_pass_the_nightly_task_just_finished_and_shows_its_figures(monkeypatch, tmp_path):
    db_path = str(tmp_path / "p.db")
    trackdb.connect(db_path).close()
    _write_pass(running=False, finished_at=_hours_ago(3), finished_source="nightly", total=2958, done=2950, failed=8, judged=40, judged_right=24)
    calls: list = []
    monkeypatch.setattr(live_refresh, "find_predictable_candidates", lambda conn: calls.append("candidates") or [])
    monkeypatch.setattr(live_refresh, "run_daily_predictions", lambda *a, **k: calls.append("predictions"))
    monkeypatch.setattr(live_refresh, "run_autopilots", lambda path=None: calls.append("autopilot") or [])

    live_refresh._refresh_once(db_path)

    status = live_refresh.refresh_status()
    assert calls == []
    assert (status["running"], status["total"], status["done"], status["failed"], status["judged"], status["judged_right"]) == (False, 2958, 2950, 8, 40, 24)
    assert status["finished_at"] == live_refresh.read_pass_state()["finished_at"]


def test_a_finished_app_pass_leaves_its_marker_and_a_second_one_is_skipped(monkeypatch, tmp_path):
    db_path = str(tmp_path / "p.db")
    trackdb.connect(db_path).close()
    cand = live_refresh.PredictCandidate("^VIX", 5, "r1", 1, "a.joblib")
    monkeypatch.setattr(live_refresh, "find_predictable_candidates", lambda conn: [cand])
    runs: list = []
    monkeypatch.setattr(live_refresh, "run_daily_predictions",
                        lambda candidates, db_path=None, on_item=None: runs.append(1) or [
                            on_item(live_refresh.PredictOutcome(c, True, detail={"n_outcomes_updated": 2, "n_outcomes_right": 1})) for c in candidates])
    monkeypatch.setattr(live_refresh, "run_autopilots", lambda path=None: [])
    for name in ("refresh_pooled_signal", "refresh_metric_panel", "write_weekly_report"):
        monkeypatch.setattr(live_refresh, name, lambda path=None: None)

    live_refresh._refresh_once(db_path)
    marker = live_refresh.read_pass_state()
    live_refresh._refresh_once(db_path)

    assert runs == [1]                                                           # la seconde passe n'a rien refait
    assert marker["running"] is False and marker["finished_source"] == "app" and marker["pid"] == os.getpid()
    assert (marker["total"], marker["done"], marker["judged"], marker["judged_right"]) == (1, 1, 2, 1)


def test_an_aborted_or_crashed_pass_does_not_count_as_done(monkeypatch, tmp_path):
    db_path = str(tmp_path / "p.db")
    trackdb.connect(db_path).close()
    cand = live_refresh.PredictCandidate("^VIX", 5, "r1", 1, "a.joblib")
    monkeypatch.setattr(live_refresh, "find_predictable_candidates", lambda conn: [cand])
    monkeypatch.setattr(live_refresh, "run_autopilots", lambda path=None: [])
    monkeypatch.setattr(live_refresh, "run_daily_predictions", lambda *a, **k: live_refresh.RunSummary(aborted="Disque plein"))

    live_refresh._refresh_once(db_path)
    assert "finished_at" not in live_refresh.read_pass_state() and live_refresh.recent_pass() is None      # disque plein : à refaire

    def crash(*a, **k):
        raise RuntimeError("réseau coupé")
    monkeypatch.setattr(live_refresh, "run_daily_predictions", crash)
    with pytest.raises(RuntimeError):
        live_refresh._refresh_once(db_path)
    assert live_refresh.read_pass_state()["running"] is False and live_refresh.recent_pass() is None        # plantage : pas bloquée « en cours »


def test_an_aborted_pass_keeps_the_previous_completed_one_for_the_page(monkeypatch, tmp_path):
    db_path = str(tmp_path / "p.db")
    trackdb.connect(db_path).close()
    old = _hours_ago(20)
    _write_pass(running=False, finished_at=old, finished_source="nightly", total=5, done=5)
    cand = live_refresh.PredictCandidate("^VIX", 5, "r1", 1, "a.joblib")
    monkeypatch.setattr(live_refresh, "find_predictable_candidates", lambda conn: [cand])
    monkeypatch.setattr(live_refresh, "run_autopilots", lambda path=None: [])
    monkeypatch.setattr(live_refresh, "run_daily_predictions", lambda *a, **k: live_refresh.RunSummary(aborted="Disque plein"))

    live_refresh._refresh_once(db_path)

    assert live_refresh.read_pass_state()["finished_at"] == old
