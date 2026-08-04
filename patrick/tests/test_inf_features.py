"""Rapport de correction, N2 -- une valeur infinie dans le pool de features ne
doit JAMAIS atteindre un modèle : XGBoost refuse la matrice sans condition
("Input data contains `inf` or a value too large, while `missing` is not set to
`inf`"), ce qui a fait échouer un run réel sur ^VIX après 380s de construction
de features.

Ces tests verrouillent les deux étages du correctif : le nettoyage en entrée
(`_finite_features`), le filet en sortie de mise à l'échelle (`_finite_scaled`),
et la garde intrinsèque au registre d'interactions (`apply_interaction`).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sklearn.preprocessing import RobustScaler
from xgboost import XGBClassifier

from patrick.features.interactions import INTERACTION_TYPES, apply_interaction
from patrick.pipeline.engine import _finite_features, _finite_scaled


def test_nan_to_num_alone_reintroduces_inf_through_the_scaler():
    """Reproduit la CAUSE RACINE, pour que le correctif ne soit pas retiré par
    inadvertance : `np.nan_to_num` seul mappe inf sur 1.797e308 (max float64),
    que le RobustScaler redivise ensuite par un IQR < 1 -- et le inf revient."""
    raw = np.array([[0.01], [0.02], [0.03], [np.inf], [0.05], [0.04]])

    naive = RobustScaler().fit_transform(np.nan_to_num(raw))
    assert not np.isfinite(naive).all(), (
        "si ceci échoue, numpy/sklearn ont changé de comportement — revérifier "
        "que le correctif `_finite_features` reste nécessaire")

    fixed = _finite_scaled(RobustScaler().fit_transform(_finite_features(raw, "test")), "test")
    assert np.isfinite(fixed).all()


def test_finite_features_maps_inf_to_the_missing_value_path():
    """±inf suit exactement le même chemin que NaN (-> 0.0), jamais celui d'un
    "nombre très grand"."""
    raw = np.array([[1.0, np.inf], [np.nan, -np.inf], [2.0, 3.0]])
    out = _finite_features(raw, "test")
    assert np.isfinite(out).all()
    assert out[0, 1] == 0.0 and out[1, 1] == 0.0  # +inf et -inf -> 0.0
    assert out[1, 0] == 0.0                        # NaN -> 0.0 (inchangé)
    assert out[0, 0] == 1.0 and out[2, 1] == 3.0   # valeurs saines intactes


def test_finite_features_reports_and_never_stays_silent(capsys):
    """Anti-défaut silencieux (même discipline que la garde D3) : le nombre de
    cellules infinies est annoncé, jamais absorbé sans un mot."""
    _finite_features(np.array([[np.inf], [1.0], [-np.inf]]), "fold 2 (h=5j)")
    out = capsys.readouterr().out
    assert "2 valeur(s) infinie(s)" in out
    assert "fold 2 (h=5j)" in out

    _finite_features(np.array([[1.0], [2.0]]), "fold 3")
    assert capsys.readouterr().out == "", "aucun bruit quand le pool est sain"


def test_finite_scaled_catches_overflow_from_large_but_finite_values(capsys):
    """`_finite_features` ne suffit pas seul : une valeur simplement TRÈS
    GRANDE mais finie (donc invisible en amont) peut encore déborder en étant
    divisée par un IQR minuscule."""
    # Calibré par mesure : le débordement exige valeur/IQR > 1.8e308 — ici
    # 1e305 / 2e-6. Une valeur "seulement" grande (1e300 / 2e-3) reste finie.
    huge = np.array([[1e305], [1e-6], [2e-6], [3e-6], [4e-6]])
    assert np.isfinite(huge).all(), "l'entrée est bien finie — rien à nettoyer en amont"

    scaled = RobustScaler().fit_transform(_finite_features(huge, "test"))
    assert not np.isfinite(scaled).all(), "le débordement doit bien se produire ici"

    repaired = _finite_scaled(scaled, "holdout (h=5j)")
    assert np.isfinite(repaired).all()
    assert "APRÈS mise à l'échelle" in capsys.readouterr().out


def test_xgboost_accepts_the_sanitized_matrix():
    """Le test qui compte : la matrice nettoyée passe réellement dans XGBoost,
    là où la matrice naïve lève l'erreur vue en production."""
    rng = np.random.default_rng(0)
    X = rng.normal(0, 0.01, size=(80, 4))
    X[5, 2] = np.inf          # dénominateur ~0 dans un ratio
    X[9, 3] = -np.inf
    y = rng.integers(0, 2, size=80)

    naive = RobustScaler().fit_transform(np.nan_to_num(X))
    with pytest.raises(Exception, match="inf"):
        XGBClassifier(n_estimators=5, verbosity=0).fit(naive, y)

    clean = _finite_scaled(RobustScaler().fit_transform(_finite_features(X, "test")), "test")
    XGBClassifier(n_estimators=5, verbosity=0).fit(clean, y)  # ne doit pas lever


def test_apply_interaction_neutralises_a_near_zero_denominator():
    """Le chemin reproduit en production : une formule `ratio` saine sur le
    fold pilote, appliquée à un fold où le dénominateur devient ~0 (pas
    exactement 0, donc non couvert par `.replace(0, np.nan)`)."""
    a = pd.Series([1.0, 2.0, 3.0])
    b = pd.Series([1.0, 1e-320, 2.0])  # ~0 sans être 0

    brut = INTERACTION_TYPES["ratio"](a, b)
    assert np.isinf(brut).any(), "sans garde, ce cas produit bien un inf réel"

    garde = apply_interaction(INTERACTION_TYPES["ratio"], a, b)
    assert not np.isinf(garde).any()
    assert pd.isna(garde.iloc[1])                 # traité comme manquant
    assert garde.iloc[0] == 1.0 and garde.iloc[2] == 1.5  # reste intact


def test_apply_interaction_still_neutralises_an_exactly_zero_denominator():
    """Non-régression : le cas déjà géré (dénominateur exactement nul) ne doit
    pas avoir été perdu en déplaçant la garde dans le registre."""
    out = apply_interaction(INTERACTION_TYPES["ratio"], pd.Series([1.0, 2.0]), pd.Series([0.0, 2.0]))
    assert pd.isna(out.iloc[0])
    assert out.iloc[1] == 1.0
