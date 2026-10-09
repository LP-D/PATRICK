"""Quatorze entraînements de la campagne FRED du 2026-10-07/08 (^VIX, DX-Y.NYB, CL=F, BZ=F, BTC-USD, SOFR, T10Y3M,
T10YIE, T5YIE, T5YIFR, UMCSENT, VIXCLS, TTE.PA, HO.PA) sont morts sur la même erreur XGBoost : « Input data contains
`inf` or a value too large ». Les gardes N2 (`tests/test_inf_features.py`) ne regardaient que le débordement du float64
(1.8e308) ; XGBoost convertit en float32 (3.4e38) : une valeur finie en float64 mais supérieure à 3.4e38 (rapport
d'une formule à dénominateur ~1e-300, ajustement paramétrique divergent sur un fold court) devient `inf` à l'entrée du
modèle. Ces tests verrouillent la plage float32 à tous les étages.
"""
from __future__ import annotations

import numpy as np
import pytest
from sklearn.preprocessing import RobustScaler
from xgboost import XGBClassifier

from patrick.features.sanitize import FLOAT32_SAFE_MAX, finite_features, finite_scaled


def _matrix_with_astronomical_cell():
    rng = np.random.default_rng(0)
    X = rng.normal(0, 0.01, size=(80, 4))
    X[7, 1] = 1e100                      # finie en float64, hors plage float32
    y = rng.integers(0, 2, size=80)
    return X, y


def test_float32_overflow_reproduces_the_production_error_without_the_guard():
    X, y = _matrix_with_astronomical_cell()
    assert np.isfinite(X).all()
    with pytest.raises(Exception, match="inf"):
        XGBClassifier(n_estimators=5, verbosity=0).fit(X, y)


def test_finite_features_treats_an_out_of_range_value_as_missing(capsys):
    X, _ = _matrix_with_astronomical_cell()
    out = finite_features(X, "fold 1 train")
    assert np.abs(out).max() <= FLOAT32_SAFE_MAX
    assert out[7, 1] == 0.0                       # même chemin que NaN / inf
    assert "out of float32 range" in capsys.readouterr().out
    assert out[0, 0] == X[0, 0]                   # valeurs saines intactes


def test_finite_scaled_clips_what_the_scaler_blows_up():
    # IQR ~1e-15 (bruit d'arrondi d'une série en escalier) : une valeur ordinaire devient 1e45 après mise à l'échelle.
    col = np.concatenate([np.full(40, 1.0) + np.arange(40) * 1e-15, [0.5]])[:, None]
    scaled = RobustScaler().fit_transform(finite_features(col, "test"))
    scaled = np.vstack([scaled, [[1e45]]])
    assert np.isfinite(scaled).all() and np.abs(scaled).max() > 3.4e38
    fixed = finite_scaled(scaled, "test")
    assert np.abs(fixed).max() <= FLOAT32_SAFE_MAX


def test_xgboost_accepts_the_matrix_after_both_guards():
    X, y = _matrix_with_astronomical_cell()
    clean = finite_scaled(RobustScaler().fit_transform(finite_features(X, "test")), "test")
    XGBClassifier(n_estimators=5, verbosity=0).fit(clean, y)   # ne doit pas lever
