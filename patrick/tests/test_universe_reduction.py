"""Correlation-clustering reduction of the candidate universe
(`selection/universe_reduction.py`), point-in-time via the covariance
matrix shared with HRP/BL (`tracking/covariance.py`)."""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import FormData

from patrick.config import defaults as D
from patrick.config.schema import RunConfig
from patrick.selection import universe_reduction as ur
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


def test_correlation_at_T_ignores_data_after_T():
    """Two series independent up to T, then identical after T. The
    reduction at T must NOT merge them; a full-history computation would."""
    rng = np.random.default_rng(1)
    idx = pd.bdate_range("2010-01-01", periods=600)
    t_idx = 299
    r1, r2 = rng.normal(0, 0.01, 600), rng.normal(0, 0.01, 600)
    r2[t_idx + 1:] = r1[t_idx + 1:]  # mocked "future": perfectly correlated after T
    p1 = pd.Series(100 * np.cumprod(1 + r1), index=idx)
    p2 = pd.Series(100 * np.cumprod(1 + r2), index=idx)
    as_of = idx[t_idx]

    res = ur.reduce_universe({"X": p1, "Y": p2}, as_of=as_of, corr_threshold=0.9, lookback=252)
    assert res.dropped == {}
    # Sanity: with a lookback that sees the future, they WOULD merge.
    late = ur.reduce_universe({"X": p1, "Y": p2}, as_of=idx[-1], corr_threshold=0.9, lookback=252)
    assert late.dropped == {"Y": "X"}


def test_future_values_are_never_read(monkeypatch):
    """Poisoned post-T values (NaN/inf/huge) must not change anything at T."""
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
    assert res.kept  # still returns a result


def test_non_aggressive_threshold_does_not_warn():
    prices = _prices()
    with warnings.catch_warnings():
        warnings.simplefilter("error", ur.AggressiveReductionWarning)
        ur.reduce_universe(prices, as_of=prices["A1"].index[-1], corr_threshold=0.95)


def test_series_too_short_at_as_of_are_kept_not_dropped():
    prices = _prices()
    late = prices["A2"].copy()
    late.iloc[:390] = np.nan  # starts after as_of's lookback window
    prices["A2"] = late
    res = ur.reduce_universe(prices, as_of=prices["A1"].index[-1], corr_threshold=0.9)
    assert "A2" in res.kept and "A2" in res.not_eligible


def test_apply_to_raw_never_drops_the_target_and_keeps_attrs():
    prices = _prices()
    raw = pd.DataFrame(prices)
    raw.attrs["snapshot_id"] = "snapX"
    out, res = ur.apply_to_raw(raw, "A1", as_of=raw.index[-1], corr_threshold=0.9)
    assert "A1" in out.columns
    assert out.attrs["snapshot_id"] == "snapX"
    assert set(out.columns) == {"A1", "A2", "A3", "B1", "C"} - set(res.dropped)


def test_reduction_as_of_is_end_of_first_training_window():
    idx = pd.bdate_range("2010-01-01", periods=1000)
    assert ur.reduction_as_of(idx, 0.4, holdout_start_idx=800) == idx[319]
    assert ur.reduction_as_of(idx, 0.5) == idx[499]


# --- config / form / API exposure -------------------------------------------

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
        _form(reduction_corr_threshold="0.85", universe_scope="extended"), target_symbol="^VIX", name="VIX_1")
    assert not errors
    assert cfg["universe"]["reduction_corr_threshold"] == 0.85
    assert "XLK" in cfg["universe"]["yf_tickers"] and "^VIX" not in cfg["universe"]["yf_tickers"]
    assert len(cfg["universe"]["yf_tickers"]) + len(cfg["universe"]["fred_series"]) > 66
    RunConfig.model_validate(cfg)
    view = forms.to_view(cfg)
    assert view["reduction_corr_threshold"] == 0.85 and view["universe_scope"] == "extended"


def test_form_defaults_are_unchanged_universe_and_no_reduction(_isolated):
    cfg, errors = forms.build_config_dict(_form(), target_symbol="^VIX", name="VIX_1")
    assert not errors
    assert cfg["universe"]["reduction_corr_threshold"] is None
    assert cfg["universe"]["yf_tickers"] == [t for t in D.DEFAULT_UNIVERSE_YF_TICKERS if t != "^VIX"]


def test_form_rejects_out_of_range_threshold(_isolated):
    _, errors = forms.build_config_dict(_form(reduction_corr_threshold="1.7"), target_symbol="^VIX", name="VIX_1")
    assert any("réduction" in e for e in errors)


def test_extended_candidates_never_become_targets():
    targets = {s for s, _, _ in D.DEFAULT_TARGET_CHOICES}
    assert len(D.DEFAULT_TARGET_CHOICES) == 66
    assert not (set(D.EXTENDED_CANDIDATE_EXTRA_YF_TICKERS) & targets)
    assert not (set(D.EXTENDED_CANDIDATE_YF_TICKERS) & D.BAD_TICKERS)


def test_launch_page_renders_the_new_fields(_isolated):
    from patrick.webapp.app import app
    html = TestClient(app).get("/launch").text
    assert 'name="reduction_corr_threshold"' in html
    assert 'name="universe_scope"' in html


# --- pipeline wiring ---------------------------------------------------------

def test_run_pipeline_applies_reduction_before_feature_construction(tmp_path, monkeypatch):
    from patrick.data.store import DataStore
    from patrick.pipeline import engine as engine_module

    class _Stop(Exception):
        pass

    prices = _prices(n=900)
    raw = pd.DataFrame(prices).rename(columns={"C": "IDX_TEST"})
    monkeypatch.setattr(engine_module, "ingest", lambda *a, **k: raw)
    seen = {}

    def spy(r, cfg, target_col):
        seen["cols"] = list(r.columns)
        raise _Stop()

    monkeypatch.setattr(engine_module, "build_base_feature_pool", spy)
    cfg = RunConfig.model_validate({
        "name": "red", "objective": {"target_symbol": "^TEST", "horizons": [3]},
        "universe": {"reduction_corr_threshold": 0.9},
        "validation": {"holdout_months": 12},
        "output": {"dir": str(tmp_path / "runs")},
    })
    with pytest.raises(_Stop):
        engine_module.run_pipeline(cfg, store=DataStore(root=str(tmp_path / "s")),
                                   db_path=str(tmp_path / "p.db"))
    assert sorted(seen["cols"]) == ["A1", "B1", "IDX_TEST"]
