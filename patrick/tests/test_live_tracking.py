"""Suivi live sur les 4 mouvements : seuils causaux memorises au signal, classe
realisee resolue a l'echeance de l'horizon, comptage « bonnes / jugees » par
mouvement predit, jours de marche ferme (aucune barre = aucune ligne), et
affichage dans /predictions. Sans pipeline ni reseau : DB et series synthetiques."""
from __future__ import annotations

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from patrick import predict as predict_module
from patrick.features.target import classify_return, live_class_thresholds
from patrick.tracking import db
from patrick.tracking import history as trackhistory
from patrick.webapp.app import app


def _series(n=600, seed=0) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2022-01-03", periods=n)
    return pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, n))), index=idx, name="X")


def _seed_trial(conn, target="^VIX", horizon=5):
    db.upsert_snapshot(conn, "s", "h", None, None, None)
    db.create_run(conn, "r", target, horizon, "s", "{}", "c", "g", 1)
    tid = db.create_trial(conn, "r", "GLOBAL", "XGBoost", "none", 5, "shap")
    db.mark_best_trial(conn, tid)
    db.finish_run(conn, "r", "done", n_trials=1)
    return tid


def test_live_thresholds_are_causal():
    s = _series()
    lo, hi = live_class_thresholds(s.iloc[:400], 5)
    corrupted = s.copy()
    corrupted.iloc[400:] = corrupted.iloc[400:] * 5  # futur tordu : ne doit rien changer
    assert live_class_thresholds(corrupted.iloc[:400], 5) == (lo, hi)
    assert lo < 0 < hi


def test_outcome_resolution_stores_the_realized_four_class_index(tmp_path):
    conn = db.connect(str(tmp_path / "p.db"))
    tid = _seed_trial(conn)
    s = _series(120)
    horizon = 5
    signal_pos = 50
    ts = str(s.index[signal_pos])
    db.add_predictions(conn, tid, 0, "live", [ts], [None], [3])
    db.set_live_signal_context(conn, tid, ts, -0.02, 0.02, backfill=False)
    raw = pd.DataFrame({"X": s})
    ret = s.iloc[signal_pos + horizon] / s.iloc[signal_pos] - 1

    assert predict_module._update_live_outcomes(conn, tid, horizon, raw, "X") == 1

    y_true, y_class = conn.execute(
        "SELECT y_true, y_class FROM prediction WHERE trial_id = ? AND ts = ?", (tid, ts)).fetchone()
    assert y_true == (1.0 if ret > 0 else 0.0)  # y_true reste binaire
    assert y_class == classify_return(ret, "L", {"L": (-0.02, 0.02)})


def test_outcome_without_stored_thresholds_leaves_class_unknown(tmp_path):
    conn = db.connect(str(tmp_path / "p.db"))
    tid = _seed_trial(conn)
    s = _series(120)
    ts = str(s.index[50])
    db.add_predictions(conn, tid, 0, "live", [ts], [None], [3])  # ligne anterieure a la migration 0028
    predict_module._update_live_outcomes(conn, tid, 5, pd.DataFrame({"X": s}), "X")
    y_true, y_class = conn.execute("SELECT y_true, y_class FROM prediction WHERE ts = ?", (ts,)).fetchone()
    assert y_true in (0.0, 1.0) and y_class is None


def test_horizon_counts_bars_so_closed_market_days_do_not_elapse(tmp_path):
    conn = db.connect(str(tmp_path / "p.db"))
    tid = _seed_trial(conn)
    s = _series(120)
    pos = len(s) - 3  # signal il y a 3 barres, horizon 5 : pas ecoule, meme si des jours calendaires passent
    ts = str(s.index[pos])
    db.add_predictions(conn, tid, 0, "live", [ts], [None], [2])
    assert predict_module._update_live_outcomes(conn, tid, 5, pd.DataFrame({"X": s}), "X") == 0


def test_bars_to_record_skips_in_sample_bars_and_known_bars():
    idx = pd.bdate_range("2026-09-01", periods=10)
    pool = pd.DataFrame({"f": range(10)}, index=idx)
    model_date = idx[4]
    already = {str(idx[6])}
    todo = predict_module._bars_to_record(pool, already, model_date, max_backfill=400)
    assert [t for t, _ in todo] == [idx[5], idx[7], idx[8], idx[9]]
    assert [b for _, b in todo] == [True, True, True, False]
    # marche ferme : la derniere barre est deja enregistree -> rien a ecrire pour aujourd'hui
    assert idx[9] not in [t for t, _ in predict_module._bars_to_record(pool, {str(idx[9])}, model_date, 400)]


def test_tally_counts_hits_per_predicted_movement(tmp_path):
    conn = db.connect(str(tmp_path / "p.db"))
    tid = _seed_trial(conn)
    rows = [  # (ts, y_true, y_pred, y_class)
        ("2026-09-01", 1.0, 3, 3), ("2026-09-02", 1.0, 3, 2), ("2026-09-03", 0.0, 0, 0),
        ("2026-09-04", 1.0, 2, 2), ("2026-09-05", None, 3, None), ("2026-09-06", 0.0, 3, None),
    ]
    for ts, yt, yp, yc in rows:
        db.add_predictions(conn, tid, 0, "live", [ts], [yt], [yp])
        if yt is not None:
            db.update_prediction_outcome(conn, tid, ts, yt, yc)

    t = trackhistory.live_class_tally_by_target_and_horizon(conn, ["^VIX"], [5])[("^VIX", 5)]

    assert t["classes"][3] == {"n": 2, "hits": 1}   # hausse forte : 1 bonne sur 2 jugees
    assert t["classes"][2] == {"n": 1, "hits": 1}
    assert t["classes"][0] == {"n": 1, "hits": 1}
    assert t["classes"][1] == {"n": 0, "hits": 0}
    assert t["pending"] == 1
    assert (t["direction_n"], t["direction_hits"]) == (5, 4)  # la ligne sans y_class compte pour le sens seulement
    assert t["since"] == "2026-09-01"
    assert trackhistory.live_class_tally_by_target_and_horizon(conn, ["^GSPC"], [5]) == {}


def test_predictions_page_shows_the_tally_in_the_hover_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "p.db"))
    conn = db.connect(str(tmp_path / "p.db"))
    tid = _seed_trial(conn)
    for i, (yt, yc) in enumerate([(1.0, 3), (1.0, 2), (0.0, 0)]):
        ts = f"2026-09-0{i + 1}"
        db.add_predictions(conn, tid, 0, "live", [ts], [None], [3])
        db.update_prediction_outcome(conn, tid, ts, yt, yc)
    db.add_predictions(conn, tid, 0, "live", ["2026-09-09"], [None], [0], y_proba=[0.6])
    conn.close()

    html = TestClient(app).get("/predictions").text

    assert "Réussites par mouvement prédit" in html and "depuis le 2026-09-01" in html
    assert "Baisse forte" in html and "1/3 · 33 %" in html  # hausse forte predite 3x, 1 bonne
    assert html.count("<th>") >= 7  # Actif + une colonne par horizon, pas une ligne par paire


def test_backfilled_bar_is_simulated_as_of_its_own_date(monkeypatch):
    """Anti-fuite : le pool d'une barre reconstituee ne voit AUCUNE donnee posterieure
    a cette barre (les ajustements parametriques sont refaits sur la coupe)."""
    seen = []

    def fake_pool(raw, config, target_col, formulas=None):
        seen.append(raw.index.max())
        return pd.DataFrame({"f": range(len(raw))}, index=raw.index)

    monkeypatch.setattr(predict_module, "build_full_feature_pool", fake_pool)
    raw = pd.DataFrame({"X": range(20)}, index=pd.bdate_range("2026-09-01", periods=20))
    t = raw.index[12]
    pool = predict_module._pool_as_of(raw, None, "X", [], t)
    assert seen == [t] and pool.index.max() == t
