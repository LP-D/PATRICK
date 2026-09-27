"""Correlation-clustering reduction of the candidate universe
(`selection/universe_reduction.py`), decided inside each fold from its
training bars only, and the predict/explain rebuild restricted to the
series a model needs. Ported from feature/replay-cache-universe (3174010),
where the reduction was decided once, before training."""
from __future__ import annotations

import warnings

import joblib
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sklearn.preprocessing import RobustScaler
from starlette.datastructures import FormData

from patrick.config import defaults as D
from patrick.config.schema import RunConfig
from patrick.pipeline import engine as engine_module
from patrick.selection import universe_reduction as ur
from patrick.tracking import db as trackdb
from patrick.tracking.export import export_best_model, scale_selected
from patrick.validation import cpcv as cpcv_module
from patrick.webapp import forms


def _prices(n=400, seed=0) -> dict[str, pd.Series]:
    """A1/A2/A3 share one driver, B1/B2 another, C is independent."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2010-01-01", periods=n)
    fa, fb = rng.normal(0, 0.01, n), rng.normal(0, 0.01, n)
    rets = {
        "A1": fa + rng.normal(0, 0.001, n), "A2": fa + rng.normal(0, 0.001, n),
        "A3": -fa + rng.normal(0, 0.001, n),  # anti-correlated: same cluster under 1-|corr|
        "B1": fb + rng.normal(0, 0.001, n), "B2": fb + rng.normal(0, 0.001, n),
        "C": rng.normal(0, 0.01, n),
    }
    return {k: pd.Series(100 * np.cumprod(1 + v), index=idx) for k, v in rets.items()}


def _pair(n: int, identical: np.ndarray, seed: int = 1) -> pd.DataFrame:
    """X and Y independent, except on the bars where `identical` is True
    (Y's return equals X's there)."""
    rng = np.random.default_rng(seed)
    r1, r2 = rng.normal(0, 0.01, n), rng.normal(0, 0.01, n)
    r2[identical] = r1[identical]
    idx = pd.bdate_range("2010-01-01", periods=n)
    return pd.DataFrame({"X": 100 * np.cumprod(1 + r1), "Y": 100 * np.cumprod(1 + r2)}, index=idx)


# --- clustering (ported) -----------------------------------------------------

def test_correlated_series_end_up_in_the_same_cluster():
    prices = _prices()
    clusters = ur.correlation_clusters(prices, as_of=prices["A1"].index[-1], corr_threshold=0.9)
    assert clusters["A1"] == clusters["A2"] == clusters["A3"]
    assert clusters["B1"] == clusters["B2"]
    assert len({clusters["A1"], clusters["B1"], clusters["C"]}) == 3


def test_reduce_universe_keeps_one_representative_per_cluster():
    prices = _prices()
    res = ur.reduce_universe(prices, as_of=prices["A1"].index[-1], corr_threshold=0.9)
    assert sorted(res.kept) == ["A1", "B1", "C"]  # tie on history length -> alphabetical
    assert res.dropped == {"A2": "A1", "A3": "A1", "B2": "B1"}


def test_representative_is_the_member_with_the_longest_training_history():
    prices = _prices()
    prices["A1"] = prices["A1"].where(prices["A1"].index >= prices["A1"].index[20])  # A1 starts later
    res = ur.reduce_universe(prices, as_of=prices["A1"].index[-1], corr_threshold=0.9)
    assert res.dropped["A1"] == "A2" and "A2" in res.kept


def test_correlation_at_T_ignores_data_after_T():
    """Independent up to T, identical after T: no merge at T; a lookback
    that sees the future would merge them."""
    n, t_idx = 600, 299
    frame = _pair(n, np.arange(n) > t_idx)
    res = ur.reduce_universe(frame, as_of=frame.index[t_idx], corr_threshold=0.9, lookback=252)
    assert res.dropped == {}
    late = ur.reduce_universe(frame, as_of=frame.index[-1], corr_threshold=0.9, lookback=252)
    assert late.dropped == {"Y": "X"}


def test_future_values_are_never_read():
    prices = _prices()
    as_of = prices["A1"].index[250]
    clean = ur.reduce_universe(prices, as_of=as_of, corr_threshold=0.9)
    poisoned = {k: v.copy() for k, v in prices.items()}
    for s in poisoned.values():
        s.iloc[251:] = np.random.default_rng(9).normal(0, 1e6, len(s) - 251)
    dirty = ur.reduce_universe(poisoned, as_of=as_of, corr_threshold=0.9)
    assert dirty.dropped == clean.dropped and dirty.kept == clean.kept


def test_aggressive_threshold_warns_but_does_not_block():
    prices = _prices()
    with pytest.warns(ur.AggressiveReductionWarning):
        res = ur.reduce_universe(prices, as_of=prices["A1"].index[-1], corr_threshold=0.5)
    assert res.kept


def test_non_aggressive_threshold_does_not_warn():
    prices = _prices()
    with warnings.catch_warnings():
        warnings.simplefilter("error", ur.AggressiveReductionWarning)
        ur.reduce_universe(prices, as_of=prices["A1"].index[-1], corr_threshold=0.95)


def test_series_with_missing_values_on_the_window_are_kept_not_dropped():
    prices = _prices()
    late = prices["A2"].copy()
    late.iloc[:390] = np.nan
    prices["A2"] = late
    res = ur.reduce_universe(prices, as_of=prices["A1"].index[-1], corr_threshold=0.9)
    assert "A2" in res.kept and "A2" in res.not_eligible


def test_too_few_training_returns_reduces_nothing():
    prices = _prices()
    res = ur.reduce_universe(prices, as_of=prices["A1"].index[30], corr_threshold=0.9)
    assert res.dropped == {} and res.skipped_reason


def test_series_crossing_zero_use_differences_and_stay_eligible():
    rng = np.random.default_rng(3)
    idx = pd.bdate_range("2010-01-01", periods=400)
    spread = pd.Series(np.sin(np.linspace(0, 6 * np.pi, 400)) + rng.normal(0, 0.05, 400), index=idx)
    assert (spread < 0).any() and (spread > 0).any()
    frame = pd.DataFrame({"S1": spread, "S2": 3 * spread + rng.normal(0, 1e-4, 400),
                          "Z": 100 + np.cumsum(rng.normal(0, 1, 400))}, index=idx)
    res = ur.reduce_universe(frame, as_of=idx[-1], corr_threshold=0.9)
    assert res.not_eligible == [] and res.dropped == {"S2": "S1"}
    returns, _ = ur._training_returns(frame, np.ones(len(idx), dtype=bool), lookback=0)
    assert np.isfinite(returns.to_numpy()).all()  # a log ratio across zero would be NaN/inf
    np.testing.assert_allclose(returns["S1"], np.diff(frame["S1"]))
    np.testing.assert_allclose(returns["Z"], np.diff(np.log(frame["Z"])))


# --- training mask: non-contiguous train (CPCV) ------------------------------

def test_reduce_on_mask_reads_only_training_bars():
    """Identical only on a middle TEST block: never merged; garbage there
    changes nothing."""
    n = 900
    test_block = (np.arange(n) >= 300) & (np.arange(n) < 600)
    frame = _pair(n, test_block)
    train = ~test_block
    res = ur.reduce_on_mask(frame, train, corr_threshold=0.9, lookback=500)
    assert res.dropped == {}
    poisoned = frame.copy()
    poisoned.iloc[300:600] = np.nan
    assert ur.reduce_on_mask(poisoned, train, 0.9, lookback=500).to_dict() == res.to_dict()
    # Sanity: with the block as training data, they do merge.
    assert ur.reduce_on_mask(frame, test_block, 0.9, lookback=500).dropped == {"Y": "X"}


def test_returns_never_straddle_a_test_block():
    """X and Y independent on training bars but both jump by the same huge
    amount inside the test block: a return from the last bar before the
    block to the first after it would be one giant common outlier."""
    n = 700
    frame = _pair(n, np.zeros(n, dtype=bool), seed=5)
    frame.iloc[400:450] *= 50.0  # same x50 level shift on both, inside the test block
    frame.iloc[450:] *= 50.0
    train = np.ones(n, dtype=bool)
    train[400:450] = False
    with pytest.warns(ur.AggressiveReductionWarning):  # threshold 0.5: flagged, still applied
        assert ur.reduce_on_mask(frame, train, corr_threshold=0.5, lookback=0).dropped == {}


# --- which features a dropped series takes with it ---------------------------

RAW_COLS = ["IDX_T", "A1", "A2", "B1", "US", "US_X"]


def test_feature_owner_is_the_longest_raw_column_prefix():
    assert ur.feature_owner("US_X_ret_5", RAW_COLS) == "US_X"
    assert ur.feature_owner("US_ret_5", RAW_COLS) == "US"
    assert ur.feature_owner("A2", RAW_COLS) == "A2"
    assert ur.feature_owner("EURUSD_carry_us_rate_level_22d_estimated", RAW_COLS) is None


def test_mask_features_drops_owned_features_and_their_interactions():
    pool = ["A1", "A2", "A2_ret_5", "A1_ret_5", "A1_ret_5__prod__A2_ret_5", "B1_z__minus__A1_ret_5",
            "EURUSD_carry_us_rate_level_22d_estimated", "US_X_ret_5"]
    kept = ur.mask_features(pool, {"A2"}, RAW_COLS)
    assert kept == ["A1", "A1_ret_5", "B1_z__minus__A1_ret_5",
                    "EURUSD_carry_us_rate_level_22d_estimated", "US_X_ret_5"]
    assert ur.mask_features(pool, {"US"}, RAW_COLS) == pool  # US_X is not US
    assert ur.mask_features(pool, set(), RAW_COLS) == pool


def test_required_series_follow_group_features_and_refuse_unknown_ones():
    cols = ["IDX_T", "GC=F", "SI=F", "HG=F", "CL=F", "US3M_Rate", "EUR_DFR_Rate", "NFCI"]
    assert ur.required_series(["NFCI_ret_5d", "GC=F_ret_5"], cols, "IDX_T") == ["IDX_T", "GC=F", "NFCI"]
    xsect = ur.required_series(["SI=F_xsect_mom_22d_estimated"], cols, "IDX_T")
    assert xsect == ["IDX_T", "GC=F", "SI=F", "HG=F", "CL=F"]
    carry = ur.required_series(["EURUSD_carry_diff_level_22d_estimated"], cols, "IDX_T")
    assert carry == ["IDX_T", "US3M_Rate", "EUR_DFR_Rate"]
    assert ur.required_series(["NFCI_ret_5d__prod__GC=F_ret_5"], cols, "IDX_T") == ["IDX_T", "GC=F", "NFCI"]
    assert ur.required_series(["mystery_feature"], cols, "IDX_T") is None


def test_every_default_pool_feature_has_known_dependencies(monkeypatch):
    """Otherwise predict/explain silently fall back to the whole universe."""
    from patrick.data.sources.yfinance_source import clean_symbol

    monkeypatch.setattr(engine_module, "download_ohlc", lambda *a, **k: None)
    cols = [clean_symbol(t) for t in D.DEFAULT_UNIVERSE_YF_TICKERS] + list(D.DEFAULT_UNIVERSE_FRED_SERIES)
    rng = np.random.default_rng(0)
    raw = pd.DataFrame({c: 50 + np.cumsum(rng.normal(0, 0.5, 300)) for c in cols},
                       index=pd.bdate_range("2020-01-01", periods=300))
    config = RunConfig.model_validate({
        "name": "x", "objective": {"target_symbol": "^VIX"},
        "universe": {"yf_tickers": D.DEFAULT_UNIVERSE_YF_TICKERS, "fred_series": D.DEFAULT_UNIVERSE_FRED_SERIES}})
    base = engine_module.build_base_feature_pool(raw, config, "IDX_VIX")
    assert [c for c in base.columns if ur.feature_dependencies(c, cols) is None] == []


def _guida_raw(n=500, seed=4) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2012-01-01", periods=n)
    cols = {"IDX_T": 20 + np.cumsum(rng.normal(0, 0.3, n)).clip(min=-15)}
    for c in ("GC=F", "SI=F", "HG=F", "CL=F"):
        cols[c] = 100 * np.cumprod(1 + rng.normal(0, 0.01, n))
    cols["US3M_Rate"] = 2 + np.cumsum(rng.normal(0, 0.01, n))
    cols["EUR_DFR_Rate"] = 1 + np.cumsum(rng.normal(0, 0.01, n))
    cols["NFCI"] = np.cumsum(rng.normal(0, 0.02, n))
    return pd.DataFrame(cols, index=idx)


def _guida_config() -> RunConfig:
    return RunConfig.model_validate({
        "name": "restrict", "objective": {"target_symbol": "^T", "horizons": [5]},
        "universe": {"yf_tickers": ["GC=F", "SI=F", "HG=F", "CL=F"],
                     "fred_series": {"US3M_Rate": "DTB3", "EUR_DFR_Rate": "ECBDFR", "NFCI": "NFCI"}},
        "features": {"families": ["technical", "vol_models", "macro"], "vol_models": ["kalman"],
                     "enable_guida_features": True},
    })


def test_pool_rebuilt_from_required_series_equals_the_full_pool(monkeypatch):
    """The predict/explain restriction is exact: every feature, rebuilt from
    only the series it requires, equals its value in the whole-universe
    pool (group-relative Guida features and interactions included)."""
    monkeypatch.setattr(engine_module, "download_ohlc", lambda *a, **k: None)
    raw, config = _guida_raw(), _guida_config()
    base = engine_module.build_full_feature_pool(raw, config, "IDX_T")
    formulas = ["GC=F_ret_5d__prod__NFCI_level", "SI=F_xsect_mom_22d_estimated__minus__CL=F_ret_5d"]
    assert all(f.split("__")[0] in base.columns and f.split("__")[-1] in base.columns for f in formulas)
    full = engine_module.build_full_feature_pool(raw, config, "IDX_T", formulas)
    assert any(c.endswith("_xsect_mom_22d_estimated") for c in full.columns)
    assert any(c.startswith("EURUSD_carry_diff_") for c in full.columns)

    by_requirement: dict[tuple, list[str]] = {}
    for f in full.columns:
        needed = ur.required_series([f], list(raw.columns), "IDX_T")
        assert needed is not None, f
        by_requirement.setdefault(tuple(needed), []).append(f)
    assert len(by_requirement) > 5
    for needed, feats in by_requirement.items():
        sub = ur.restrict_to_required_series(raw, feats, "IDX_T")
        assert list(sub.columns) == list(needed)
        rebuilt = engine_module.build_full_feature_pool(sub, config, "IDX_T", formulas)
        for f in feats:
            np.testing.assert_array_equal(rebuilt[f].to_numpy(), full[f].to_numpy(), err_msg=f)


def test_scale_selected_equals_full_transform_then_selection():
    rng = np.random.default_rng(0)
    X = rng.standard_t(3, size=(300, 12)) * rng.uniform(0.01, 100, 12)
    sc = RobustScaler().fit(X)
    cols = [7, 2, 11, 0]
    rows = rng.normal(0, 5, size=(4, 12))
    assert np.array_equal(sc.transform(rows)[:, cols], scale_selected(sc, rows[:, cols], cols))


@pytest.fixture
def _exported(tmp_path, monkeypatch):
    """A model exported from a whole-universe pool, registered as the best
    trial of run "r" (^T, h=5)."""
    monkeypatch.setattr(engine_module, "download_ohlc", lambda *a, **k: None)
    raw = _guida_raw()
    raw.attrs["snapshot_id"] = "s"
    config = RunConfig.model_validate({
        "name": "p", "objective": {"target_symbol": "^T", "horizons": [5]},
        "universe": {"yf_tickers": ["GC=F", "SI=F", "HG=F", "CL=F"], "fred_series": {"NFCI": "NFCI"}},
        "features": {"families": ["technical", "macro"]},
        "selection": {"method": "shap", "shap_sample": 100},
        "output": {"dir": str(tmp_path / "out")},
    })
    pool = engine_module.build_full_feature_pool(raw, config, "IDX_T")
    feature_pool = [c for c in pool.columns if c != "IDX_T"]
    best_cfg = {"horizon": 5, "regime": "GLOBAL", "N": 4, "sampler": "none", "algo": "XGBoost"}
    path = export_best_model(pool, "IDX_T", feature_pool, config, best_cfg, str(tmp_path))
    bundle = joblib.load(path)

    db_path = str(tmp_path / "p.db")
    conn = trackdb.connect(db_path)
    trackdb.upsert_snapshot(conn, "s", "h", 1, 1, "api")
    trackdb.create_run(conn, "r", target="^T", horizon=5, snapshot_id="s",
                       config_json=config.model_dump_json(), config_hash="x", git_sha="x", seed=42)
    tid = trackdb.create_trial(conn, "r", "GLOBAL", "XGBoost", "none", 4, selector="shap")
    trackdb.mark_best_trial(conn, tid, artifact_path=path)
    trackdb.finish_run(conn, "r", status="done", n_trials=1)
    conn.close()

    last = pool[feature_pool].iloc[[-1]].to_numpy()
    X_full = bundle["scaler"].transform(np.where(np.isfinite(last), last, 0.0))
    X_sel = X_full[:, [feature_pool.index(f) for f in bundle["feature_names"]]]
    needed = ur.required_series(bundle["feature_names"], list(raw.columns), "IDX_T")
    assert len(needed) < raw.shape[1]
    return {"raw": raw, "bundle": bundle, "db_path": db_path, "trial_id": tid, "X_sel": X_sel,
            "needed": needed, "ts": pool.index[-1]}


def _spy_pool_builds(monkeypatch, module) -> list[list[str]]:
    seen: list[list[str]] = []
    real_build = module.build_full_feature_pool

    def spy(r, *a, **k):
        seen.append(list(r.columns))
        return real_build(r, *a, **k)

    monkeypatch.setattr(module, "build_full_feature_pool", spy)
    return seen


def test_predict_live_rebuilds_only_the_models_series_and_matches_the_full_path(_exported, monkeypatch):
    from patrick import predict as predict_module

    ex = _exported
    monkeypatch.setattr(predict_module, "ingest", lambda *a, **k: ex["raw"])
    seen = _spy_pool_builds(monkeypatch, predict_module)
    out = predict_module.predict_live("r", db_path=ex["db_path"])

    assert seen == [ex["needed"]]
    model = ex["bundle"]["model"]
    assert out["y_pred"] == int(model.predict(ex["X_sel"])[0])
    assert out["y_proba"] == float(model.predict_proba(ex["X_sel"])[0].max())


def test_explain_rebuilds_only_the_models_series_and_matches_the_full_path(_exported, monkeypatch):
    import shap

    from patrick import explain as explain_module

    ex = _exported
    y_pred = int(ex["bundle"]["model"].predict(ex["X_sel"])[0])
    monkeypatch.setattr(explain_module.trackdb, "latest_prediction_for_trial",
                        lambda c, tid: {"ts": str(ex["ts"]), "y_pred": y_pred, "split": "live", "y_proba": 0.5})
    monkeypatch.setattr(explain_module, "_load_snapshot_for_prediction", lambda *a, **k: ex["raw"])
    seen = _spy_pool_builds(monkeypatch, explain_module)
    out = explain_module.explain_last_prediction("^T", 5, db_path=ex["db_path"])

    assert seen == [ex["needed"]]
    sv = np.asarray(shap.TreeExplainer(ex["bundle"]["model"]).shap_values(ex["X_sel"]))
    expected = dict(zip(ex["bundle"]["feature_names"], sv[0, :, y_pred]))
    assert {c["name"]: c["shap"] for c in out["contributions"]} == pytest.approx(expected, abs=1e-12)


# --- per-fold decisions in the engine ----------------------------------------

def _engine_raw(n: int, identical: np.ndarray) -> pd.DataFrame:
    frame = _pair(n, identical, seed=11)
    rng = np.random.default_rng(12)
    frame.insert(0, "IDX_T", 20 + np.cumsum(rng.normal(0, 0.3, n)).clip(min=-15))
    frame["C"] = 100 * np.cumprod(1 + rng.normal(0, 0.01, n))
    return frame


def _reduction_config(threshold=0.9) -> RunConfig:
    return RunConfig.model_validate({"name": "u", "objective": {"target_symbol": "^T"},
                                     "universe": {"reduction_corr_threshold": threshold}})


def test_walkforward_folds_each_decide_on_their_own_training_bars():
    n = 1000
    raw = _engine_raw(n, np.arange(n) >= 450)  # X, Y identical from bar 450 on
    pool = ["X", "X_ret_5", "Y", "Y_ret_5", "C", "Y_ret_5__prod__C"]
    universe = engine_module._FoldUniverse(raw, "IDX_T", _reduction_config())
    ctx = engine_module._FoldContext(None, "IDX_T", pool, _reduction_config(), raw.index, [400, 750, 1000],
                                     universe=universe)
    assert ctx.fold_features(0) == pool                        # trained before 400: independent
    assert ctx.fold_features(1) == ["X", "X_ret_5", "C"]       # trained before 750: Y ~ X
    disabled = engine_module._FoldUniverse(raw, "IDX_T", _reduction_config(None))
    assert disabled.features(pool, np.ones(n, dtype=bool), "x") is pool


def test_cpcv_combination_decides_without_its_test_groups():
    n = 1000
    groups = cpcv_module.build_groups(n, 5)
    identical = np.zeros(n, dtype=bool)
    identical[groups[3][0]:] = True  # identical on groups 3 and 4 only
    raw = _engine_raw(n, identical)
    universe = engine_module._FoldUniverse(raw, "IDX_T", _reduction_config())
    pool = ["X", "Y", "C"]
    test_late = cpcv_module.build_split(groups, (3, 4), 5, embargo_bars=5)
    test_early = cpcv_module.build_split(groups, (0, 1), 5, embargo_bars=5)
    assert universe.features(pool, test_late.train_mask, "late") == pool
    assert universe.features(pool, test_early.train_mask, "early") == ["X", "C"]
    poisoned = raw.copy()
    poisoned.iloc[groups[3][0]:, 1:] = np.nan  # test groups of the "late" combination
    other = engine_module._FoldUniverse(poisoned, "IDX_T", _reduction_config())
    assert other.decision(test_late.train_mask).to_dict() == universe.decision(test_late.train_mask).to_dict()


# --- config / form / API exposure (ported) -----------------------------------

def test_threshold_is_a_config_field_off_by_default():
    cfg = RunConfig.model_validate({"name": "x", "objective": {"target_symbol": "^VIX"}})
    assert cfg.universe.reduction_corr_threshold is None
    cfg = RunConfig.model_validate({"name": "x", "objective": {"target_symbol": "^VIX"},
                                    "universe": {"reduction_corr_threshold": 0.85}})
    assert cfg.universe.reduction_corr_threshold == 0.85
    with pytest.raises(ValueError):
        RunConfig.model_validate({"name": "x", "objective": {"target_symbol": "^VIX"},
                                  "universe": {"reduction_corr_threshold": 1.5}})


def _form(**overrides) -> FormData:
    base = {"horizons": ["1"], "regimes": "GLOBAL", "families": ["technical"], "n_features_grid": "5",
            "sampler_candidates": ["SMOTE"], "algos": ["RandomForest"]}
    base.update(overrides)
    items = []
    for k, v in base.items():
        items.extend((k, x) for x in v) if isinstance(v, list) else items.append((k, v))
    return FormData(items)


@pytest.fixture
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))


def test_form_exposes_threshold_and_extended_scope(_isolated):
    cfg, errors = forms.build_config_dict(
        _form(reduction_corr_threshold="0,85", universe_scope="extended"), target_symbol="^VIX", name="VIX_1")
    assert not errors
    assert cfg["universe"]["reduction_corr_threshold"] == 0.85
    assert "XLK" in cfg["universe"]["yf_tickers"] and "^VIX" not in cfg["universe"]["yf_tickers"]
    assert len(cfg["universe"]["yf_tickers"]) > len(D.DEFAULT_UNIVERSE_YF_TICKERS)
    RunConfig.model_validate(cfg)
    view = forms.to_view(cfg)
    assert view["reduction_corr_threshold"] == 0.85 and view["universe_scope"] == "extended"


def test_form_defaults_are_unchanged_universe_and_no_reduction(_isolated):
    cfg, errors = forms.build_config_dict(_form(), target_symbol="^VIX", name="VIX_1")
    assert not errors
    assert cfg["universe"]["reduction_corr_threshold"] is None
    assert cfg["universe"]["yf_tickers"] == [t for t in D.DEFAULT_UNIVERSE_YF_TICKERS if t != "^VIX"]
    assert forms.to_view(cfg)["universe_scope"] == "default"


def test_form_rejects_out_of_range_threshold_and_unknown_scope(_isolated):
    _, errors = forms.build_config_dict(_form(reduction_corr_threshold="1.7"), target_symbol="^VIX", name="VIX_1")
    assert any("réduction" in e for e in errors)
    _, errors = forms.build_config_dict(_form(universe_scope="galaxy"), target_symbol="^VIX", name="VIX_1")
    assert any("Univers candidat" in e for e in errors)


def test_launch_page_renders_the_new_fields(_isolated):
    from patrick.webapp.app import app
    html = TestClient(app).get("/launch").text
    assert 'name="reduction_corr_threshold"' in html
    assert 'name="universe_scope"' in html


# --- run_pipeline: which training bars each decision reads (~6 s each) ------

def _pipeline_config(tmp_path, scheme: str) -> RunConfig:
    return RunConfig.model_validate({
        "name": f"reduction_{scheme}",
        "objective": {"target_symbol": "^T", "horizons": [3], "regimes": ["GLOBAL"]},
        "universe": {"yf_tickers": ["X", "Y", "C"], "reduction_corr_threshold": 0.9},
        "features": {"families": ["technical"]},
        "validation": {"scheme": scheme, "n_wf_folds": 2, "min_train_frac": 0.5, "holdout_months": 12,
                       "n_groups": 4, "k_test_groups": 1},
        "selection": {"method": "shap", "n_features_grid": [4], "shap_sample": 80},
        "sampler": {"candidates": ["none"]},
        "models": {"algos": ["LightGBM"]},
        "tuning": {"enabled": False},
        "output": {"dir": str(tmp_path / "out"), "seed": 42},
    })


def _run_with_spy(tmp_path, monkeypatch, scheme: str, raw: pd.DataFrame):
    from patrick.data.store import DataStore

    masks: list[np.ndarray] = []
    decisions: dict[tuple, dict] = {}
    real = ur.reduce_on_mask

    def spy(prices, train_mask, *a, **k):
        masks.append(np.asarray(train_mask, dtype=bool).copy())
        out = real(prices, train_mask, *a, **k)
        decisions[tuple(masks[-1])] = out.dropped
        return out

    monkeypatch.setattr(ur, "reduce_on_mask", spy)
    monkeypatch.setattr(engine_module, "ingest", lambda *a, **k: raw)
    monkeypatch.setattr(engine_module, "download_ohlc", lambda *a, **k: None)
    config = _pipeline_config(tmp_path, scheme)
    result = engine_module.run_pipeline(config, store=DataStore(root=str(tmp_path / "store")),
                                        db_path=str(tmp_path / "p.db"))
    return config, result, masks, decisions


def _prefix(n: int, end: int) -> tuple:
    return tuple(np.arange(n) < end)


def test_walkforward_run_decides_per_fold_holdout_and_final_model(tmp_path, monkeypatch):
    n = 1500
    raw = _engine_raw(n, np.arange(n) >= 900)  # X, Y identical from bar 900 on
    config, result, masks, decisions = _run_with_spy(tmp_path, monkeypatch, "walkforward", raw)

    v = config.validation
    n_wf = engine_module._walk_forward_span(raw.index, v.holdout_months, v.min_train_frac)
    cuts = engine_module.build_fold_cuts(raw.index[:n_wf], v.n_wf_folds, v.min_train_frac)
    expected = {_prefix(n, c) for c in cuts[:-1]} | {_prefix(n, n_wf), _prefix(n, n)}
    assert {tuple(m) for m in masks} == expected  # one decision per training set, nothing else
    assert len(masks) == len(expected)            # memoized: never decided twice
    assert decisions[_prefix(n, cuts[0])] == {}   # fold 1 trains before bar ~620: X, Y independent
    assert decisions[_prefix(n, n_wf)] == {"Y": "X"}

    bundle = joblib.load(result["model_path"])
    assert bundle["universe_reduction"]["dropped"] == {"Y": "X"}
    assert not [f for f in bundle["feature_pool"] if f == "Y" or f.startswith("Y_")]
    board = result["leaderboard"]
    later = board[(board["fold"] > 1) & board["N"].notna()]
    assert not any(f == "Y" or f.startswith("Y_") for row in later["features"] for f in row.split("|"))


def test_cpcv_run_decides_on_each_combinations_train_mask(tmp_path, monkeypatch):
    n = 1200
    raw = _engine_raw(n, np.arange(n) >= 900)
    config, result, masks, _decisions = _run_with_spy(tmp_path, monkeypatch, "cpcv", raw)

    v = config.validation
    groups = cpcv_module.build_groups(n, v.n_groups)
    expected = {tuple(cpcv_module.build_split(groups, combo, h, embargo_bars=v.embargo_bars).train_mask)
                for combo in cpcv_module.all_combinations(v.n_groups, v.k_test_groups)
                for h in config.objective.horizons}
    expected.add(_prefix(n, n))
    assert {tuple(m) for m in masks} == expected
    assert joblib.load(result["model_path"])["universe_reduction"]["dropped"] == {"Y": "X"}
