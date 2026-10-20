"""Moniteur de dérive (`patrick/analysis/drift_monitor.py`, `/derive`) : états par couple, courbe de Page-Hinkley identique au test existant,
détail d'un couple."""
from __future__ import annotations

import numpy as np
import pytest
from analysis_support import seed_run
from fastapi.testclient import TestClient

from patrick.analysis import drift_monitor as dm
from patrick.analysis import registry
from patrick.tracking import db as trackdb
from patrick.validation import drift as drift_lib
from patrick.webapp.app import app


def _live(conn, info, hits, *, start="2027-01-04"):
    """Appels live jugés : `hits[i]` = 1 si la direction prédite (hausse) était la bonne."""
    ts = [(np.datetime64(start) + i).astype(str) + " 00:00:00" for i in range(len(hits))]
    y_true = [1.0 if h else 0.0 for h in hits]              # prédit « hausse » (classe 2) : juste si la hausse a eu lieu
    trackdb.add_predictions(conn, info["trial_id"], 0, "live", ts, y_true, [2.0] * len(hits), [0.6] * len(hits), p_up=[0.6] * len(hits))


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    registry.clear_cache()
    conn, info = seed_run(tmp_path, monkeypatch, live=0)
    yield conn, info
    registry.clear_cache()


def test_ph_curve_matches_the_reference_test():
    rng = np.random.default_rng(0)
    hits = list(np.r_[(rng.random(120) < 0.7).astype(int), (rng.random(120) < 0.3).astype(int)])
    curve = dm.ph_curve(hits, drift_lib.PAGE_HINKLEY_DELTA, drift_lib.PAGE_HINKLEY_LAMBDA)
    ref = drift_lib.page_hinkley_test(hits)
    assert curve["values"][-1] == pytest.approx(ref["ph_value"]) and curve["detected_at"] == ref["detected_at"]
    assert curve["detected_at"] is not None and len(curve["values"]) == 240


def test_overview_flags_a_collapsing_model_and_leaves_a_stable_one(seeded):
    conn, info = seeded
    rng = np.random.default_rng(1)
    horizon = info["horizon"]
    n = 200 * horizon                                                  # 200 appels indépendants
    hits = list(np.r_[(rng.random(n // 2) < 0.8).astype(int), (rng.random(n // 2) < 0.2).astype(int)])
    _live(conn, info, hits)
    d = dm.overview(conn)
    row = next(r for r in d["items"] if r["target"] == "TST")
    assert row["horizon"] == horizon and row["n_hits"] == len(hits) and row["n_independent"] == 200
    assert row["concept_drift"] is True and row["action"] == "retrain"
    assert d["counts"]["retrain"] == 1 and d["thresholds"]["ph_lambda"] == drift_lib.PAGE_HINKLEY_LAMBDA


def test_not_testable_with_few_calls_and_psi_alone_never_retrains(seeded):
    conn, info = seeded
    _live(conn, info, [1, 0, 1, 1, 0] * horizon_calls(info))
    trackdb.record_drift_psi_batch(conn, "TST", info["horizon"], {f"f{k}": (0.4 if k < 5 else 0.05) for k in range(10)})   # 5 variables sur 10 à PSI marqué
    row = next(r for r in dm.overview(conn)["items"] if r["target"] == "TST")
    assert row["concept_drift"] is None and row["n_independent"] < 30
    assert row["action"] == "watch" and row["data_level"] in ("watch", "drift") and row["share_significant"] == pytest.approx(0.5)


def horizon_calls(info):
    return info["horizon"]


def test_pair_detail_psi_history_and_live_series(seeded):
    conn, info = seeded
    for at, level in (("2027-01-01 10:00:00", 0.05), ("2027-02-01 10:00:00", 0.3)):
        for k in range(4):
            conn.execute("INSERT INTO drift_psi_history (symbol, horizon, feature, computed_at, psi) VALUES (?, ?, ?, ?, ?)", ("TST", info["horizon"], f"f{k}", at, level * (k + 1) / 4))
    conn.commit()
    _live(conn, info, [1, 1, 0, 1] * 3 * info["horizon"])
    d = dm.pair_detail(conn, "TST", info["horizon"])
    assert [p["at"][:10] for p in d["psi_history"]] == ["2027-01-01", "2027-02-01"] and d["psi_history"][1]["max"] == pytest.approx(0.3)
    assert d["latest"]["n"] == 4 and d["latest"]["features"][0]["psi"] >= d["latest"]["features"][-1]["psi"]
    live = d["live"]
    assert live["n_resolved"] == 12 * info["horizon"] and live["n_independent"] == 12 and len(live["ph"]) == 12 and len(live["dates"]) == 12
    assert live["hit_rate"] == pytest.approx(0.75)


def test_unknown_pair_is_an_empty_detail(seeded):
    conn, _ = seeded
    d = dm.pair_detail(conn, "NOPE", 3)
    assert d["psi_history"] == [] and d["live"]["n_resolved"] == 0 and d["live"]["ph"] == []


def test_drift_pages_and_api(seeded):
    conn, info = seeded
    _live(conn, info, [1, 0, 1] * info["horizon"])
    conn.close()
    c = TestClient(app)
    assert c.get("/derive").status_code == 200 and 'href="/derive"' in c.get("/").text
    ov = c.get("/api/derive/overview")
    assert ov.status_code == 200 and "NaN" not in ov.text and ov.json()["n"] >= 1
    det = c.get(f"/api/derive/detail?target=TST&horizon={info['horizon']}")
    assert det.status_code == 200 and det.json()["live"]["n_resolved"] == 3 * info["horizon"]
