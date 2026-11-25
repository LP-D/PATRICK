"""GJR-GARCH, APARCH et HAR comme variables (A3) : causalité par pli, valeurs plausibles, défauts et empreintes inchangés."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.config import defaults as D
from patrick.features import vol_models as vm
from patrick.features import vol_models_extra as vx
from patrick.webapp import forms


def _prices(n=900, seed=3):
    rng = np.random.default_rng(seed)
    sigma = np.empty(n)
    r = np.empty(n)
    s2 = 1e-4
    for t in range(n):                       # GARCH(1,1) à effet de levier : une vraie dynamique de volatilité
        s2 = 2e-6 + 0.08 * (r[t - 1] ** 2 if t else 1e-4) * (1.6 if t and r[t - 1] < 0 else 0.4) + 0.88 * s2
        sigma[t] = np.sqrt(s2)
        r[t] = sigma[t] * rng.standard_normal()
    return pd.Series(100 * np.exp(np.cumsum(r)), index=pd.bdate_range("2020-01-01", periods=n), name="px")


@pytest.mark.parametrize("model", ["gjr", "aparch", "har"])
def test_corrupting_the_future_leaves_the_train_part_unchanged(model):
    px = _prices()
    cut = 600
    corrupted = px.copy()
    corrupted.iloc[cut + 5:] *= np.linspace(1, 40, len(px) - cut - 5)          # un futur absurde
    clean = vm.build_vol_model_features_parametric(px, models=[model], fit_end_idx=cut, test_end_idx=cut + 100)
    dirty = vm.build_vol_model_features_parametric(corrupted, models=[model], fit_end_idx=cut, test_end_idx=cut + 100)
    col = f"px_{vm._MODEL_OUTPUT_COLUMN[model]}"
    a, b = clean[col].iloc[:cut], dirty[col].iloc[:cut]
    assert a.notna().sum() > 400
    pd.testing.assert_series_equal(a, b)


@pytest.mark.parametrize("model", ["gjr", "aparch", "har"])
def test_outputs_are_positive_daily_volatilities(model):
    px = _prices()
    out = vm.build_vol_model_features_parametric(px, models=[model], fit_end_idx=700)[f"px_{vm._MODEL_OUTPUT_COLUMN[model]}"].dropna()
    realised = px.pct_change().std()
    assert (out > 0).all() and 0.3 * realised < out.median() < 3 * realised


def test_har_tracks_volatility_better_than_a_constant():
    px = _prices(1500)
    har = vx.har_vol(px, fit_end_idx=1000)
    nxt = (px.pct_change() ** 2).shift(-1)
    test = slice(1000, 1490)
    mse_har = float(((har.iloc[test] ** 2 - nxt.iloc[test]) ** 2).mean())
    mse_const = float(((nxt.iloc[:1000].mean() - nxt.iloc[test]) ** 2).mean())
    assert mse_har < mse_const


def test_new_models_are_offered_but_not_default():
    assert {"gjr", "aparch", "har"} <= set(D.ALL_VOL_MODELS) <= set(forms.VOL_MODEL_LABELS)
    assert not {"gjr", "aparch", "har"} & set(D.DEFAULT_VOL_MODELS)
    assert {"gjr", "aparch", "har"} <= vm.PARAMETRIC_VOL_MODELS


def test_the_feature_code_hash_and_existing_cache_keys_do_not_move():
    """`vol_models.py` reste intact (empreinte du cache) ; une configuration sans les nouveaux modèles garde exactement sa clé."""
    from patrick.config.schema import RunConfig
    from patrick.features import pool_cache
    from patrick.pipeline import engine

    assert "vol_models_extra.py" not in pool_cache._FEATURE_SOURCES
    base = RunConfig.model_validate({"objective": {"target_symbol": "^VIX"}})
    payload = engine._features_payload(base)
    assert "vol_extra_code" not in payload and "enable_text_features" not in payload["features"]
    with_gjr = RunConfig.model_validate({"objective": {"target_symbol": "^VIX"}, "features": {"vol_models": ["egarch", "gjr"]}})
    assert engine._features_payload(with_gjr)["vol_extra_code"] == vx.CODE_HASH
