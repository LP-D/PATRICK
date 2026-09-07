"""Phase 4 (log de timing lisible par run) -- complément texte brut à
`run_phase_timing` (table SQLite, `tracking/db.py::record_phase_timing`) pour
inspecter le timing d'un run sans requête DB. Réutilise
`tracking.history.phase_breakdown_for_run()` pour l'agrégation (mêmes
sommes/occurrences/`unaccounted_s` qu'affiche déjà la webapp) -- ce fichier ne
teste que la mise en forme texte (`format_phase_timing_report`, fonction pure)
et l'écriture sur disque (`write_phase_timing_log`) séparément de tout run
réel. Le test d'exécution réelle bout-en-bout est en bas de fichier, marqué
`slow` comme les autres tests pipeline complets (cf. `test_predict_live.py`,
`test_pipeline_smoke.py`).
"""
from __future__ import annotations

import os
import sqlite3

import numpy as np
import pandas as pd
import pytest

from patrick.tracking import db
from patrick.tracking import history as trackhistory
from patrick.tracking import phase_timing_log


def _make_run(conn, run_id: str, target: str = "^VIX", horizon: int = 5) -> None:
    db.upsert_snapshot(conn, f"snap_{run_id}", f"hash_{run_id}", None, None, None)
    db.create_run(conn, run_id, target, horizon, f"snap_{run_id}", "{}", "cfghash", "sha", 42)


# ---------------------------------------------------------------------------
# format_phase_timing_report -- fonction pure (pas de DB, pas de disque)
# ---------------------------------------------------------------------------

def test_format_includes_run_id_and_total():
    breakdown = {"run_total_s": 143, "unaccounted_s": 0, "phases": []}
    text = phase_timing_log.format_phase_timing_report("run1", breakdown)
    assert "run1" in text
    assert "143s" in text


def test_format_has_pipe_delimited_header_phase_duree_pct():
    breakdown = {"run_total_s": 100, "unaccounted_s": 0, "phases": []}
    text = phase_timing_log.format_phase_timing_report("run1", breakdown)
    header_line = next(line for line in text.splitlines() if "phase" in line and "|" in line)
    parts = [p.strip() for p in header_line.split("|")]
    assert parts[0] == "phase"
    assert "dur" in parts[1]  # "durée" -- tolère un test lancé sans accent selon l'éditeur
    assert "% du total" in parts[2]


def test_format_lists_each_phase_with_duration_and_percentage():
    breakdown = {
        "run_total_s": 100,
        "unaccounted_s": 0,
        "phases": [
            {"phase": "scan", "duration_s": 60, "occurrences": 1},
            {"phase": "ingestion", "duration_s": 40, "occurrences": 1},
        ],
    }
    text = phase_timing_log.format_phase_timing_report("run1", breakdown)
    lines = text.splitlines()
    scan_line = next(l for l in lines if l.strip().startswith("scan"))
    ingestion_line = next(l for l in lines if l.strip().startswith("ingestion"))
    assert "60s" in scan_line and "60.0%" in scan_line
    assert "40s" in ingestion_line and "40.0%" in ingestion_line
    # Ordre = ordre reçu (déjà trié par duree desc par phase_breakdown_for_run,
    # pas re-trié ici).
    assert lines.index(scan_line) < lines.index(ingestion_line)


def test_format_marks_phases_with_more_than_one_occurrence():
    """`tuning` peut survenir plusieurs fois par run_id (une fois par
    top-config Optuna, cf. record_phase_timing docstring) -- le nombre
    d'occurrences doit être visible, pas silencieusement absorbé dans la
    seule durée sommée."""
    breakdown = {
        "run_total_s": 50,
        "unaccounted_s": 0,
        "phases": [{"phase": "tuning", "duration_s": 50, "occurrences": 2}],
    }
    text = phase_timing_log.format_phase_timing_report("run1", breakdown)
    assert "tuning" in text
    assert "2" in text  # occurrences visibles quelque part sur la ligne


def test_format_includes_unaccounted_time_when_present():
    breakdown = {
        "run_total_s": 100,
        "unaccounted_s": 34,
        "phases": [{"phase": "scan", "duration_s": 66, "occurrences": 1}],
    }
    text = phase_timing_log.format_phase_timing_report("run1", breakdown)
    unaccounted_line = next(l for l in text.splitlines() if "34s" in l)
    assert "34.0%" in unaccounted_line


def test_format_handles_unknown_total_without_crashing():
    """Un run encore `running` (pas de finished_at) -> run_total_s=None,
    phase_breakdown_for_run docstring -- ne doit jamais lever, juste ne pas
    afficher de pourcentage calculable."""
    breakdown = {"run_total_s": None, "unaccounted_s": None, "phases": [
        {"phase": "ingestion", "duration_s": 12, "occurrences": 1},
    ]}
    text = phase_timing_log.format_phase_timing_report("run1", breakdown)
    assert "12s" in text
    assert "n/a" in text.lower() or "inconnu" in text.lower()


def test_format_handles_no_phases_recorded():
    breakdown = {"run_total_s": None, "unaccounted_s": None, "phases": []}
    text = phase_timing_log.format_phase_timing_report("run1", breakdown)
    assert isinstance(text, str) and len(text) > 0


def test_format_matches_real_phase_breakdown_shape(tmp_path):
    """Vérifie que la fonction accepte tel quel le format de sortie réel de
    `phase_breakdown_for_run` (pas une reconstruction manuelle qui dérive du
    vrai schéma)."""
    conn = db.connect(str(tmp_path / "patrick.db"))
    _make_run(conn, "run1")
    db.finish_run(conn, "run1", status="done", n_trials=1)
    db.record_phase_timing(conn, "run1", "ingestion", started_at=0.0, finished_at=10.0)
    db.record_phase_timing(conn, "run1", "scan", started_at=10.0, finished_at=70.0)
    breakdown = trackhistory.phase_breakdown_for_run(conn, "run1")
    conn.close()

    text = phase_timing_log.format_phase_timing_report("run1", breakdown)
    assert "scan" in text and "ingestion" in text


# ---------------------------------------------------------------------------
# write_phase_timing_log -- écriture sur disque
# ---------------------------------------------------------------------------

def test_write_phase_timing_log_creates_file_named_by_run_id(tmp_path):
    breakdown = {"run_total_s": 10, "unaccounted_s": 0,
                 "phases": [{"phase": "scan", "duration_s": 10, "occurrences": 1}]}
    out_dir = str(tmp_path / "runs")
    path = phase_timing_log.write_phase_timing_log(out_dir, "my_run_h5_abcd1234", breakdown)

    assert os.path.exists(path)
    assert "my_run_h5_abcd1234" in os.path.basename(path)
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert content == phase_timing_log.format_phase_timing_report("my_run_h5_abcd1234", breakdown)


def test_write_phase_timing_log_creates_output_dir_if_missing(tmp_path):
    breakdown = {"run_total_s": 1, "unaccounted_s": 0, "phases": []}
    out_dir = str(tmp_path / "does_not_exist_yet")
    path = phase_timing_log.write_phase_timing_log(out_dir, "run1", breakdown)
    assert os.path.exists(path)


# ---------------------------------------------------------------------------
# Exécution réelle bout-en-bout -- run pipeline complet minimal, ingest()
# mocké (pas de réseau), données synthétiques -- cf. test_predict_live.py /
# test_pipeline_smoke.py pour le même schéma de test.
# ---------------------------------------------------------------------------

TARGET_SYMBOL = "^TEST"
HORIZON = 5


def _synthetic_raw(n=1500, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    target = 100 + np.cumsum(rng.normal(0, 0.5, n))
    df = pd.DataFrame({"IDX_TEST": target}, index=idx)
    df["SPX_LIKE"] = 3000 + np.cumsum(rng.normal(0, 5, n))
    df["NFCI"] = np.cumsum(rng.normal(0, 0.02, n))
    df["T10Y2Y"] = np.cumsum(rng.normal(0, 0.01, n))
    return df


def _tiny_config(tmp_path):
    from patrick.config.schema import RunConfig
    raw_yaml = {
        "name": "phase_timing_log_test",
        "objective": {"target_symbol": TARGET_SYMBOL, "horizons": [HORIZON], "regimes": ["GLOBAL"]},
        "universe": {
            "yf_tickers": ["SPX_LIKE"],
            "fred_series": {"NFCI": "NFCI", "T10Y2Y": "T10Y2Y"},
            "start_date": "2015-01-01",
        },
        "features": {
            "families": ["technical", "interactions", "spike", "vol_models", "macro"],
            "interact_top_base": 15, "interact_top_pairs": 8, "interact_final_n": 6,
            "pool_prefilter": 60,
        },
        "validation": {"n_wf_folds": 2, "min_train_frac": 0.5},
        "selection": {"method": "shap", "n_features_grid": [5, 8], "shap_sample": 200},
        "sampler": {"candidates": ["SMOTE"]},
        "models": {"algos": ["RandomForest", "XGBoost"]},
        "tuning": {"enabled": False, "top_k": 2, "n_trials": 3, "cv_splits": 2},
        "output": {"dir": str(tmp_path / "runs"), "seed": 42},
    }
    return RunConfig.model_validate(raw_yaml)


@pytest.mark.slow
def test_run_pipeline_writes_readable_phase_timing_log(tmp_path, monkeypatch):
    from patrick.data.store import DataStore
    from patrick.pipeline import engine as engine_module

    raw = _synthetic_raw()
    monkeypatch.setattr(
        engine_module, "ingest",
        lambda objective, universe, store=None, force=False, data_quality=None: raw)

    db_path = str(tmp_path / "patrick.db")
    store = DataStore(root=str(tmp_path / "store"))
    config = _tiny_config(tmp_path)
    result = engine_module.run_pipeline(config, store=store, db_path=db_path)
    assert result["model_path"] is not None

    conn = sqlite3.connect(db_path)
    run_id = conn.execute("SELECT run_id FROM run WHERE horizon = ?", (HORIZON,)).fetchone()[0]
    conn.close()

    expected_path = os.path.join(config.output.dir, f"{run_id}_phase_timing.txt")
    assert os.path.exists(expected_path), f"fichier attendu absent: {expected_path}"

    with open(expected_path, encoding="utf-8") as f:
        content = f.read()

    assert run_id in content
    # Au moins une phase connue du pipeline complet doit apparaitre.
    assert any(phase in content for phase in
               ("ingestion", "pool_construction", "scan", "export"))
    # Format demande : "phase | duree | % du total" -- verifie la presence
    # d'un en-tete pipe-delimite avec ces 3 colonnes.
    header_line = next(line for line in content.splitlines() if "phase" in line and "|" in line)
    assert header_line.count("|") == 2
