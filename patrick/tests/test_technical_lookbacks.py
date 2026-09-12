"""Phase 3 (feature/hyperparams-lookbacks) : l'audit de `feature/hyperparams-ui`
avait laisse de cote les lookbacks de features (fenetres de returns/zscore/
ma_ratio/rolling_vol/ohlc_vol, `features/technical.py`) -- defauts de
FONCTION fixes (`returns(series, windows=(1, 5, 10, 20))`, etc.), jamais
threades dans `RunConfig` ni `pipeline/engine.py::build_base_feature_pool`,
en le documentant seulement comme "trop risque" sans detail.

Cause racine identifiee ici (le refactor lui-meme est CONTENU : les
fonctions de `technical.py` acceptent deja un parametre `windows=`, seuls
les deux call sites de `pipeline/engine.py` ne le transmettaient pas) :

1. `returns()` passe la fenetre a `safe_pct_change`, qui delegue a
   `Series.pct_change(periods=...)`. Pandas accepte une periode NEGATIVE
   SANS AUCUNE ERREUR -- elle decale alors dans l'autre sens et calcule un
   rendement FUTUR (fuite look-ahead SILENCIEUSE), contrairement a
   `.rolling(w<0)` (les 3 autres fonctions), qui leve un `ValueError`
   explicite. Voir `test_returns_silently_looks_ahead_on_negative_window...`
   ci-dessous (mesure directe, pas une supposition).
2. `yang_zhang_vol` (utilise par `ohlc_vol_features`) divise par
   `(window - 1)` : `window=1` leve un `ZeroDivisionError` profond dans le
   pipeline plutot que d'etre rejete proprement en amont. Voir
   `test_yang_zhang_vol_crashes_on_window_of_one`.

Ces deux points motivent la validation de bornes dans
`pipeline/engine.py::_sanitize_lookback_windows` (filtre + avertit, ne
plante jamais -- meme discipline que `_finite_features` dans le meme
fichier) et dans `webapp/forms.py::_parse_technical_lookbacks` (erreur
explicite cote formulaire, meme patron que `_parse_optuna_bounds`).
`RunConfig` lui-meme n'a pas de bornes pydantic globales (cf. docstring
`config/schema.py` / `TuningConfig.optuna_bounds`), donc PAS de validation
au niveau du schema ici non plus -- coherent avec l'existant."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.config import defaults as D
from patrick.config.schema import RunConfig
from patrick.data.sources.yfinance_source import clean_symbol
from patrick.features.technical import build_technical_features, ohlc_vol_features, returns
from patrick.pipeline.engine import _sanitize_lookback_windows, build_base_feature_pool


def _series(n=200, seed=0) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=n)
    return pd.Series(100 + np.cumsum(rng.normal(0, 1, n)), index=idx)


# ---------------------------------------------------------------------------
# Documentation du risque reel (pin le bug qui motive la validation)
# ---------------------------------------------------------------------------

def test_returns_silently_looks_ahead_on_negative_window_undocumented_bug():
    """`returns()` ne leve AUCUNE erreur pour une fenetre negative -- elle
    calcule un rendement FUTUR (`Series.pct_change(periods=negative)` decale
    en arriere), un vrai canal de fuite si jamais expose sans validation."""
    s = _series()
    leaked = returns(s, windows=[-3])["ret_-3d"]
    # pandas' `pct_change(periods)` is always `self / self.shift(periods) - 1`
    # regardless of sign; with periods=-3, `shift(-3)` pulls in the value 3
    # bars in the FUTURE, so this is a look-ahead ratio, not a lag one.
    forward_looking = s / s.shift(-3) - 1
    pd.testing.assert_series_equal(leaked, forward_looking, check_names=False)


def test_yang_zhang_vol_crashes_on_window_of_one():
    """`ohlc_vol_features`/`yang_zhang_vol` divise par (window - 1) --
    window=1 casse profond dans le pipeline plutot que d'etre rejete
    proprement en amont."""
    idx = pd.bdate_range("2020-01-01", periods=10)
    ohlc = pd.DataFrame({"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.5}, index=idx)
    with pytest.raises(ZeroDivisionError):
        ohlc_vol_features(ohlc, prefix="px", windows=[1])


# ---------------------------------------------------------------------------
# config/defaults.py + RunConfig : non-regression des valeurs par defaut
# ---------------------------------------------------------------------------

def test_default_lookback_windows_match_technical_py_hardcoded_defaults():
    """Fige les valeurs par defaut : identiques aux anciens defauts de
    fonction codes en dur -- un run qui ne personnalise rien doit calculer
    exactement les memes features technical qu'avant ce champ."""
    assert D.DEFAULT_RETURNS_WINDOWS == [1, 5, 10, 20]
    assert D.DEFAULT_ZSCORE_WINDOWS == [10, 20, 60]
    assert D.DEFAULT_MA_RATIO_WINDOWS == [10, 20, 50]
    assert D.DEFAULT_ROLLING_VOL_WINDOWS == [10, 20]
    assert D.DEFAULT_OHLC_VOL_WINDOWS == [10, 20]


def test_run_config_default_technical_lookbacks_match_defaults():
    config = RunConfig.model_validate({"objective": {"target_symbol": "^TEST"}})
    tl = config.features.technical_lookbacks
    assert tl.returns_windows == D.DEFAULT_RETURNS_WINDOWS
    assert tl.zscore_windows == D.DEFAULT_ZSCORE_WINDOWS
    assert tl.ma_ratio_windows == D.DEFAULT_MA_RATIO_WINDOWS
    assert tl.rolling_vol_windows == D.DEFAULT_ROLLING_VOL_WINDOWS
    assert tl.ohlc_vol_windows == D.DEFAULT_OHLC_VOL_WINDOWS


# ---------------------------------------------------------------------------
# features/technical.py : threading des lookbacks (refactor contenu -- les
# fonctions avaient deja un parametre windows=, seule la signature de
# build_technical_features() doit s'enrichir)
# ---------------------------------------------------------------------------

def test_build_technical_features_without_window_args_matches_old_hardcoded_defaults():
    s = _series()
    df = build_technical_features(s, prefix="px")
    expected_cols = {
        "px_ret_1d", "px_ret_5d", "px_ret_10d", "px_ret_20d",
        "px_zscore_10d", "px_zscore_20d", "px_zscore_60d",
        "px_vs_ma10", "px_vs_ma20", "px_vs_ma50",
        "px_vol_10d", "px_vol_20d",
    }
    assert expected_cols.issubset(set(df.columns))


def test_build_technical_features_threads_custom_windows():
    """`px_rsi_14d` est toujours present (feature/guida-features-full,
    mergee independamment de ces lookbacks, a rendu rsi() inconditionnel
    dans `build_technical_features` -- non affecte par les `*_windows`
    ci-dessous, qui ne couvrent pas rsi, cf. docstring de la fonction)."""
    s = _series()
    df = build_technical_features(
        s, prefix="px",
        returns_windows=[3], zscore_windows=[7], ma_ratio_windows=[9],
        rolling_vol_windows=[4],
    )
    assert set(df.columns) == {"px_ret_3d", "px_zscore_7d", "px_vs_ma9", "px_vol_4d", "px_rsi_14d"}


def test_build_technical_features_threads_ohlc_vol_windows():
    s = _series()
    ohlc = pd.DataFrame({"Open": s, "High": s * 1.01, "Low": s * 0.99, "Close": s}, index=s.index)
    df = build_technical_features(s, prefix="px", ohlc=ohlc, ohlc_vol_windows=[15])
    assert "px_pk_15d" in df.columns
    assert "px_pk_10d" not in df.columns  # l'ancien defaut ne doit plus apparaitre


# ---------------------------------------------------------------------------
# pipeline/engine.py : sanitization defensive (protege le chemin YAML/CLI,
# pas seulement le formulaire web -- meme discipline que _finite_features)
# ---------------------------------------------------------------------------

def test_sanitize_lookback_windows_drops_non_positive_values():
    assert _sanitize_lookback_windows([-3, 0, 5, 10], min_allowed=1, label="x") == [5, 10]


def test_sanitize_lookback_windows_enforces_ohlc_minimum_of_two():
    assert _sanitize_lookback_windows([1, 2, 3], min_allowed=2, label="ohlc_vol_windows") == [2, 3]


def test_sanitize_lookback_windows_keeps_all_when_valid():
    assert _sanitize_lookback_windows([10, 20, 60], min_allowed=1, label="x") == [10, 20, 60]


def test_sanitize_lookback_windows_warns_on_stdout(capsys):
    _sanitize_lookback_windows([-1, 5], min_allowed=1, label="returns_windows")
    captured = capsys.readouterr()
    assert "WARN" in captured.out
    assert "returns_windows" in captured.out


# ---------------------------------------------------------------------------
# pipeline/engine.py : bout-en-bout (jamais de crash, fenetres invalides
# retirees silencieusement du pool -- mais signalees, cf. test ci-dessus)
# ---------------------------------------------------------------------------

def _synthetic_raw(n=300, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    target = 15 + np.cumsum(rng.normal(0, 0.5, n)).clip(min=-10)
    return pd.DataFrame({clean_symbol("^TEST"): target}, index=idx)


def test_build_base_feature_pool_never_crashes_on_invalid_configured_lookbacks():
    raw = _synthetic_raw()
    target_col = clean_symbol("^TEST")
    config = RunConfig.model_validate({
        "objective": {"target_symbol": "^TEST", "horizons": [5]},
        "features": {
            "families": ["technical"],
            "technical_lookbacks": {
                "returns_windows": [-3, 5],
                "zscore_windows": [0, 10],
            },
        },
    })
    pool = build_base_feature_pool(raw, config, target_col)
    assert f"{target_col}_ret_5d" in pool.columns
    assert f"{target_col}_ret_-3d" not in pool.columns
    assert f"{target_col}_zscore_10d" in pool.columns
    assert f"{target_col}_zscore_0d" not in pool.columns


def test_build_base_feature_pool_default_lookbacks_unchanged_columns():
    """Non-regression explicite : un run par defaut (aucune personnalisation
    des lookbacks) doit produire EXACTEMENT les memes colonnes technical
    qu'avant ce champ."""
    raw = _synthetic_raw()
    target_col = clean_symbol("^TEST")
    config = RunConfig.model_validate({
        "objective": {"target_symbol": "^TEST", "horizons": [5]},
        "features": {"families": ["technical"]},
    })
    pool = build_base_feature_pool(raw, config, target_col)
    for w in D.DEFAULT_RETURNS_WINDOWS:
        assert f"{target_col}_ret_{w}d" in pool.columns
    for w in D.DEFAULT_ZSCORE_WINDOWS:
        assert f"{target_col}_zscore_{w}d" in pool.columns
