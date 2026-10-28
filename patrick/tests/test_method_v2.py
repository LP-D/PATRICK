"""Méthode d'évaluation 2 (ADR 0008) : test de Diebold-Mariano sur la direction, SHAP sur les lignes récentes, régimes par volatilité,
jours plats retirés de l'entraînement mais gardés dans l'évaluation. La méthode 1 (tout run d'avant le champ) reste exactement l'ancienne."""
from __future__ import annotations

import json
from typing import ClassVar

import numpy as np
import pandas as pd
import pytest

from patrick.config import defaults as D
from patrick.config.schema import RunConfig
from patrick.features import target as T
from patrick.features.alpha_target import run_target
from patrick.pipeline import engine
from patrick.selection import shap_select
from patrick.tracking import db as trackdb
from patrick.tracking import stats as trackstats
from patrick.validation.diebold_mariano import diebold_mariano


def _config(version: int, target="AAPL") -> RunConfig:
    return RunConfig.model_validate({"name": "t", "objective": {"target_symbol": target},
                                     "validation": {"method_version": version}, "output": {"dir": "out"}})


def _prices(n=1200, seed=3, drift=0.0005, vol=0.01) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    return pd.Series(100 * np.exp(np.cumsum(rng.normal(drift, vol, n))), index=idx, name="P")


def _original_build_target(series, horizon, split_idx, flat_thr=0.003, ret=None):
    """Copie de l'implémentation d'avant `TargetSpec` : la méthode 1 doit lui rester identique."""
    s = series.ffill().bfill()
    s_tr = s.iloc[:split_idx]
    calm_thr, stress_thr = s_tr.quantile(0.33), s_tr.quantile(0.67)
    regime = pd.Series("NORMAL", index=s.index)
    regime[s < calm_thr] = "CALM"
    regime[s >= stress_thr] = "STRESS"
    ret = (s.shift(-horizon) / s) - 1 if ret is None else ret.reindex(s.index)
    flat = ret.abs() < flat_thr
    ret = ret.loc[~flat].dropna()
    reg_r = regime.reindex(ret.index)
    safe_fit_cut_date = s.index[max(split_idx - horizon, 0)]
    ret_tr = ret.loc[ret.index < safe_fit_cut_date]
    reg_tr = reg_r.loc[ret_tr.index]
    thr = {}
    for reg in ["CALM", "NORMAL", "STRESS"]:
        sub = ret_tr[reg_tr == reg]
        thr[reg] = (sub.quantile(0.25) if len(sub) >= 20 else ret_tr.quantile(0.25),
                    sub.quantile(0.75) if len(sub) >= 20 else ret_tr.quantile(0.75))
    thr["GLOBAL"] = (ret_tr.quantile(0.25), ret_tr.quantile(0.75))

    def classify(r, reg):
        q25, q75 = thr.get(reg, (0, 0))
        return 0 if r < q25 else 1 if r < 0 else 2 if r < q75 else 3

    return pd.Series([classify(r, reg_r[i]) for i, r in ret.items()], index=ret.index, name=T.TARGET_COL), reg_r, thr


def test_method_one_target_is_identical_to_the_original_implementation():
    price = _prices()
    for horizon, split in ((1, 800), (5, 700), (20, 900)):
        want = _original_build_target(price, horizon, split)
        got = T.build_target(price, horizon, split)
        pd.testing.assert_series_equal(got[0], want[0])
        pd.testing.assert_series_equal(got[1], want[1])
        assert got[2] == want[2]
        assert "flat" not in got[0].attrs


def test_method_two_keeps_the_flat_days_and_marks_them():
    price = _prices()
    legacy, _, _ = T.build_target(price, 1, 800)
    full, regimes, _thr = T.build_target(price, 1, 800, spec=T.METHOD_2)
    flat = full.attrs["flat"]
    assert len(full) > len(legacy)                                             # les jours plats sont étiquetés
    assert flat.sum() == len(full) - int(T.non_flat_mask(full).sum()) > 0
    assert flat.index.equals(full.index) and regimes.index.equals(full.index)
    assert set(full.unique()) <= {0, 1, 2, 3}


def test_method_two_flat_days_are_defined_in_volatility_not_in_absolute_return():
    calm = _prices(seed=1, vol=0.002)                                           # 0,2 % par jour : presque tout est sous 0,3 %
    wild = _prices(seed=1, vol=0.03)
    for price in (calm, wild):
        t1, _, _ = T.build_target(price, 1, 800)
        t2, _, _ = T.build_target(price, 1, 800, spec=T.METHOD_2)
        assert len(t1) > 0 and len(t2) > 0
    share_calm = T.build_target(calm, 1, 800, spec=T.METHOD_2)[0].attrs["flat"].mean()
    share_wild = T.build_target(wild, 1, 800, spec=T.METHOD_2)[0].attrs["flat"].mean()
    assert abs(share_calm - share_wild) < 0.1                                   # la même part, quelle que soit l'échelle
    assert (T.build_target(calm, 1, 800)[0].shape[0] / len(calm)) < 0.5         # l'ancien seuil absolu retirait presque tout


def test_thresholds_are_fitted_on_the_non_flat_training_days_only():
    price = _prices()
    _, _, thr_legacy_like = T.build_target(price, 1, 800, spec=T.TargetSpec(flat_vol_mult=0.25, regime_basis="level", keep_flat=False))
    _, _, thr_keep = T.build_target(price, 1, 800, spec=T.TargetSpec(flat_vol_mult=0.25, regime_basis="level", keep_flat=True))
    assert thr_legacy_like == thr_keep


def test_volatility_regimes_do_not_collapse_for_a_trending_series():
    price = _prices(drift=0.002, vol=0.006)                                    # tendance haussière : le niveau sort de la plage d'entraînement
    by_level = T.regime_series(price, 600, T.METHOD_1)
    by_vol = T.regime_series(price, 600, T.METHOD_2)
    test_part = slice(600, None)
    assert (by_level.iloc[test_part] == "STRESS").mean() > 0.9                  # le défaut d'origine
    assert (by_vol.iloc[test_part] == "STRESS").mean() < 0.6
    assert set(by_vol.unique()) == {"CALM", "NORMAL", "STRESS"}


def test_volatility_regimes_are_causal():
    price = _prices()
    full = T.regime_series(price, 800, T.METHOD_2)
    cut = price.copy()
    cut.iloc[900:] = cut.iloc[900:] * 7                                         # le futur change, le passé ne bouge pas
    again = T.regime_series(cut, 800, T.METHOD_2)
    pd.testing.assert_series_equal(full.iloc[:900], again.iloc[:900])


def test_spec_for_follows_the_run_method_version_and_keeps_levels_for_volatility_indices():
    assert T.spec_for(_config(1)) == T.METHOD_1
    assert T.spec_for(_config(2)) == T.METHOD_2
    assert T.spec_for(_config(2, "^VIX")).regime_basis == "level"
    assert T.spec_for(_config(2, "^VIX")).keep_flat is True


def test_run_target_returns_the_flat_mask_only_for_method_two():
    pool = pd.DataFrame({"AAPL": _prices()})
    assert "flat" not in run_target(pool, _config(1), "AAPL", 1, 800)[0].attrs
    assert "flat" in run_target(pool, _config(2), "AAPL", 1, 800)[0].attrs


def test_non_flat_mask_is_all_true_without_flat_information():
    series = pd.Series([0, 1, 2], index=pd.bdate_range("2020-01-01", periods=3))
    assert T.non_flat_mask(series).all()


# --------------------------------------------------------------------------- Diebold-Mariano sur la direction

def test_direction_loss_counts_the_sign_not_the_class():
    y_true = np.array([0, 1, 2, 3, 2])
    y_pred = np.array([1, 1, 3, 0, 2])
    assert engine._dm_losses(y_true, y_pred, "class4").tolist() == [1, 0, 1, 1, 0]
    assert engine._dm_losses(y_true, y_pred, "direction").tolist() == [0, 0, 0, 1, 0]


def test_an_amplitude_only_model_beats_the_constant_class_baseline_on_four_classes_but_not_on_direction():
    rng = np.random.default_rng(0)
    n = 1500
    y_true = rng.integers(0, 4, n)
    flip = rng.random(n) < 0.5
    pred = np.where(flip, 3 - y_true, y_true)               # amplitude juste, sens tiré au hasard
    baseline = np.full(n, 2)                                 # marche aléatoire sans dérive : toujours la classe 2
    four = diebold_mariano(engine._dm_losses(y_true, pred, "class4"), engine._dm_losses(y_true, baseline, "class4"), h=1)
    direction = diebold_mariano(engine._dm_losses(y_true, pred, "direction"), engine._dm_losses(y_true, baseline, "direction"), h=1)
    assert four["dm_stat"] < 0 and four["p_value"] < 0.01                 # « meilleur » que la baseline sur les 4 classes
    assert not (direction["dm_stat"] < 0 and direction["p_value"] < 0.05)  # mais aucune compétence directionnelle


def test_dm_against_baselines_records_the_loss_it_used():
    rng = np.random.default_rng(1)
    y = rng.integers(0, 4, 300)
    out = engine._dm_against_baselines(y, y, {"BASELINE_persistence": np.full(300, 2)}, None, 1, "direction")
    assert out["common"]["loss"] == "direction"
    assert engine._dm_against_baselines(y, y, {"BASELINE_persistence": np.full(300, 2)}, None, 1)["common"]["loss"] == "class4"


def _db_with_runs(tmp_path):
    conn = trackdb.connect(str(tmp_path / "patrick.db"))
    trackdb.upsert_snapshot(conn, "snap", "hash", 0, 1, "api")
    for run_id, target in (("a1", "AAA"), ("a2", "AAA"), ("b1", "BBB")):
        trackdb.create_run(conn, run_id, target=target, horizon=1, snapshot_id="snap", config_json="{}",
                           config_hash="x", git_sha="x", seed=1)
        trackdb.finish_run(conn, run_id, status="done", n_trials=1)
    return conn


def test_dm_result_stores_the_loss_and_defaults_to_class4(tmp_path):
    conn = _db_with_runs(tmp_path)
    dm = {"baseline": "BASELINE_persistence", "dm_stat": -2.0, "p_value": 0.04, "n_obs": 200}
    trackdb.save_dm_result(conn, "a1", dm, sample="holdout")
    trackdb.save_dm_result(conn, "a2", dm, sample="holdout", loss="direction")
    assert dict(conn.execute("SELECT run_id, loss FROM dm_result")) == {"a1": "class4", "a2": "direction"}
    with pytest.raises(ValueError):
        trackdb.save_dm_result(conn, "b1", dm, sample="holdout", loss="mse")
    conn.close()


def test_the_bh_family_prefers_direction_p_values_and_keeps_legacy_ones_when_alone(tmp_path):
    conn = _db_with_runs(tmp_path)
    low = {"baseline": "BASELINE_persistence", "dm_stat": -3.0, "p_value": 0.001, "n_obs": 200}
    high = {"baseline": "BASELINE_persistence", "dm_stat": -0.1, "p_value": 0.9, "n_obs": 200}
    trackdb.save_dm_result(conn, "a1", low, sample="holdout")                          # AAA : p = 0,001 sur 4 classes...
    trackdb.save_dm_result(conn, "a2", high, kind="class_specific", sample="holdout", loss="direction")    # ...0,9 sur la direction
    trackdb.save_dm_result(conn, "b1", low, sample="holdout")                          # BBB : seulement l'ancienne perte
    result = trackstats.fdr_across_targets(conn, alpha=0.10)["results"]
    assert result["AAA"]["best_run_p_value"] == pytest.approx(0.45)                    # 0,9 bilatéral -> 0,45 unilatéral (ADR 0003)
    assert result["BBB"]["best_run_p_value"] == pytest.approx(0.0005)
    conn.close()


# --------------------------------------------------------------------------- SHAP sur les lignes récentes

class _FakeExplainer:
    seen: ClassVar[list] = []

    def __init__(self, model):
        pass

    def shap_values(self, rows):
        _FakeExplainer.seen.append(np.array(rows))
        return np.zeros((len(rows), rows.shape[1], 4))


def test_shap_ranks_on_the_oldest_rows_by_default_and_on_the_newest_in_method_two(monkeypatch):
    rng = np.random.default_rng(0)
    X = rng.normal(size=(900, 12))
    y = rng.integers(0, 4, 900)
    monkeypatch.setattr(shap_select.shap, "TreeExplainer", _FakeExplainer)
    keep_all = shap_select.prefilter_pool(X, y, 12, 0)
    for recent, rows in ((False, slice(0, 300)), (True, slice(600, 900))):
        _FakeExplainer.seen.clear()
        shap_select.shap_rank(X, y, [], 3, 12, shap_sample=300, seed=0, recent=recent)
        np.testing.assert_array_equal(_FakeExplainer.seen[0], X[:, keep_all][rows])


# --------------------------------------------------------------------------- version, hachage, reprise

def test_the_config_hash_of_a_method_one_run_does_not_see_the_field():
    one, two = _config(1), _config(2)
    assert engine._config_hash(one) != engine._config_hash(two)
    stored = json.loads(one.model_dump_json())
    del stored["validation"]["method_version"]
    assert engine._config_hash(RunConfig.model_validate_json(json.dumps(stored))) == engine._config_hash(one)


def test_the_selector_cache_key_changes_only_for_method_two():
    assert engine._selector_config_hash(_config(1), 10, 1) != engine._selector_config_hash(_config(2), 10, 1)


def test_a_new_run_gets_method_two_and_a_resume_keeps_its_own(monkeypatch):
    seen: list[int] = []

    def spy(objective, *args, **kwargs):
        raise RuntimeError("stop")

    def capture(config, **kwargs):
        pass

    monkeypatch.setattr(engine, "ingest", spy)
    monkeypatch.setattr(engine, "load_snapshot", lambda objective, *a, **k: spy(objective))
    for snapshot_id in (None, "snap-1"):
        cfg = _config(1)
        with pytest.raises(RuntimeError, match="stop"):
            engine.run_pipeline(cfg, snapshot_id=snapshot_id)
        seen.append(cfg.validation.method_version)
    assert seen == [D.CURRENT_METHOD_VERSION, 1]


def test_a_stored_config_without_the_field_reads_as_method_one():
    data = json.loads(_config(2).model_dump_json())
    del data["validation"]["method_version"]
    assert RunConfig.model_validate_json(json.dumps(data)).validation.method_version == 1
    assert RunConfig.from_stored_json(json.dumps(data)).validation.method_version == 1


# --------------------------------------------------------------------------- placebo de décalage par run

class _Pools:
    def __init__(self, frame):
        self.frame = frame

    def get(self, cut_idx):
        return self.frame


def test_the_lagged_pool_delays_every_feature_but_never_the_target_price():
    idx = pd.bdate_range("2020-01-01", periods=6)
    frame = pd.DataFrame({"P": np.arange(6.0), "f1": np.arange(10.0, 16.0), "f2": np.arange(20.0, 26.0)}, index=idx)
    lagged = engine._LaggedPoolBuilder(_Pools(frame), "P", lag=1).get(0)
    pd.testing.assert_series_equal(lagged["P"], frame["P"])
    assert np.isnan(lagged["f1"].iloc[0]) and lagged["f1"].iloc[3] == frame["f1"].iloc[2]
    assert lagged["f2"].iloc[1] == frame["f2"].iloc[0]
    assert frame["f1"].iloc[0] == 10.0                                           # le pool d'origine n'est pas modifié


@pytest.mark.parametrize("real, lagged, expected", [
    ({"AUC_ovr_4cls": 0.69}, {"AUC_ovr_4cls": 0.51}, "same_day"),               # EURUSD h=1 avant la correction
    ({"AUC_ovr_4cls": 0.62}, {"AUC_ovr_4cls": 0.60}, "stable"),
    ({"AUC_ovr_4cls": 0.52}, {"AUC_ovr_4cls": 0.40}, "stable"),                 # pas de signal à perdre
    ({"AUC_ovr_4cls": 0.69}, {}, None), (None, None, None), ({"AUC_ovr_4cls": float("nan")}, {"AUC_ovr_4cls": 0.5}, None),
])
def test_placebo_verdict(real, lagged, expected):
    assert engine.placebo_verdict(real, lagged) == expected


def test_the_placebo_is_stored_per_run_and_variant(tmp_path):
    conn = _db_with_runs(tmp_path)
    trackdb.save_placebo(conn, "a1", "real", {"AUC_ovr_4cls": 0.69, "F1_dir": 0.7, "Other": 1.0, "Acc_dir": None})
    trackdb.save_placebo(conn, "a1", "lag1", {"AUC_ovr_4cls": 0.51})
    assert trackdb.get_placebo(conn, "a1") == {"real": {"AUC_ovr_4cls": 0.69, "F1_dir": 0.7}, "lag1": {"AUC_ovr_4cls": 0.51}}
    assert trackdb.get_placebo(conn, "b1") == {}
    with pytest.raises(ValueError):
        trackdb.save_placebo(conn, "a1", "lag2", {})
    conn.close()
