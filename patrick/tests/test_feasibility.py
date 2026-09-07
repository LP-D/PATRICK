"""Seuil de faisabilite walk-forward (feature/expanded-horizons) : un
(ticker, horizon) est faisable seulement si CHAQUE fold de walk-forward
conserve au moins une ligne de test apres embargo -- sinon le fold est
integralement vide (`validation/embargo.py::embargo_mask` retire les
`embargo_bars` premieres lignes du masque de test, `embargo_bars` valant
`horizon` par defaut, cf. `config/defaults.py::DEFAULT_EMBARGO_BARS`).

`validation/walkforward.py::build_fold_cuts` decoupe `n_obs` observations en
`n_wf_folds` segments de test de taille
`test_span = (n_obs - int(n_obs * min_train_frac)) // n_wf_folds` -- taille du
PREMIER fold, et donc du plus petit (le dernier absorbe le reste de la
division entiere). Avec les valeurs par defaut actuelles
(`n_wf_folds=5`, `min_train_frac=0.40`), `test_span ~= 0.12 * n_obs`, d'ou le
seuil corrige `n_obs > horizon / 0.12 ~= 8.33 x horizon` -- PAS l'ancien 6x
d'un audit ponctuel precedent, qui ignorait l'interaction avec l'embargo.

Chiffre reel utilise ci-dessous : BTC-USD a 4371 jours de bourse en cache
local au moment de cet audit (`~/.patrick/store`, cle `raw_BTC-USD`, verifie
directement via `DataStore` -- pas une table figee, cf. module docstring de
`validation/feasibility.py`)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.config.defaults import DEFAULT_MIN_TRAIN_FRAC, DEFAULT_N_WF_FOLDS
from patrick.data.store import DataStore
from patrick.validation.feasibility import (
    check_feasibility,
    is_feasible,
    min_obs_required,
    min_test_fold_size,
)
from patrick.validation.walkforward import build_fold_cuts

BTC_USD_N_OBS_AUDIT = 4371  # cf. docstring ci-dessus


def _real_min_fold_size(n_obs: int, n_wf_folds: int, min_train_frac: float) -> int:
    """Calcule la taille du plus petit fold de test directement via
    `build_fold_cuts` (le VRAI code de decoupage), independamment de
    `min_test_fold_size` -- verifie que les deux formules concordent plutot
    que de dupliquer aveuglement la logique dans le test."""
    dates = pd.bdate_range("2000-01-01", periods=n_obs)
    cuts = build_fold_cuts(dates, n_wf_folds=n_wf_folds, min_train_frac=min_train_frac)
    sizes = [cuts[k + 1] - cuts[k] for k in range(len(cuts) - 1)]
    return min(sizes)


@pytest.mark.parametrize("n_obs", [100, 523, 1000, 4371, 6885, 10000])
def test_min_test_fold_size_matches_real_build_fold_cuts(n_obs):
    expected = _real_min_fold_size(n_obs, DEFAULT_N_WF_FOLDS, DEFAULT_MIN_TRAIN_FRAC)
    assert min_test_fold_size(n_obs, DEFAULT_N_WF_FOLDS, DEFAULT_MIN_TRAIN_FRAC) == expected


def test_btc_usd_history_is_ineligible_at_756_days_horizon():
    """756j (candidat 'long') : 8.33 x 756 ~= 6300j requis -- BTC-USD n'a que
    4371j en cache -> infaisable."""
    assert is_feasible(BTC_USD_N_OBS_AUDIT, 756) is False


def test_btc_usd_history_is_eligible_at_504_days_horizon():
    """504j (candidat 'long') : 8.33 x 504 ~= 4200j requis -- BTC-USD (4371j)
    passe, sous le seuil corrige (l'ancien 6x, 6 x 504 = 3024, aurait
    egalement dit 'faisable' ici -- ce cas ne distingue pas les deux seuils,
    voir le test 756j ci-dessus pour ca)."""
    assert is_feasible(BTC_USD_N_OBS_AUDIT, 504) is True


def test_corrected_threshold_differs_from_the_old_naive_6x_at_756_days():
    """La ou l'ancien seuil 6x (trop optimiste) aurait dit 'faisable'
    (6 x 756 = 4536 < 4371 ? non -- verifions le cas qui les distingue
    vraiment : un n_obs entre 6x et 8.33x horizon, ici ~5000j a horizon
    756j)."""
    n_obs = 5000
    old_naive_6x_says_feasible = n_obs > 6 * 756  # 4536 -> True (l'ancien seuil, trop optimiste)
    assert old_naive_6x_says_feasible is True
    assert is_feasible(n_obs, 756) is False  # le seuil corrige (8.33x = 6300) le contredit


@pytest.mark.parametrize("horizon", [1, 2, 3, 5, 7, 10, 15, 20, 30, 252, 504, 756])
def test_min_obs_required_is_the_exact_boundary(horizon):
    required = min_obs_required(horizon, DEFAULT_N_WF_FOLDS, DEFAULT_MIN_TRAIN_FRAC)
    assert is_feasible(required, horizon, DEFAULT_N_WF_FOLDS, DEFAULT_MIN_TRAIN_FRAC) is True
    assert is_feasible(required - 1, horizon, DEFAULT_N_WF_FOLDS, DEFAULT_MIN_TRAIN_FRAC) is False


def test_is_feasible_rejects_zero_or_negative_n_obs():
    assert is_feasible(0, 10) is False
    assert is_feasible(-5, 10) is False


def _seed_store(tmp_path, symbol: str, n_obs: int) -> DataStore:
    store = DataStore(root=str(tmp_path))
    idx = pd.bdate_range("2000-01-01", periods=n_obs)
    df = pd.DataFrame({symbol: np.arange(n_obs, dtype=float)}, index=idx)
    store.save(f"raw_{symbol}", df)
    return store


def test_check_feasibility_reads_real_history_depth_from_the_local_store(tmp_path):
    store = _seed_store(tmp_path, "FAKE-SHORT", BTC_USD_N_OBS_AUDIT)
    result = check_feasibility("FAKE-SHORT", 756, store=store)
    assert result.source == "store"
    assert result.n_obs == BTC_USD_N_OBS_AUDIT
    assert result.feasible is False
    assert result.n_obs_required == min_obs_required(756)


def test_check_feasibility_reads_real_history_depth_from_the_local_store_long_horizon_ok(tmp_path):
    store = _seed_store(tmp_path, "FAKE-LONG", 6885)
    result = check_feasibility("FAKE-LONG", 756, store=store)
    assert result.source == "store"
    assert result.feasible is True


def test_check_feasibility_unknown_symbol_is_exposed_not_blocked(tmp_path):
    """Rien en cache pour ce symbole (jamais lance comme cible) : le principe
    directeur de cette session est d'exposer avec un avertissement plutot que
    de bloquer par prudence -- feasible=True mais source="unknown" pour que
    l'appelant (UI/backend) puisse afficher la reserve, sans jamais avoir
    fige de table statique de profondeurs."""
    store = DataStore(root=str(tmp_path))
    result = check_feasibility("NEVER-SEEN", 756, store=store)
    assert result.source == "unknown"
    assert result.feasible is True
    assert result.n_obs is None


def test_check_feasibility_reason_mentions_available_and_required_bars(tmp_path):
    store = _seed_store(tmp_path, "FAKE-SHORT", BTC_USD_N_OBS_AUDIT)
    result = check_feasibility("FAKE-SHORT", 756, store=store)
    assert str(BTC_USD_N_OBS_AUDIT) in result.reason
    assert str(min_obs_required(756)) in result.reason
