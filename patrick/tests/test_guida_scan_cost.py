"""Phase 2 (feature/guida-features-full) -- end-to-end pipeline check with
`enable_guida_features` OFF vs ON on the SAME synthetic config (`ingest()`
monkeypatched, no network -- same pattern as `test_pipeline_smoke.py`), plus
the scan-time measurement the task requires before even considering (never
done here) a default-on flip. Real wall-clock numbers, not an estimate.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
import pytest

from patrick.config.schema import RunConfig
from patrick.data.store import DataStore
from patrick.pipeline import engine as engine_module

pytestmark = pytest.mark.slow


def _synthetic_raw_with_commodities_and_macro(n=1500, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    target = 15 + np.cumsum(rng.normal(0, 0.5, n)).clip(min=-10)
    df = pd.DataFrame({"IDX_TEST": target}, index=idx)
    # >=3 commodities: activates cross-sectional momentum + idio vol (commo group)
    df["GC=F"] = 1500 + np.cumsum(rng.normal(0, 8, n))
    df["SI=F"] = 20 + np.cumsum(rng.normal(0, 0.3, n))
    df["HG=F"] = 4 + np.cumsum(rng.normal(0, 0.05, n))
    # >=3 macro series incl. US3M_Rate: activates carry + idio vol (macro group)
    df["US3M_Rate"] = np.clip(2 + np.cumsum(rng.normal(0, 0.02, n)), 0.01, None)
    df["NFCI"] = np.cumsum(rng.normal(0, 0.02, n))
    df["T10Y2Y_Spread"] = np.cumsum(rng.normal(0, 0.01, n))
    return df


def _tiny_config(tmp_path, enable_guida: bool) -> RunConfig:
    raw_yaml = {
        "name": "guida_scan_cost",
        "objective": {"target_symbol": "^TEST", "horizons": [3, 5], "regimes": ["GLOBAL"]},
        "universe": {
            "yf_tickers": ["GC=F", "SI=F", "HG=F"],
            "fred_series": {"US3M_Rate": "DTB3", "NFCI": "NFCI", "T10Y2Y_Spread": "T10Y2Y"},
            "start_date": "2015-01-01",
        },
        "features": {
            "families": ["technical", "interactions", "spike", "vol_models", "macro"],
            "interact_top_base": 15, "interact_top_pairs": 8, "interact_final_n": 6,
            "pool_prefilter": 60,
            "enable_guida_features": enable_guida,
        },
        "validation": {"n_wf_folds": 2, "min_train_frac": 0.5},
        "selection": {"method": "shap", "n_features_grid": [5, 8], "shap_sample": 200},
        "sampler": {"candidates": ["SMOTE"]},
        "models": {"algos": ["RandomForest"]},
        "tuning": {"enabled": False},
        "output": {"dir": str(tmp_path / "runs"), "seed": 42},
    }
    return RunConfig.model_validate(raw_yaml)


def _run_and_time(tmp_path, enable_guida: bool) -> tuple[dict, float]:
    config = _tiny_config(tmp_path, enable_guida)

    def fake_ingest(objective, universe, store=None, force=False, data_quality=None):
        return _synthetic_raw_with_commodities_and_macro()

    import patrick.pipeline.engine as em
    orig_ingest = em.ingest
    em.ingest = fake_ingest
    try:
        t0 = time.time()
        result = engine_module.run_pipeline(
            config, store=DataStore(root=str(config.output.dir) + f"_store_{enable_guida}"),
            db_path=str(tmp_path / f"patrick_test_{enable_guida}.db"))
        elapsed = time.time() - t0
    finally:
        em.ingest = orig_ingest
    return result, elapsed


def test_guida_features_off_vs_on_pipeline_runs_and_scan_cost_is_measured(tmp_path, capsys):
    result_off, t_off = _run_and_time(tmp_path, enable_guida=False)
    result_on, t_on = _run_and_time(tmp_path, enable_guida=True)

    assert len(result_off["leaderboard"]) > 0
    assert len(result_on["leaderboard"]) > 0

    with capsys.disabled():
        print(f"\n[GUIDA SCAN COST] enable_guida_features=False: {t_off:.2f}s")
        print(f"[GUIDA SCAN COST] enable_guida_features=True:  {t_on:.2f}s")
        print(f"[GUIDA SCAN COST] delta: {t_on - t_off:+.2f}s "
              f"({(t_on / t_off - 1) * 100:+.1f}%)")


def test_enabling_guida_features_adds_estimated_and_extended_lookback_columns(tmp_path):
    """Correctness check (not just "doesn't crash"): flipping the flag must
    actually widen the base feature pool with `_estimated` columns (carry/
    cross-sectional momentum/idio vol) and Guida-lookback technical columns,
    on the exact same input."""
    from patrick.config.defaults import GUIDA_LOOKBACKS

    raw = _synthetic_raw_with_commodities_and_macro()
    config_off = _tiny_config(tmp_path, enable_guida=False)
    config_on = _tiny_config(tmp_path, enable_guida=True)

    pool_off = engine_module.build_base_feature_pool(raw, config_off, target_col="IDX_TEST")
    pool_on = engine_module.build_base_feature_pool(raw, config_on, target_col="IDX_TEST")

    assert len(pool_on.columns) > len(pool_off.columns)
    estimated_cols = [c for c in pool_on.columns if c.endswith("_estimated")]
    assert len(estimated_cols) > 0
    assert any(f"ret_{GUIDA_LOOKBACKS[-1]}d" in c for c in pool_on.columns)
    assert not any(c.endswith("_estimated") for c in pool_off.columns)
