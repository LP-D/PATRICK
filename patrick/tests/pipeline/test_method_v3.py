"""Méthode 3 (ADR 0011) : niveaux bruts différenciés fractionnairement, cible de volatilité, calibration par défaut du formulaire."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from statsmodels.tsa.stattools import adfuller

from patrick.config.schema import FeaturesConfig, ObjectiveConfig, RunConfig
from patrick.features import fracdiff
from patrick.features import macro as feat_macro
from patrick.pipeline import engine


def _random_walk(n: int = 1500, seed: int = 3) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, n))), index=pd.bdate_range("2015-01-01", periods=n), name="X")


def test_the_fractional_level_is_stationary_where_the_level_is_not():
    s = _random_walk()
    fd = fracdiff.fracdiff_level(s).dropna()
    assert adfuller(np.log(s).to_numpy(), maxlag=1, autolag=None)[1] > 0.05          # un cours : racine unitaire
    assert adfuller(fd.to_numpy(), maxlag=1, autolag=None)[1] < 0.05                 # son niveau fractionnaire : stationnaire
    assert np.corrcoef(np.log(s).loc[fd.index], fd)[0, 1] > 0.5                      # et il garde de la mémoire du niveau


def test_the_fractional_level_is_causal_and_keeps_the_index():
    s = _random_walk()
    fd = fracdiff.fracdiff_level(s)
    assert fd.index.equals(s.index) and fd.iloc[:50].isna().all() and fd.iloc[-1] == fd.iloc[-1]
    changed = s.copy()
    changed.iloc[-1] *= 3.0                                                          # un changement du dernier jour ...
    assert fracdiff.fracdiff_level(changed).iloc[:-1].equals(fd.iloc[:-1])           # ... ne touche aucune valeur passée


def test_a_series_that_can_be_negative_is_not_logged():
    s = _random_walk() - 100.0
    fd = fracdiff.fracdiff_level(s).dropna()
    assert np.isfinite(fd).all() and len(fd) > 1000


def test_macro_levels_and_lags_follow_the_flag():
    s = _random_walk()
    df = pd.DataFrame({"DGS10": s})
    legacy = feat_macro.build_macro_features(df, ["DGS10"])
    v3 = feat_macro.build_macro_features(df, ["DGS10"], fracdiff=True)
    assert list(legacy.columns) == list(v3.columns)                                  # mêmes noms
    assert legacy["DGS10_level"].equals(s)
    fd = fracdiff.fracdiff_level(s)
    assert v3["DGS10_level"].equals(fd) and v3["DGS10_lag5"].equals(fd.shift(5))
    assert legacy["DGS10_ret_5d"].equals(v3["DGS10_ret_5d"])                         # les rendements ne changent pas


def _config(method: int, **objective) -> RunConfig:
    return RunConfig(objective=ObjectiveConfig(target_symbol="^GSPC", **objective), features=FeaturesConfig(families=["technical"]),
                     validation={"method_version": method})


def test_method_three_replaces_raw_levels_but_not_the_target_price(monkeypatch):
    monkeypatch.setattr(engine, "download_ohlc", lambda *a, **k: None)
    s = _random_walk()
    raw = pd.DataFrame({"GSPC": s, "GC_F": s * 2.0})
    pool2 = engine.build_base_feature_pool(raw, _config(2), "GSPC")
    pool3 = engine.build_base_feature_pool(raw, _config(3), "GSPC")
    assert set(pool2.columns) == set(pool3.columns)                                  # les noms ne changent pas
    assert pool3["GSPC"].equals(s)                                                   # le prix de la cible reste le prix (les étiquettes en dépendent)
    assert pool2["GC_F"].equals(raw["GC_F"]) and pool3["GC_F"].equals(fracdiff.fracdiff_level(raw["GC_F"]))
    assert pool2["GC_F_ret_5d"].equals(pool3["GC_F_ret_5d"]) if "GC_F_ret_5d" in pool2 else True


def test_the_pool_cache_key_moves_only_for_method_three():
    base = engine._features_payload(_config(1))
    assert engine._features_payload(_config(2)) == base                              # un run ancien retrouve sa réserve en cache
    assert engine._features_payload(_config(3)) != base and engine._features_payload(_config(3))["raw_level"] == "fracdiff"


@pytest.mark.parametrize("method", [1, 2])
def test_legacy_methods_keep_raw_levels(method, monkeypatch):
    monkeypatch.setattr(engine, "download_ohlc", lambda *a, **k: None)
    raw = pd.DataFrame({"GSPC": _random_walk(), "OTHER": _random_walk(seed=9)})
    pool = engine.build_base_feature_pool(raw, _config(method), "GSPC")
    assert pool["OTHER"].equals(raw["OTHER"])


def test_the_launch_form_starts_calibrated_while_the_schema_default_does_not_move():
    from patrick.config import defaults as D
    from patrick.webapp import forms

    assert forms.default_config_dict("ml")["models"]["calibration"] is True
    assert forms.default_config_dict("dl")["models"]["calibration"] is True
    assert _config(2).models.calibration is D.DEFAULT_CALIBRATION_ENABLED is False       # golden master et configs enregistrées intacts
