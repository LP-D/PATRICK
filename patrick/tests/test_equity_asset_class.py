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

import re

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from patrick.config import defaults as D
from patrick.config import equity_universe
from patrick.config.schema import DataQualityConfig, FeaturesConfig, ObjectiveConfig, RunConfig, UniverseConfig
from patrick.data import ingest as ingest_module
from patrick.data.sources import fred_source, fundamentals_source, yfinance_source
from patrick.data.store import DataStore
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
# 3. Badge d'insuffisance de donnees -- CHANTIER (suite) : lit desormais le
#    meme parametre que la regle d'ingestion (min_history_years, converti en
#    jours de bourse via TRADING_DAYS_PER_YEAR), plus un seuil independant a
#    60 jours fixes. Frontieres testees a T-1/T/T+1 JOURS exactement.
# ---------------------------------------------------------------------------

def _threshold_days(min_history_years: int = None) -> int:
    years = min_history_years if min_history_years is not None else D.DEFAULT_MIN_HISTORY_YEARS
    return years * equity_sufficiency.TRADING_DAYS_PER_YEAR


def test_data_sufficiency_insufficient_at_threshold_minus_one_day(monkeypatch):
    threshold = _threshold_days()
    monkeypatch.setattr(
        equity_sufficiency.yfinance_source, "download_one",
        lambda symbol, start: pd.Series(np.arange(threshold - 1, dtype=float)),
    )
    result = equity_sufficiency.check_data_sufficiency("ALDAT.PA")
    assert result.sufficient is False
    assert result.n_trading_days == threshold - 1
    assert result.min_required == threshold
    assert "insuffisant" in result.reason.lower()


def test_data_sufficiency_sufficient_exactly_at_threshold(monkeypatch):
    """>= le seuil, pas seulement au-dessus : la limite est INCLUSE."""
    threshold = _threshold_days()
    monkeypatch.setattr(
        equity_sufficiency.yfinance_source, "download_one",
        lambda symbol, start: pd.Series(np.arange(threshold, dtype=float)),
    )
    result = equity_sufficiency.check_data_sufficiency("TTE.PA")
    assert result.sufficient is True
    assert result.n_trading_days == threshold


def test_data_sufficiency_sufficient_at_threshold_plus_one_day(monkeypatch):
    threshold = _threshold_days()
    monkeypatch.setattr(
        equity_sufficiency.yfinance_source, "download_one",
        lambda symbol, start: pd.Series(np.arange(threshold + 1, dtype=float)),
    )
    result = equity_sufficiency.check_data_sufficiency("TTE.PA")
    assert result.sufficient is True
    assert result.n_trading_days == threshold + 1


def test_data_sufficiency_uses_configured_min_history_years_not_the_default(monkeypatch):
    """Le badge doit reagir a un min_history_years EXPLICITE different du
    defaut (7 ans, pas 10) -- meme jeu de donnees, verdict different."""
    threshold_7y = _threshold_days(7)
    n_days = threshold_7y + 5  # suffisant pour 7 ans, insuffisant pour 10 ans (defaut)
    monkeypatch.setattr(
        equity_sufficiency.yfinance_source, "download_one",
        lambda symbol, start: pd.Series(np.arange(n_days, dtype=float)),
    )
    result_7y = equity_sufficiency.check_data_sufficiency("TTE.PA", min_history_years=7)
    result_default = equity_sufficiency.check_data_sufficiency("TTE.PA")
    assert result_7y.sufficient is True
    assert result_default.sufficient is False
    assert result_7y.min_required != result_default.min_required


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


def _start_days_back(days: int) -> str:
    return (pd.Timestamp.today().normalize() - pd.Timedelta(days=days)).strftime("%Y-%m-%d")


def _ingest_with_history(monkeypatch, tmp_path, target_symbol: str, days_back: int,
                          min_history_years: int) -> pd.DataFrame:
    """Ingestion synthetique, sans reseau : historique de `days_back` jours
    de bourse pour `target_symbol`, seuil configure a `min_history_years`."""
    monkeypatch.setenv("PATRICK_CACHE_ROOT", str(tmp_path / "cache"))
    monkeypatch.delenv(fred_source.FRED_API_KEY_ENV, raising=False)
    start = _start_days_back(days_back)
    idx = pd.bdate_range(start, periods=max(days_back // 7 * 5, 5))

    def fake_download(tickers, start=None, auto_adjust=True, progress=False):
        return pd.DataFrame({"Close": np.linspace(100.0, 110.0, len(idx))}, index=idx)

    monkeypatch.setattr(yfinance_source.yf, "download", fake_download)
    objective = ObjectiveConfig(target_symbol=target_symbol)
    universe = UniverseConfig(yf_tickers=[], fred_series={}, start_date=start)
    dq = DataQualityConfig(min_history_years=min_history_years)
    store = DataStore(root=str(tmp_path / f"store_{target_symbol}"))
    return ingest_module.ingest(objective, universe, store, data_quality=dq)


def test_ingest_history_rule_uses_configured_min_history_years_not_hardcoded_20(monkeypatch, tmp_path):
    """data/ingest.py:180-184 exigeait 20 ans fixes, sans aucun test --
    verifie desormais que le seuil EFFECTIVEMENT applique est
    `dq.min_history_years`, aux deux frontieres, pour deux valeurs
    differentes (10 puis 7 ans)."""
    for min_history_years in (10, 7):
        threshold_days = round(min_history_years * 365.25)

        with pytest.raises(RuntimeError, match=str(min_history_years)):
            _ingest_with_history(monkeypatch, tmp_path, f"TOOSHORT_{min_history_years}",
                                  threshold_days - 15, min_history_years)

        df_ok = _ingest_with_history(monkeypatch, tmp_path, f"OLDENOUGH_{min_history_years}",
                                      threshold_days + 15, min_history_years)
        assert len(df_ok) > 0


def test_cli_min_history_years_option_rejects_out_of_bounds_and_overrides_yaml(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from patrick.cli import app as cli_app

    yaml_path = tmp_path / "cfg.yaml"
    yaml_path.write_text(
        "objective:\n  target_symbol: '^GSPC'\n"
        "data_quality:\n  min_history_years: 10\n",
        encoding="utf-8",
    )
    runner = CliRunner()

    result = runner.invoke(cli_app, ["ingest", "--config", str(yaml_path), "--min-history-years", "999"])
    assert result.exit_code != 0

    captured = {}

    def fake_ingest(objective, universe, store=None, force=False, data_quality=None):
        captured["min_history_years"] = data_quality.min_history_years
        return pd.DataFrame({"x": [1.0]})

    monkeypatch.setattr("patrick.cli.ingest", fake_ingest)
    result2 = runner.invoke(cli_app, ["ingest", "--config", str(yaml_path), "--min-history-years", "15"])
    assert result2.exit_code == 0, result2.output
    assert captured["min_history_years"] == 15


# ---------------------------------------------------------------------------
# Etape c -- build_config_dict : bornes sur la valeur SOUMISE, propagation,
# et controle a la soumission contre l'historique deja connu localement.
# ---------------------------------------------------------------------------

def _minimal_form(**overrides):
    from starlette.datastructures import FormData
    base = {
        "horizons": ["1", "2"],
        "regimes": "GLOBAL",
        "families": ["technical"],
        "n_features_grid": "5,8",
        "sampler_candidates": ["SMOTE"],
        "algos": ["RandomForest"],
    }
    base.update(overrides)
    items = []
    for k, v in base.items():
        if isinstance(v, list):
            items.extend((k, x) for x in v)
        else:
            items.append((k, v))
    return FormData(items)


def _seed_equity_history_years_back(symbol: str, years_back: float) -> None:
    """A la difference de `test_webapp_forms.py::_seed_history` (ancre fixe
    2000-01-01, adaptee au test de TAILLE de fold), ici c'est la date de
    DEPART (earliest) qui compte -- doit refleter une anciennete reelle de
    `years_back` annees avant aujourd'hui."""
    store = DataStore()
    start = (pd.Timestamp.today().normalize() - pd.Timedelta(days=round(years_back * 365.25))).strftime("%Y-%m-%d")
    idx = pd.bdate_range(start, periods=max(round(years_back * 252), 5))
    df = pd.DataFrame({symbol: np.arange(len(idx), dtype=float)}, index=idx)
    store.save(f"raw_{symbol}", df)


def test_build_config_dict_rejects_min_history_years_out_of_bounds(monkeypatch, tmp_path):
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))
    form = _minimal_form(min_history_years="999")
    config_dict, errors = forms.build_config_dict(form, target_symbol="^VIX", name="VIX_MH_1")
    assert any("historique" in e.lower() for e in errors)
    assert config_dict["data_quality"]["min_history_years"] == D.DEFAULT_MIN_HISTORY_YEARS


def test_build_config_dict_propagates_a_valid_min_history_years_different_from_default(monkeypatch, tmp_path):
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))
    assert 15 != D.DEFAULT_MIN_HISTORY_YEARS
    form = _minimal_form(min_history_years="15")
    config_dict, errors = forms.build_config_dict(form, target_symbol="^VIX", name="VIX_MH_2")
    assert errors == []
    assert config_dict["data_quality"]["min_history_years"] == 15


def test_build_config_dict_rejects_submission_when_cached_history_is_too_short(monkeypatch, tmp_path):
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))
    _seed_equity_history_years_back("^VIX", 5)  # ~5 ans d'anciennete en cache
    form = _minimal_form(min_history_years="10")
    _config_dict, errors = forms.build_config_dict(form, target_symbol="^VIX", name="VIX_MH_3")
    assert any("historique" in e.lower() for e in errors)


def test_build_config_dict_does_not_block_min_history_years_for_a_never_cached_target(monkeypatch, tmp_path):
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))
    form = _minimal_form(min_history_years="10")
    _config_dict, errors = forms.build_config_dict(form, target_symbol="^VIX", name="VIX_MH_4")
    assert errors == []


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
    """Etape f : fixture reproduisant la forme REELLE renvoyee par yfinance
    (verifie empiriquement le 2026-09-19, `yf.Ticker("HO.PA").
    quarterly_income_stmt`) -- Thales n'a AUCUNE donnee trimestrielle cote
    yfinance : `shape=(0, 0)`, exactement `pd.DataFrame()`, pas une
    DataFrame avec des colonnes vides ni une exception. C'est le cas reel
    qui motive ce test (pas seulement D.A.T.E avant son premier exercice
    publie -- HO.PA a bien des exercices publies, simplement pas via
    `quarterly_income_stmt`, voir `income_stmt` annuel a la place, hors
    scope de ce module qui n'appelle QUE le trimestriel).

    `stmt.empty` est du CODE MORT ici, au sens observable : confirme par
    mutation-check (tour precedent) -- retirer le `or stmt.empty` du garde
    (`if stmt is None or stmt.empty:`) ne change PAS le resultat de ce
    test, une DataFrame (0,0) traversant `.T.reset_index().rename(...).
    melt(...)` sans lui produit deja un resultat vide equivalent a
    `_empty()`. Non retire malgre tout (garde explicite plus lisible/
    defensive qu'un comportement implicite de pandas) -- aucune
    modification de code de production ici, uniquement la fixture."""
    monkeypatch.setenv("PATRICK_CACHE_ROOT", str(tmp_path))

    class _FakeTicker:
        def __init__(self, symbol):
            self.quarterly_income_stmt = pd.DataFrame()  # shape (0, 0), reel pour HO.PA

    monkeypatch.setattr(fundamentals_source.yf, "Ticker", _FakeTicker)

    out = fundamentals_source.fetch_fundamentals("HO.PA")
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


def test_launch_page_badge_suffix_is_scoped_to_the_insufficient_equity_option(monkeypatch):
    """Etape e : l'ancienne assertion `"insuffisant" in resp.text` etait
    inoperante -- `webapp/i18n.py:356` ("Historique insuffisant pour
    calculer ces statistiques...") est injectee en JSON sur TOUTE page via
    `base_v2.html` (`i18n_js`), donc la chaine est presente meme quand le
    badge actions est correct. Cette version cible l'element <option> exact
    de chaque ticker."""
    def fake_download_one(symbol, start):
        if symbol == "ALDAT.PA":
            return None  # pas encore cote -> insuffisant
        return pd.Series(np.arange(equity_sufficiency.TRADING_DAYS_PER_YEAR * 20, dtype=float))  # ~20 ans, largement suffisant

    monkeypatch.setattr(equity_sufficiency.yfinance_source, "download_one", fake_download_one)
    client = TestClient(app)
    resp = client.get("/launch")
    assert resp.status_code == 200

    def _option_label(symbol: str) -> str:
        m = re.search(rf'<option value="{re.escape(symbol)}"[^>]*>([^<]*)</option>', resp.text)
        assert m is not None, f"option {symbol} introuvable sur /launch"
        return m.group(1)

    assert "données insuffisantes" in _option_label("ALDAT.PA")
    for sym in ("TTE.PA", "HO.PA", "AMZN"):
        assert "données insuffisantes" not in _option_label(sym), sym
