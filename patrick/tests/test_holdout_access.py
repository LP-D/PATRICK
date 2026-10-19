"""Registre d'accès au holdout (audit externe du 2026-10-19, point 5).

Le holdout terminal n'est protégé que par la discipline de ne s'en servir qu'une fois. Or il est lu à plusieurs
endroits : l'évaluation finale d'un run, le diagnostic qui note TOUS les essais de la grille, et le duel
champion / challenger (qui SÉLECTIONNE sur lui, `pipeline/champion_duel.py`). Rien ne disait combien de fois, ni pour
quel run. `holdout_access` (migration 0038) est un registre append-only, sans clé étrangère (un run supprimé n'efface
pas ses lectures), écrit par l'unique fonction qui lit le holdout, `engine._evaluate_holdout`.
"""
from __future__ import annotations

import sqlite3

import pytest

from patrick.pipeline import champion_duel
from patrick.pipeline import engine as engine_module
from patrick.tracking import db as trackdb
from patrick.tracking import stats as trackstats


def _run(conn, run_id, target="^T", horizon=5):
    trackdb.upsert_snapshot(conn, "snap", "h", 0, 0, None)
    trackdb.create_run(conn, run_id, target=target, horizon=horizon, snapshot_id="snap",
                        config_json="{}", config_hash="c", git_sha="g", seed=42)


def _read(conn, purpose="final_eval", run_id="r1", target="^T", horizon=5,
          start="2025-01-02", end="2026-03-31", n_rows=300):
    trackdb.record_holdout_access(conn, target, horizon, purpose, run_id=run_id,
                                  holdout_start=start, holdout_end=end, n_rows=n_rows)


def test_reads_are_counted_per_purpose_and_per_run(conn):
    for purpose, run_id in [("final_eval", "r1"), ("diagnostic", "r1"), ("diagnostic", "r1"),
                            ("champion_duel_champion", "r2"), ("champion_duel_challenger", "r2")]:
        _read(conn, purpose, run_id)
    reads = trackstats.holdout_reads(conn, "^T", 5)
    assert reads["total"] == 5
    assert reads["n_runs"] == 2
    assert reads["by_purpose"] == {"final_eval": 1, "diagnostic": 2,
                                   "champion_duel_champion": 1, "champion_duel_challenger": 1}
    assert reads["selecting"] == 2          # les lectures qui servent à CHOISIR un modèle : les deux du duel
    assert reads["first_at"] is not None and reads["last_at"] >= reads["first_at"]


def test_reads_are_scoped_to_the_target_and_the_horizon(conn):
    _read(conn, horizon=5)
    _read(conn, horizon=3)
    _read(conn, target="^OTHER", horizon=5)
    assert trackstats.holdout_reads(conn, "^T", 5)["total"] == 1
    assert trackstats.holdout_reads(conn, "^T")["total"] == 2           # tous horizons de la cible
    assert trackstats.holdout_reads(conn, "^NEVER", 5)["total"] == 0


def test_only_reads_that_saw_part_of_this_window_are_counted_when_asked(conn):
    # Le holdout glisse avec les données : une lecture d'une fenêtre sans rapport n'a pas « vu » celle-ci.
    _read(conn, start="2023-01-02", end="2024-03-29")      # avant
    _read(conn, start="2024-01-02", end="2025-03-31")      # chevauche le début
    _read(conn, start="2025-06-02", end="2026-08-31")      # dedans
    window = ("2025-01-01", "2025-12-31")
    assert trackstats.holdout_reads(conn, "^T", 5)["total"] == 3
    assert trackstats.holdout_reads(conn, "^T", 5, overlapping=window)["total"] == 2


def test_the_registry_survives_the_deletion_of_a_run(conn):
    _run(conn, "r1")
    _read(conn, run_id="r1")
    with conn:
        conn.execute("DELETE FROM run WHERE run_id = 'r1'")
    assert trackstats.holdout_reads(conn, "^T", 5)["total"] == 1


def test_an_unknown_purpose_is_refused(conn):
    with pytest.raises(sqlite3.IntegrityError):
        _read(conn, purpose="peek")


# --- fusion entre deux PC -------------------------------------------------------------------------------------------

def test_the_merge_unites_the_registries_without_duplicates(tmp_path):
    from test_sync_merge import _pair

    from patrick import sync_merge

    local, remote = _pair(tmp_path, ["a1"], ["b1"])
    insert = ("INSERT INTO holdout_access (accessed_at, target, horizon, purpose, run_id, holdout_start, "
              "holdout_end, n_rows) VALUES (?, '^T', 5, ?, ?, '2025-01-02', '2026-03-31', 300)")
    for path, rows in ((local, [("2026-10-01 10:00:00", "final_eval", "a1"),
                                ("2026-10-02 10:00:00", "diagnostic", "a1")]),
                       (remote, [("2026-10-02 10:00:00", "diagnostic", "a1"),    # le même événement, vu des deux côtés
                                 ("2026-10-03 10:00:00", "final_eval", "b1")])):
        conn = sqlite3.connect(str(path))
        conn.executemany(insert, rows)
        conn.commit()
        conn.close()

    sync_merge.merge_databases(str(local), str(remote))
    sync_merge.merge_databases(str(local), str(remote))        # idempotent
    conn = sqlite3.connect(str(local))
    assert conn.execute("SELECT COUNT(*) FROM holdout_access").fetchone()[0] == 3
    conn.close()


# --- un moteur plus ancien resté en mémoire du worker ---------------------------------------------------------------

def test_the_duel_still_reads_the_holdout_through_an_engine_without_the_registry(monkeypatch):
    """Un worker démarré avant la mise à jour garde l'ancien `engine` en mémoire mais charge `champion_duel` à la fin
    du run (même cas que `persist_holdout`) : l'ancienne `_evaluate_holdout` n'a ni `purpose` ni `run_id`."""
    calls = []

    def old_engine(conn, snapshot_id, pool_builder, target_col, feature_pool, config, all_dates_full, n_wf,
                   best_cfg, seed, universe=None):
        calls.append("old")
        return {"metrics": {}}

    monkeypatch.setattr(engine_module, "_evaluate_holdout", old_engine)
    out = champion_duel._read_holdout("champion_duel_champion", "r1", None, None, None, None, [], None, None, 0,
                                      {}, 42)
    assert out == {"metrics": {}} and calls == ["old"]


def test_the_duel_passes_its_purpose_and_run_to_an_engine_with_the_registry(monkeypatch):
    seen = {}

    def new_engine(conn, snapshot_id, pool_builder, target_col, feature_pool, config, all_dates_full, n_wf,
                   best_cfg, seed, universe=None, *, purpose, run_id=None):
        seen.update(purpose=purpose, run_id=run_id)
        return {"metrics": {}}

    monkeypatch.setattr(engine_module, "_evaluate_holdout", new_engine)
    champion_duel._read_holdout("champion_duel_champion", "r1", None, None, None, None, [], None, None, 0, {}, 42)
    assert seen == {"purpose": "champion_duel_champion", "run_id": "r1"}


# --- page d'un run ---------------------------------------------------------------------------------------------------

def test_the_run_page_tells_how_many_times_the_holdout_was_read(tmp_path, monkeypatch):
    import json

    from page_support import FullPageClient as TestClient

    from patrick.webapp.app import app

    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    conn = trackdb.connect(str(tmp_path / "patrick.db"))
    trackdb.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    trackdb.create_run(conn, "run1", "^VIX", 5, "snap1", json.dumps({"validation": {"scheme": "walkforward"}}),
                       "cfghash", "sha", 42)
    trial_id = trackdb.create_trial(conn, "run1", "GLOBAL", "XGBoost", "SMOTE", 8, "shap")
    trackdb.mark_best_trial(conn, trial_id)
    trackdb.add_fold_metrics(conn, trial_id, 1, "test", {"F1_dir": 0.6})
    trackdb.finish_run(conn, "run1", status="done", n_trials=1)
    for purpose in ("final_eval", "diagnostic", "champion_duel_champion", "champion_duel_challenger"):
        trackdb.record_holdout_access(conn, "^VIX", 5, purpose, run_id="run1", holdout_start="2025-01-02",
                                      holdout_end="2026-03-31", n_rows=300)
    conn.close()

    html_ = TestClient(app).get("/runs/run1/detail").text
    assert "Lectures du holdout" in html_
    assert "dont 2 pour choisir un modèle" in html_
