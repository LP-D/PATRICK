"""Phase X5 (session de consolidation, bloc X) -- classification par classe
d'actif étendue (indices de volatilité, macro) et nouvelles baselines
(momentum, marche aléatoire, majoritaire par régime)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from patrick.data.session_calendar import classify_asset_class
from patrick.validation.baselines import (
    majority_by_regime_predictions,
    momentum_predictions,
    random_walk_predictions,
)


def test_classify_asset_class_volatility_index():
    assert classify_asset_class("^VIX") == "volatility_index"
    assert classify_asset_class("^VIX3M") == "volatility_index"
    assert classify_asset_class("^VVIX") == "volatility_index"
    # ^GSPC (indice actions, pas de volatilité) inchangé.
    assert classify_asset_class("^GSPC") == "equities_us"


def test_classify_asset_class_fred_is_macro():
    assert classify_asset_class("NFCI", source="fred") == "macro"
    assert classify_asset_class("ANYTHING", source="fred") == "macro"


def test_random_walk_no_drift_predicts_constant_class():
    idx = pd.bdate_range("2020-01-01", periods=40)
    price = pd.Series(100 + np.cumsum(np.random.default_rng(0).normal(0, 1, 40)), index=idx)
    tr_mask = np.array([True] * 20 + [False] * 20)
    te_mask = ~tr_mask
    thr = {"GLOBAL": (-0.01, 0.01)}
    reg_r = pd.Series("GLOBAL", index=idx)
    preds = random_walk_predictions(price, idx, tr_mask, te_mask, drift=False, thr=thr, reg_r=reg_r)
    # r_hat = 0 pour toutes les lignes -> même classe partout (prévision constante).
    assert len(set(preds.tolist())) == 1
    assert preds[0] == 2  # 0 < q75=0.01 -> classe 2, cf. _classify_like_target


def test_random_walk_with_drift_uses_train_mean_return():
    idx = pd.bdate_range("2020-01-01", periods=40)
    # Rendement constant +2% chaque jour sur le train -> dérive positive nette.
    price = pd.Series(100 * (1.02 ** np.arange(40)), index=idx)
    tr_mask = np.array([True] * 20 + [False] * 20)
    te_mask = ~tr_mask
    thr = {"GLOBAL": (-0.001, 0.001)}
    reg_r = pd.Series("GLOBAL", index=idx)
    preds = random_walk_predictions(price, idx, tr_mask, te_mask, drift=True, thr=thr, reg_r=reg_r)
    # dérive positive et forte (>> q75) -> classe 3 partout.
    assert set(preds.tolist()) == {3}


def test_momentum_predictions_detects_uptrend():
    idx = pd.bdate_range("2020-01-01", periods=40)
    price = pd.Series(100 * (1.01 ** np.arange(40)), index=idx)  # tendance haussière régulière
    te_mask = np.array([False] * 20 + [True] * 20)
    thr = {"GLOBAL": (-0.001, 0.001)}
    reg_r = pd.Series("GLOBAL", index=idx)
    preds = momentum_predictions(price, idx, te_mask, window=5, thr=thr, reg_r=reg_r)
    # rendement 5j glissant toujours largement positif -> classe 3 (au-dessus de q75).
    assert set(preds.tolist()) == {3}


def test_majority_by_regime_differs_from_global_when_regimes_diverge():
    y_tr = np.array([0, 0, 0, 3, 3, 3, 3])  # majorité globale = 3
    tr_regimes = np.array(["CALM", "CALM", "CALM", "STRESS", "STRESS", "STRESS", "STRESS"])
    te_regimes = np.array(["CALM", "CALM", "STRESS"])
    preds = majority_by_regime_predictions(y_tr, tr_regimes, te_regimes)
    assert preds.tolist() == [0, 0, 3]  # CALM -> majorité locale 0, STRESS -> majorité locale 3


def test_majority_by_regime_falls_back_to_global_for_unseen_regime():
    y_tr = np.array([0, 0, 3])
    tr_regimes = np.array(["CALM", "CALM", "CALM"])
    te_regimes = np.array(["STRESS"])  # jamais vu au train
    preds = majority_by_regime_predictions(y_tr, tr_regimes, te_regimes)
    assert preds.tolist() == [0]  # repli sur la majorité globale du train (0)
