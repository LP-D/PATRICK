"""Estimation des durées (`tracking/eta.py`) : temps actif hors veille et pause, réglages identiques, moyenne par étape, file d'attente."""
from __future__ import annotations

import json
import time
from datetime import UTC, datetime

import pytest

from patrick.system import awake_clock
from patrick.tracking import eta, jobs
from patrick.webapp import run_manager


def _ts(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%d %H:%M:%S")


def _cfg(algos=("XGBoost", "LightGBM"), trials=None, horizons=(1,), target="AAA", name=None) -> dict:
    return {"name": name or f"{target}_1", "objective": {"target_symbol": target, "horizons": list(horizons), "regimes": ["GLOBAL"]},
            "models": {"algos": list(algos)}, "tuning": {"enabled": trials is not None, "n_trials": trials or 100},
            "validation": {"scheme": "walkforward", "n_wf_folds": 3}, "selection": {"method": "shap"},
            "features": {"families": ["technical"]}, "universe": {"yf_tickers": ["^GSPC"], "fred_series": {}}}


def _done_job(conn, job_id: str, cfg: dict, start: float, phases: list[tuple[str, float]]) -> float:
    """Un job terminé dont les étapes durent `phases` (secondes, dans l'ordre) ; renvoie la fin."""
    t = start
    for phase, seconds in phases:
        jobs.record_job_phase(conn, job_id, phase, t, t + seconds)
        t += seconds
    with conn:
        conn.execute("INSERT INTO job (job_id, config_json, status, created_at, started_at, finished_at) VALUES (?, ?, 'done', ?, ?, ?)",
                     (job_id, json.dumps(cfg), _ts(start), _ts(start), _ts(t)))
    return t


def test_active_seconds_removes_overlapping_idle_spans():
    idle = eta.merge_intervals([(10.0, 20.0), (15.0, 30.0), (50.0, 60.0)])
    assert idle == [(10.0, 30.0), (50.0, 60.0)]
    assert eta.active_seconds(0.0, 100.0, idle) == pytest.approx(70.0)
    assert eta.active_seconds(25.0, 55.0, idle) == pytest.approx(20.0)       # 30 s moins 25-30 et 50-55
    assert eta.active_seconds(12.0, 28.0, idle) == 0.0
    assert eta.active_seconds(5.0, 5.0, idle) == 0.0


def test_suspension_detected_only_beyond_threshold():
    assert awake_clock.suspended_between(0.0, 0.0, 5.0, 5.0) == 0.0
    assert awake_clock.suspended_between(0.0, 0.0, 15.0, 5.0) == 0.0          # 10 s d'écart : gigue, pas une veille
    assert awake_clock.suspended_between(0.0, 0.0, 3605.0, 5.0) == pytest.approx(3600.0)
    assert isinstance(awake_clock.awake_seconds(), float)


def test_signatures_ignore_target_and_name_but_not_settings():
    a = eta.signatures(_cfg(target="AAA"))
    b = eta.signatures(_cfg(target="BBB", name="other"))
    assert a == b
    c = eta.signatures(_cfg(trials=100))
    assert c[0] != a[0] and c[1] != a[1] and c[2] == a[2] == "ml"
    assert eta.signatures(_cfg(algos=("MLP", "GRU")))[2] == "dl"
    assert eta.signatures({"kind": "rl", "rl": {"algo": "PPO", "total_timesteps": 1000}})[2] == "rl"


def test_trimmed_mean_resists_one_outlier():
    assert eta.trimmed_mean([100.0] * 9 + [10_000.0]) == pytest.approx(100.0)
    assert eta.trimmed_mean([10.0, 20.0]) == pytest.approx(15.0)


def test_history_averages_steps_at_identical_settings_and_excludes_sleep(conn):
    start = time.time() - 100_000
    end1 = _done_job(conn, "j1", _cfg(target="AAA"), start, [("ingestion", 60), ("features", 300), ("scan", 1200), ("export", 240)])
    # Deuxième run identique, mais le PC a dormi une heure pendant le balayage : le temps de veille ne compte pas.
    s2 = end1 + 100
    _done_job(conn, "j2", _cfg(target="BBB"), s2, [("ingestion", 60), ("features", 300), ("scan", 1200 + 3600), ("export", 240)])
    jobs.record_suspension(conn, s2 + 400, s2 + 400 + 3600)
    # Un run aux réglages différents (réglage Optuna) n'entre pas dans la moyenne « identique ».
    _done_job(conn, "j3", _cfg(trials=50), s2 + 20_000, [("ingestion", 60), ("features", 300), ("scan", 600), ("tuning", 5000), ("export", 240)])

    est = eta.build_history(conn).estimate(_cfg(target="CCC"))
    assert est.basis == "exact" and est.n == 2
    assert est.order == ["ingestion", "features", "scan", "export"]
    assert est.phases["scan"] == pytest.approx(1200, abs=2)
    assert est.total_s == pytest.approx(1800, abs=5)

    near = eta.build_history(conn).estimate({**_cfg(trials=50), "universe": {"yf_tickers": ["^GSPC", "^VIX"], "fred_series": {}}})
    assert near.basis == "near" and near.n == 1 and "tuning" in near.phases

    family = eta.build_history(conn).estimate(_cfg(algos=("CatBoost",)))
    assert family.basis == "family" and family.phases == {} and family.n == 3
    assert eta.build_history(conn).estimate({"kind": "rl", "rl": {}}) is None


def test_remaining_uses_rest_of_current_step_then_following_steps():
    est = eta.Estimate(total_s=1800, phases={"ingestion": 60, "features": 300, "scan": 1200, "export": 240},
                       order=["ingestion", "features", "scan", "export"], basis="exact", n=4)
    rest, overdue = eta.remaining_seconds(est, "scan", 560, {"ingestion": 60, "features": 300, "scan": 200})
    assert rest == pytest.approx(1000 + 240) and not overdue
    # étape plus longue que d'habitude : on lui laisse encore 5 % de sa moyenne, jamais zéro
    rest, _ = eta.remaining_seconds(est, "scan", 1700, {"scan": 1500})
    assert rest == pytest.approx(60 + 240)
    # étape inconnue de l'historique : durée totale moins le temps actif écoulé
    rest, overdue = eta.remaining_seconds(est, "mystery", 2000)
    assert rest == 0.0 and overdue


def test_paused_time_is_not_counted_and_queue_total_sums_estimates(conn, monkeypatch):
    now = time.time()
    _done_job(conn, "past1", _cfg(), now - 50_000, [("ingestion", 60), ("features", 300), ("scan", 1200), ("export", 240)])
    _done_job(conn, "past2", _cfg(), now - 40_000, [("ingestion", 60), ("features", 300), ("scan", 1200), ("export", 240)])
    with conn:
        conn.execute("INSERT INTO job (job_id, config_json, status, created_at, started_at, phase, progress_done, progress_total) "
                     "VALUES ('run', ?, 'running', ?, ?, 'scan', 0, 0)", (json.dumps(_cfg(target="ZZZ")), _ts(now - 1000), _ts(now - 1000)))
        conn.execute("INSERT INTO job (job_id, config_json, status, created_at) VALUES ('q1', ?, 'queued', ?)", (json.dumps(_cfg(target="Q1")), _ts(now)))
        conn.execute("INSERT INTO job (job_id, config_json, status, created_at) VALUES ('q2', ?, 'queued', ?)",
                     (json.dumps(_cfg(algos=("Unseen",), target="Q2")), _ts(now + 1)))
    jobs.record_job_phase(conn, "run", "ingestion", now - 1000, now - 940)
    jobs.record_job_phase(conn, "run", "features", now - 940, now - 640)
    # 300 s de pause pendant le balayage en cours
    with conn:
        conn.execute("INSERT INTO machine_idle (started_at, ended_at, reason, job_id) VALUES (?, ?, 'pause', 'run')", (_ts(now - 500), _ts(now - 200)))

    monkeypatch.setattr(run_manager, "_connect", lambda: conn.__class__(conn.execute("PRAGMA database_list").fetchone()[2], timeout=30))
    active = run_manager.active_run()
    assert active["elapsed_s"] == pytest.approx(700, abs=3)                   # 1 000 s d'horloge - 300 s de pause
    assert active["eta_basis"] == "exact" and active["eta_n"] == 2
    assert active["estimated_remaining_s"] == pytest.approx((1200 - 340) + 240, abs=5)
    queue = run_manager.queued_runs()
    assert queue[0]["estimated_duration_s"] == pytest.approx(1800, abs=5)
    assert queue[1]["estimated_duration_s"] == pytest.approx(1800, abs=5) and queue[1]["eta_basis"] == "family"
    summary = run_manager.queue_eta(active, queue)
    assert summary["total_s"] == pytest.approx(active["estimated_remaining_s"] + 3600, abs=10)
    assert summary["unknown"] == 0 and summary["n"] == 3


def test_pause_and_resume_record_an_idle_span(conn):
    with conn:
        conn.execute("INSERT INTO job (job_id, config_json, status) VALUES ('p', '{}', 'running')")
    assert jobs.set_job_paused(conn, "p", True)
    assert jobs.set_job_paused(conn, "p", True)                                  # deuxième clic : une seule période ouverte
    assert conn.execute("SELECT COUNT(*) FROM machine_idle WHERE ended_at IS NULL").fetchone()[0] == 1
    assert jobs.set_job_paused(conn, "p", False)
    assert conn.execute("SELECT COUNT(*) FROM machine_idle WHERE ended_at IS NULL").fetchone()[0] == 0
    jobs.set_job_paused(conn, "p", True)
    jobs.finish_job(conn, "p", "done")
    assert conn.execute("SELECT COUNT(*) FROM machine_idle WHERE ended_at IS NULL").fetchone()[0] == 0


def test_worker_capture_records_each_step_once_per_change(conn, capsys):
    from patrick.system import worker

    with conn:
        conn.execute("INSERT INTO job (job_id, config_json, status) VALUES ('w', '{}', 'running')")
    capture = worker._ProgressCapture(conn, "w", pid=1)
    for line in ["téléchargement", "[FEATURES] base pool", "[FEATURES] encore", "[SCAN] 3 evaluations", "[EXPORT] fichier"]:
        capture.write(line + "\n")
    capture.final_flush()
    rows = [r[0] for r in conn.execute("SELECT phase FROM job_phase_timing WHERE job_id = 'w' ORDER BY rowid")]
    assert rows == ["ingestion", "features", "scan", "export"]
