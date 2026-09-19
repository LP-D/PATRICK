"""CHANTIER (feature/equity-asset-class) -- TDD pour la nouvelle classe
d'actifs "actions individuelles" (prix ajustes via yfinance, univers separe
de commo/macro, fondamentaux hors pipeline par defaut, badge d'insuffisance
de donnees, exclusions Guida documentees). Aucun appel reseau reel dans
cette suite : yfinance/`fundamentals_source` sont systematiquement
monkeypatches, meme style que `test_guida_features.py`/
`test_guida_scan_cost.py` (attentes derivees a la main de la construction
des donnees synthetiques, ou de valeurs REELLEMENT observees via yfinance
le 2026-09-19 pour le cas du detachement de dividende TotalEnergies)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from patrick.config import defaults as D
from patrick.config import equity_universe
from patrick.config.schema import FeaturesConfig, ObjectiveConfig, RunConfig
from patrick.data.sources import fundamentals_source, yfinance_source
from patrick.features import equity_fundamentals, guida
from patrick.pipeline import engine as engine_module
from patrick.validation import equity_sufficiency
from patrick.webapp import forms
from patrick.webapp.app import app

# ---------------------------------------------------------------------------
# 1. Univers actions -- config separee, metadonnees, non fuite dans le pool
#    de features par defaut d'un autre run.
# ---------------------------------------------------------------------------

def test_equity_universe_has_required_metadata_per_ticker():
    for symbol, meta in equity_universe.EQUITY_UNIVERSE.items():
        assert {"label", "currency", "exchange", "first_listed"} <= set(meta), symbol
        assert meta["currency"] and isinstance(meta["currency"], str)
        assert meta["exchange"] and isinstance(meta["exchange"], str)


def test_equity_universe_contains_the_four_expected_tickers():
    assert set(equity_universe.EQUITY_UNIVERSE) == {"TTE.PA", "HO.PA", "AMZN", "ALDAT.PA"}


def test_equity_group_absent_from_default_target_groups():
    """Separation explicite (spec) : le groupe actions ne doit JAMAIS
    apparaitre dans `DEFAULT_TARGET_GROUPS` lui-meme -- sans quoi il
    fuirait dans `DEFAULT_UNIVERSE_YF_TICKERS` (univers de features par
    defaut de CHAQUE run, y compris ceux predisant le VIX/l'or/etc.) et
    casserait `test_universe_matches_exactly_the_reduced_target_set`."""
    assert equity_universe.EQUITY_TARGET_GROUP not in D.DEFAULT_TARGET_GROUPS
    for symbol in equity_universe.EQUITY_UNIVERSE:
        assert symbol not in D.DEFAULT_UNIVERSE_YF_TICKERS


def test_equities_are_selectable_as_target_but_never_in_the_default_feature_universe():
    """`webapp/forms.py` : les actions doivent apparaitre comme CIBLES
    possibles (TARGET_GROUPS/TARGET_SOURCE_BY_SYMBOL), mais
    `universe_excluding` (l'univers de features par defaut de tout run,
    quel que soit son target) ne doit JAMAIS les inclure."""
    assert equity_universe.EQUITY_TARGET_GROUP in forms.TARGET_GROUPS
    for symbol in equity_universe.EQUITY_UNIVERSE:
        assert symbol in forms.TARGET_SOURCE_BY_SYMBOL
        assert forms.TARGET_SOURCE_BY_SYMBOL[symbol] == "yfinance"

    yf_tickers, _ = forms.universe_excluding("^VIX")
    for symbol in equity_universe.EQUITY_UNIVERSE:
        assert symbol not in yf_tickers


# ---------------------------------------------------------------------------
# 2. Prix ajustes (splits/dividendes) via yfinance.
#
# Detachement REEL de TotalEnergies (TTE.PA), verifie empiriquement via
# yfinance le 2026-09-19 : dividende de 0.85EUR, ex-date 2026-06-30.
#   - Close BRUT (auto_adjust=False) le 2026-06-25 : 69.269997
#   - Close AJUSTE (auto_adjust=True)  le 2026-06-25 : 68.416420
# (integre le detachement survenu 3 jours de bourse plus tard). Le module
# doit systematiquement demander `auto_adjust=True` et restituer la valeur
# AJUSTEE, jamais la brute.
# ---------------------------------------------------------------------------

def test_equity_prices_are_dividend_adjusted_totalenergies_2026_06_30(monkeypatch):
    captured: dict = {}
    adjusted_close = [68.416420, 67.517639, 68.130005, 68.029999]
    raw_close_2026_06_25 = 69.269997  # NON ajuste -- ne doit jamais apparaitre en sortie

    def fake_download(tickers, **kwargs):
        captured.update(kwargs)
        idx = pd.bdate_range("2026-06-25", periods=4)
        cols = pd.MultiIndex.from_tuples([("Close", "TTE.PA")])
        return pd.DataFrame(adjusted_close, index=idx, columns=cols)

    monkeypatch.setattr(yfinance_source.yf, "download", fake_download)
    out = yfinance_source.download_batch(["TTE.PA"], "2026-06-01")

    assert captured.get("auto_adjust") is True
    assert out["TTE.PA"].iloc[0] == pytest.approx(68.416420)
    assert out["TTE.PA"].iloc[0] != pytest.approx(raw_close_2026_06_25)
    assert out["TTE.PA"].iloc[-1] == pytest.approx(68.029999)


# ---------------------------------------------------------------------------
# 3. Badge d'insuffisance de donnees -- seuil ABSOLU de jours de cotation,
#    independant du garde-fou horizon existant (validation/feasibility.py).
# ---------------------------------------------------------------------------

def test_data_sufficiency_insufficient_below_threshold(monkeypatch):
    monkeypatch.setattr(
        equity_sufficiency.yfinance_source, "download_one",
        lambda symbol, start: pd.Series(np.arange(10, dtype=float)),
    )
    result = equity_sufficiency.check_data_sufficiency("ALDAT.PA", min_trading_days=60)
    assert result.sufficient is False
    assert result.n_trading_days == 10
    assert result.min_required == 60
    assert "insuffisant" in result.reason.lower()


def test_data_sufficiency_sufficient_at_threshold_boundary(monkeypatch):
    """>= le seuil, pas seulement au-dessus : la limite est INCLUSE."""
    monkeypatch.setattr(
        equity_sufficiency.yfinance_source, "download_one",
        lambda symbol, start: pd.Series(np.arange(60, dtype=float)),
    )
    result = equity_sufficiency.check_data_sufficiency("TTE.PA", min_trading_days=60)
    assert result.sufficient is True
    assert result.n_trading_days == 60


def test_data_sufficiency_never_fetched_ticker_is_zero_days_not_an_exception(monkeypatch):
    """D.A.T.E avant sa cotation effective (2026-09-25) : yfinance ne
    renvoie rien (`download_one` -> None, deja verifie empiriquement le
    2026-09-19) -- doit etre traite comme 0 jour, jamais planter."""
    monkeypatch.setattr(
        equity_sufficiency.yfinance_source, "download_one",
        lambda symbol, start: None,
    )
    result = equity_sufficiency.check_data_sufficiency("ALDAT.PA")
    assert result.sufficient is False
    assert result.n_trading_days == 0


def test_default_min_history_years_is_10():
    assert D.DEFAULT_MIN_HISTORY_YEARS == 10


# ---------------------------------------------------------------------------
# 4. Fondamentaux -- collecte, format long, mise en cache locale, et flag
#    enable_fundamentals_features=False n'injecte AUCUNE colonne dans le
#    pipeline d'entrainement (comportement par defaut inchange).
# ---------------------------------------------------------------------------

def test_fetch_fundamentals_returns_long_format(monkeypatch, tmp_path):
    monkeypatch.setenv("PATRICK_CACHE_ROOT", str(tmp_path))

    class _FakeTicker:
        def __init__(self, symbol):
            self.quarterly_income_stmt = pd.DataFrame(
                {pd.Timestamp("2025-12-31"): [1000.0], pd.Timestamp("2026-03-31"): [1100.0]},
                index=["Total Revenue"],
            )

    monkeypatch.setattr(fundamentals_source.yf, "Ticker", _FakeTicker)

    out = fundamentals_source.fetch_fundamentals("TTE.PA")
    assert list(out.columns) == ["fiscalDateEnding", "metric", "value"]
    assert set(out["fiscalDateEnding"]) == {"2025-12-31", "2026-03-31"}
    assert set(out["value"]) == {1000.0, 1100.0}


def test_fetch_fundamentals_empty_when_yfinance_has_nothing(monkeypatch, tmp_path):
    """Titre trop recent (ex. D.A.T.E avant son premier exercice publie) --
    DataFrame vide, jamais une exception."""
    monkeypatch.setenv("PATRICK_CACHE_ROOT", str(tmp_path))

    class _FakeTicker:
        def __init__(self, symbol):
            self.quarterly_income_stmt = pd.DataFrame()

    monkeypatch.setattr(fundamentals_source.yf, "Ticker", _FakeTicker)

    out = fundamentals_source.fetch_fundamentals("ALDAT.PA")
    assert out.empty
    assert list(out.columns) == ["fiscalDateEnding", "metric", "value"]


def test_build_equity_fundamentals_features_reindexes_and_ffills(monkeypatch):
    monkeypatch.setattr(fundamentals_source, "fetch_fundamentals", lambda symbol: pd.DataFrame({
        "fiscalDateEnding": ["2025-12-31", "2026-03-31"],
        "metric": ["Total Revenue", "Total Revenue"],
        "value": [1000.0, 1100.0],
    }))
    idx = pd.bdate_range("2026-01-01", periods=100)
    out = equity_fundamentals.build_equity_fundamentals_features("TTE.PA", idx)

    col = "TTE_PA_Total_Revenue_fundamental"
    assert col in out.columns
    before = out.index < "2026-03-31"
    after = out.index >= "2026-03-31"
    assert (out.loc[before, col] == 1000.0).all()
    assert (out.loc[after, col] == 1100.0).all()


def test_build_equity_fundamentals_features_is_a_noop_for_a_non_equity_symbol(monkeypatch):
    calls = []
    monkeypatch.setattr(fundamentals_source, "fetch_fundamentals",
                         lambda symbol: (calls.append(symbol), pd.DataFrame())[1])
    idx = pd.bdate_range("2024-01-01", periods=5)
    out = equity_fundamentals.build_equity_fundamentals_features("^VIX", idx)
    assert out.empty
    assert not calls  # jamais interroge pour un symbole non-action


def test_enable_fundamentals_features_defaults_to_false():
    config = RunConfig(objective=ObjectiveConfig(target_symbol="TTE.PA"))
    assert config.features.enable_fundamentals_features is False
    assert D.DEFAULT_ENABLE_FUNDAMENTALS_FEATURES is False


def test_enable_fundamentals_features_false_injects_no_fundamental_columns(monkeypatch):
    """Coeur du garde-fou : le pipeline d'entrainement (`build_base_feature_
    pool`) ne doit ajouter AUCUNE colonne fondamentale -- et ne doit meme
    pas appeler `fetch_fundamentals` -- quand le flag est a False (defaut)."""
    calls = []
    monkeypatch.setattr(fundamentals_source, "fetch_fundamentals",
                         lambda symbol: (calls.append(symbol), pd.DataFrame())[1])
    monkeypatch.setattr(engine_module, "download_ohlc", lambda *a, **k: None)

    raw = pd.DataFrame({"TTE_PA": [100.0, 101.0, 102.0]},
                        index=pd.bdate_range("2024-01-01", periods=3))
    config = RunConfig(
        objective=ObjectiveConfig(target_symbol="TTE.PA"),
        features=FeaturesConfig(families=["technical"]),
    )
    assert config.features.enable_fundamentals_features is False

    pool = engine_module.build_base_feature_pool(raw, config, target_col="TTE_PA")

    assert not calls
    assert not any("fundamental" in c.lower() for c in pool.columns)


# ---------------------------------------------------------------------------
# 5. Exclusions documentees (pas des silences) : carry et cross-sectional
#    momentum restent absents pour la classe actions.
# ---------------------------------------------------------------------------

def test_cross_sectional_momentum_is_empty_not_silently_zero_for_equity_columns():
    """L'univers actions (4 tickers) ne correspond a aucun ticker du groupe
    commodites que `cross_sectional_momentum_features` filtre en interne --
    le resultat doit etre une absence EXPLICITE (DataFrame vide), jamais une
    colonne remplie de zeros qui ferait croire a un vrai calcul silencieux."""
    idx = pd.bdate_range("2020-01-01", periods=6)
    raw = pd.DataFrame({
        "TTE_PA": [100, 101, 102, 103, 104, 105.0],
        "HO_PA": [100, 99, 98, 97, 96, 95.0],
        "AMZN": [100, 102, 104, 106, 108, 110.0],
    }, index=idx)
    out = guida.cross_sectional_momentum_features(raw, windows=[5])
    assert out.empty


def test_carry_is_empty_not_silently_zero_for_equity_only_raw():
    raw = pd.DataFrame({"TTE_PA": [100.0, 101.0, 102.0]})
    out = guida.eurusd_carry_features(raw)
    assert out.empty


def test_equity_feature_exclusions_documents_carry_and_cross_sectional_momentum():
    exclusions = guida.equity_feature_exclusions()
    assert set(exclusions) == {"carry", "cross_sectional_momentum"}
    assert exclusions["carry"].strip()
    assert exclusions["cross_sectional_momentum"].strip()
    # message explicite, pas un silence : cite le seuil minimum reel
    assert str(guida._MIN_GROUP_SIZE_FOR_RANKING) in exclusions["cross_sectional_momentum"]
    assert str(len(equity_universe.EQUITY_UNIVERSE)) in exclusions["cross_sectional_momentum"]


# ---------------------------------------------------------------------------
# 6. Pages web -- badge visible sur /launch et sur /equities (toute page
#    listant des tickers actions).
# ---------------------------------------------------------------------------

def test_equities_page_returns_200_and_lists_every_ticker(monkeypatch):
    monkeypatch.setattr(
        equity_sufficiency.yfinance_source, "download_one",
        lambda symbol, start: pd.Series(np.arange(100, dtype=float)),
    )
    monkeypatch.setattr(fundamentals_source, "fetch_fundamentals",
                         lambda symbol: pd.DataFrame(columns=["fiscalDateEnding", "metric", "value"]))
    client = TestClient(app)
    resp = client.get("/equities")
    assert resp.status_code == 200
    for symbol, meta in equity_universe.EQUITY_UNIVERSE.items():
        assert symbol in resp.text
        assert meta["label"] in resp.text
    # exclusions carry/cross-sectional momentum affichees explicitement
    assert "Cross-sectional momentum" in resp.text or "cross_sectional_momentum" in resp.text


def test_launch_page_shows_insufficient_badge_for_a_low_history_equity(monkeypatch):
    def fake_download_one(symbol, start):
        if symbol == "ALDAT.PA":
            return None  # pas encore cote
        return pd.Series(np.arange(6863, dtype=float))

    monkeypatch.setattr(equity_sufficiency.yfinance_source, "download_one", fake_download_one)
    client = TestClient(app)
    resp = client.get("/launch")
    assert resp.status_code == 200
    assert "ALDAT.PA" in resp.text
    assert "insuffisant" in resp.text
