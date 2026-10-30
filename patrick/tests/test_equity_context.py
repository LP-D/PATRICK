"""Contexte de marché des actions : indices de comparaison par place de cotation, indice composite de la zone euro, features relatives
(rendement, bêta, corrélation, volatilité propre, force relative, écarts de taux de la zone euro) et leur branchement dans le run.
Données synthétiques, aucun réseau."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.config import defaults as D
from patrick.config import equity_context as EC
from patrick.config.instrument_names import INSTRUMENTS
from patrick.config.schema import FeaturesConfig, ObjectiveConfig, RunConfig
from patrick.data.sources.yfinance_source import clean_symbol
from patrick.features import equity_context as FE
from patrick.pipeline import engine as engine_module
from patrick.webapp import forms

IDX = pd.bdate_range("2018-01-01", periods=700)


def _prices(returns, start=100.0) -> pd.Series:
    return pd.Series(start * np.cumprod(1.0 + np.asarray(returns)), index=IDX)


def _euro_raw(seed=0, target="MC.PA", with_fred=False) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    tickers = {*EC.EURO_COMPOSITE, "^GSPC", *([EC.home_index(target)] if EC.home_index(target) else [])}
    cols = {clean_symbol(t): _prices(rng.normal(0.0003, 0.01, len(IDX))) for t in sorted(tickers)}
    home = cols[clean_symbol(EC.home_index(target))] if EC.home_index(target) else None
    br = home.pct_change().fillna(0.0).to_numpy() if home is not None else rng.normal(0, 0.01, len(IDX))
    cols[clean_symbol(target)] = _prices(1.2 * br + rng.normal(0.0, 0.004, len(IDX)))
    raw = pd.DataFrame(cols)
    if with_fred:
        raw["Germany_10Y_Yield"] = np.linspace(2.0, 3.0, len(IDX))
        raw["Italy_10Y_Yield"] = np.linspace(3.5, 4.5, len(IDX))
        raw["France_10Y_Yield"] = np.linspace(2.6, 3.2, len(IDX))
        raw["EUR_DFR_Rate"] = np.linspace(0.0, 2.0, len(IDX))
        raw["DFF"] = np.linspace(0.1, 4.0, len(IDX))
    return raw


# ---------------------------------------------------------------------------------------------------------------- configuration
@pytest.mark.parametrize("symbol, suffix, region, home", [
    ("MC.PA", "PA", "euro", "^FCHI"), ("SAP.DE", "DE", "euro", "^GDAXI"), ("ASML.AS", "AS", "euro", "^AEX"),
    ("ENEL.MI", "MI", "euro", "FTSEMIB.MI"), ("SHEL.L", "L", "europe", "^FTSE"), ("NESN.SW", "SW", "europe", "^SSMI"),
    ("NOVO-B.CO", "CO", "europe", None), ("7203.T", "T", "other", "^N225"), ("AAPL", None, "other", "^GSPC"),
    ("BRK-B", None, "other", "^GSPC"),
])
def test_each_place_is_compared_with_its_own_index(symbol, suffix, region, home):
    assert EC.suffix_of(symbol) == suffix
    assert EC.region_of(symbol) == region
    assert EC.home_index(symbol) == home


def test_indices_and_futures_are_not_mistaken_for_stocks():
    for symbol in ("^FCHI", "GC=F", "EURUSD=X", "BTC-USD"):
        assert EC.suffix_of(symbol) is None
        assert EC.context_tickers(symbol) == []


def test_context_tickers_of_a_euro_stock_are_its_index_the_euro_composite_and_the_world():
    tickers = EC.context_tickers("MC.PA")
    assert tickers[0] == "^FCHI" and set(EC.EURO_COMPOSITE) <= set(tickers) and tickers[-1] == "^GSPC"
    assert len(tickers) == len(set(tickers))
    assert EC.context_tickers("AAPL") == ["^GSPC"]
    assert "^FTSE" in EC.context_tickers("SHEL.L") and set(EC.EURO_COMPOSITE) <= set(EC.context_tickers("SHEL.L"))
    assert set(EC.context_tickers("NOVO-B.CO")) == set(EC.EURO_COMPOSITE) | {"^GSPC"}      # pas d'indice danois exploitable


def test_every_reference_index_has_a_display_name():
    for ticker in (*EC.HOME_INDEX_BY_SUFFIX.values(), *EC.EURO_COMPOSITE, EC.GLOBAL_BENCHMARK):
        assert ticker in INSTRUMENTS, ticker


def test_every_stock_of_the_universe_has_a_reference():
    from patrick.config.equity_universe import equity_symbols

    # Danemark, Norvège, Suède, Finlande : pas d'indice de place, mais toujours l'indice composite européen
    for symbol in equity_symbols():
        assert EC.context_tickers(symbol), symbol
        assert EC.home_index(symbol) or EC.uses_euro_composite(symbol), symbol


# ---------------------------------------------------------------------------------------------------------------- univers du run
def test_a_stock_target_gets_its_context_tickers_in_the_feature_universe_and_no_other_target_does():
    yf, _ = forms.universe_excluding("MC.PA", scope="default")
    assert set(EC.context_tickers("MC.PA")) <= set(yf) and "MC.PA" not in yf
    assert yf.count("^GSPC") == 1                                      # déjà dans le pool par défaut : pas de doublon
    yf_vix, _ = forms.universe_excluding("^VIX", scope="default")
    assert not set(EC.EURO_COMPOSITE) & set(yf_vix)


def test_new_runs_switch_the_context_features_on_but_a_stored_config_keeps_its_columns():
    assert FeaturesConfig().enable_equity_context_features is False       # un run enregistré se rejoue avec ses colonnes d'origine
    assert D.DEFAULT_ENABLE_EQUITY_CONTEXT_FEATURES is True
    assert forms.default_config_dict()["features"]["enable_equity_context_features"] is True
    assert RunConfig.model_validate(forms.default_config_dict()).features.enable_equity_context_features is True


# ---------------------------------------------------------------------------------------------------------------- features
def test_euro_composite_is_the_mean_of_the_national_indices_and_needs_three_of_them():
    raw = _euro_raw()
    comp = FE.euro_composite(raw)
    cols = [clean_symbol(t) for t in EC.EURO_COMPOSITE]
    expected = raw[cols].pct_change().mean(axis=1).fillna(0.0)
    assert comp.name == FE.EURO_COMPOSITE_NAME and comp.iloc[0] == pytest.approx(1.0 + expected.iloc[0])
    assert comp.pct_change().iloc[5:].to_numpy() == pytest.approx(expected.iloc[5:].to_numpy())
    assert FE.euro_composite(raw[cols[:2]]) is None


def test_a_paris_stock_is_compared_with_cac_euro_composite_and_world():
    raw = _euro_raw()
    out = FE.build_equity_context_features(raw, "MC.PA")
    t = "MC.PA_ctx"
    for ref in ("IDX_FCHI", "EURO_COMPOSITE", "IDX_GSPC"):
        assert f"{t}_rel_{ref}_ret_22d" in out.columns
        assert f"{t}_beta_{ref}_66d" in out.columns and f"{t}_corr_{ref}_252d" in out.columns
        assert f"{t}_idio_vol_{ref}_66d" in out.columns and f"{t}_rel_strength_z_{ref}_252d" in out.columns
    assert out.index.equals(raw.index)
    assert all(c.startswith(t) for c in out.columns)


def test_beta_correlation_and_idiosyncratic_vol_recover_a_known_relationship():
    rng = np.random.default_rng(3)
    bench_ret = rng.normal(0.0002, 0.01, len(IDX))
    raw = pd.DataFrame({"IDX_GSPC": _prices(bench_ret), "AAPL": _prices(1.5 * bench_ret)})
    out = FE.build_equity_context_features(raw, "AAPL")
    last = out.iloc[-1]
    assert last["AAPL_ctx_beta_IDX_GSPC_66d"] == pytest.approx(1.5, abs=1e-6)
    assert last["AAPL_ctx_corr_IDX_GSPC_252d"] == pytest.approx(1.0, abs=1e-6)
    assert last["AAPL_ctx_idio_vol_IDX_GSPC_66d"] == pytest.approx(0.0, abs=1e-6)
    noisy = pd.DataFrame({"IDX_GSPC": raw["IDX_GSPC"], "AAPL": _prices(1.5 * bench_ret + rng.normal(0, 0.01, len(IDX)))})
    assert FE.build_equity_context_features(noisy, "AAPL").iloc[-1]["AAPL_ctx_idio_vol_IDX_GSPC_66d"] > 0.05


def test_relative_return_is_the_stock_minus_its_reference():
    bench = _prices(np.full(len(IDX), 0.001))
    raw = pd.DataFrame({"IDX_GSPC": bench, "AAPL": pd.Series(100.0, index=IDX)})
    out = FE.build_equity_context_features(raw, "AAPL")
    assert out["AAPL_ctx_rel_IDX_GSPC_ret_22d"].iloc[-1] == pytest.approx(-(bench.iloc[-1] / bench.iloc[-23] - 1.0))


def test_features_are_causal_nothing_in_the_past_depends_on_the_future():
    raw = _euro_raw(seed=5, with_fred=True)
    full = FE.build_equity_context_features(raw, "MC.PA")
    cut = FE.build_equity_context_features(raw.iloc[:450], "MC.PA")
    pd.testing.assert_frame_equal(full.iloc[:450], cut, check_exact=False, rtol=1e-9, atol=1e-12)


def test_missing_references_are_skipped_never_invented():
    raw = _euro_raw()
    no_cac = raw.drop(columns=["IDX_FCHI"])
    out = FE.build_equity_context_features(no_cac, "MC.PA")
    assert not any("IDX_FCHI" in c for c in out.columns) and any("EURO_COMPOSITE" in c for c in out.columns)
    two = raw.drop(columns=[clean_symbol(t) for t in EC.EURO_COMPOSITE[2:]])
    assert not any("EURO_COMPOSITE" in c for c in FE.build_equity_context_features(two, "MC.PA").columns)
    only_target = raw[["MC.PA"]]
    assert FE.build_equity_context_features(only_target, "MC.PA").empty


def test_a_target_that_is_not_a_stock_gets_nothing():
    raw = _euro_raw()
    raw["IDX_VIX"] = raw["IDX_GSPC"]
    assert FE.build_equity_context_features(raw, "^VIX").empty
    assert FE.build_equity_context_features(raw, "GC=F").empty


def test_euro_area_stress_features_are_for_euro_stocks_only_and_need_the_series():
    euro = FE.build_equity_context_features(_euro_raw(with_fred=True), "MC.PA")
    assert "MC.PA_ctx_spread_it_de_level" in euro.columns and "MC.PA_ctx_spread_fr_de_chg_66d" in euro.columns
    assert "MC.PA_ctx_policy_gap_ecb_fed_level" in euro.columns
    assert euro["MC.PA_ctx_spread_it_de_level"].iloc[-1] == pytest.approx(4.5 - 3.0)
    assert euro["MC.PA_ctx_policy_gap_ecb_fed_level"].iloc[-1] == pytest.approx(2.0 - 4.0)
    assert not any("spread" in c for c in FE.build_equity_context_features(_euro_raw(with_fred=False), "MC.PA").columns)
    london = _euro_raw(target="SHEL.L", with_fred=True)
    assert not any("spread" in c for c in FE.build_equity_context_features(london, "SHEL.L").columns)


def test_the_euro_series_the_features_read_are_in_the_run_universe():
    labels = set(D.DEFAULT_UNIVERSE_FRED_SERIES)
    assert {"Germany_10Y_Yield", "France_10Y_Yield", "Italy_10Y_Yield", "EUR_DFR_Rate", "DFF"} <= labels


# ---------------------------------------------------------------------------------------------------------------- branchement dans le run
def _pool(target: str, raw: pd.DataFrame, on: bool) -> pd.DataFrame:
    config = RunConfig(objective=ObjectiveConfig(target_symbol=target),
                       features=FeaturesConfig(families=["technical"], enable_equity_context_features=on))
    return engine_module.build_base_feature_pool(raw, config, target_col=clean_symbol(target))


def test_the_run_pool_gains_the_context_columns_only_when_the_switch_is_on(monkeypatch):
    monkeypatch.setattr(engine_module, "download_ohlc", lambda *a, **k: None)
    raw = _euro_raw(seed=2)
    on, off = _pool("MC.PA", raw, True), _pool("MC.PA", raw, False)
    assert any(c.startswith("MC.PA_ctx_") for c in on.columns) and not any("_ctx_" in c for c in off.columns)
    assert set(off.columns) <= set(on.columns)                          # rien d'existant ne bouge : on n'ajoute que des colonnes
    pd.testing.assert_frame_equal(on[off.columns], off)


def test_the_switch_is_a_noop_for_a_target_that_is_not_a_stock(monkeypatch):
    monkeypatch.setattr(engine_module, "download_ohlc", lambda *a, **k: None)
    raw = _euro_raw(seed=2)
    raw["IDX_VIX"] = raw["IDX_GSPC"] * 0.2
    on, off = _pool("^VIX", raw, True), _pool("^VIX", raw, False)
    pd.testing.assert_frame_equal(on, off)


def test_the_config_hash_only_moves_for_a_stock_with_the_switch_on():
    from patrick.pipeline.engine import _config_hash

    def cfg(target: str, on: bool) -> RunConfig:
        return RunConfig(objective=ObjectiveConfig(target_symbol=target), features=FeaturesConfig(enable_equity_context_features=on))

    assert _config_hash(cfg("^VIX", True)) == _config_hash(cfg("^VIX", False))        # sans effet : le hachage d'avant le champ
    assert _config_hash(cfg("MC.PA", False)) != _config_hash(cfg("MC.PA", True))
