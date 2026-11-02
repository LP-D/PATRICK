"""Carry de change (`features/fx_carry.py`) : disponibilité des taux, signaux, neutralité au dollar, rejeu mensuel net de frais, causalité. Données synthétiques."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.features import fx_carry as fc

PAIRS = {ccy: pair for ccy, (_sid, pair, _d) in fc.CURRENCIES.items()}


def _rates(values: dict[str, float], start="2019-01-01", months=40) -> pd.DataFrame:
    idx = pd.date_range(start, periods=months, freq="MS")
    return pd.DataFrame({k: pd.Series(v, index=idx) for k, v in values.items()})


def _spot(days=1100, seed=0, flat=False) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2019-01-01", periods=days)
    out = {}
    for _sid, pair, _direct in fc.CURRENCIES.values():
        out[pair] = pd.Series(1.0 if flat else 1.0 * np.cumprod(1 + rng.standard_normal(days) * 0.005), index=idx)
    return pd.DataFrame(out)


ALL_FLAT = {"USD": 1.0, "EUR": 0.0, "GBP": 1.0, "AUD": 2.0, "NZD": 3.0, "JPY": 0.5, "CAD": 1.5, "CHF": -0.5}


def test_month_ends_are_the_last_trading_day_of_each_month():
    idx = pd.bdate_range("2020-01-01", "2020-04-30")
    ends = fc.month_ends(idx)
    assert [d.strftime("%Y-%m-%d") for d in ends] == ["2020-01-31", "2020-02-28", "2020-03-31", "2020-04-30"]


def test_a_rate_is_known_only_after_the_publication_lag():
    rates = _rates({"USD": 1.0, "EUR": 2.0}, months=6)
    rates.loc["2019-02-01", "EUR"] = 9.0                       # le taux de février
    at = pd.DatetimeIndex(["2019-03-29", "2019-04-15", "2019-04-30", "2019-05-31"])
    known = fc.known_rates(rates, at, lag_months=2)
    assert pd.isna(known.loc["2019-03-29", "EUR"])             # janvier ne devient connu que fin mars (retard de 2 mois) : rien avant
    assert known.loc["2019-04-15", "EUR"] == 2.0               # janvier connu ; février (9,0) pas encore
    assert known.loc["2019-04-30", "EUR"] == 9.0               # février devient connu fin avril
    assert known.loc["2019-05-31", "EUR"] == 2.0               # mars (2,0) est le dernier connu fin mai


def test_time_series_signal_is_the_sign_of_the_differential():
    diff = pd.DataFrame({"AAA": [1.0, -2.0, 0.0], "BBB": [np.nan, 1.0, -1.0]}, index=pd.date_range("2020-01-31", periods=3, freq="ME"))
    pos = fc.carry_signals(diff, "time_series")
    assert pos["AAA"].tolist() == [1.0, -1.0, 0.0] and pos["BBB"].tolist() == [0.0, 1.0, -1.0]


def test_cross_section_is_long_the_top_short_the_bottom_and_neutral():
    diff = pd.DataFrame([[4.0, 3.0, 2.0, 1.0, 0.0, -1.0, -2.0]], columns=list("ABCDEFG"), index=pd.DatetimeIndex(["2020-01-31"]))
    pos = fc.carry_signals(diff, "cross_section", n_tail=3)
    assert pos.iloc[0].to_dict() == {"A": 1.0, "B": 1.0, "C": 1.0, "D": 0.0, "E": -1.0, "F": -1.0, "G": -1.0}
    assert pos.sum(axis=1).iloc[0] == 0.0
    short = fc.carry_signals(diff.assign(F=np.nan, G=np.nan), "cross_section", n_tail=2)          # 5 devises connues : 2 longues, 2 courtes
    assert (short.iloc[0] == 1).sum() == 2 and (short.iloc[0] == -1).sum() == 2 and short.iloc[0][["F", "G"]].eq(0).all()
    with pytest.raises(ValueError):
        fc.carry_signals(diff, "autre")


def test_usd_per_currency_inverts_the_dollar_quoted_pairs():
    spot = pd.DataFrame({"EURUSD=X": [1.10], "USDJPY=X": [110.0]})
    usd = fc.usd_per_currency(spot)
    assert usd["EUR"].iloc[0] == pytest.approx(1.10) and usd["JPY"].iloc[0] == pytest.approx(1 / 110.0)


def test_with_flat_prices_the_monthly_return_is_the_carry_net_of_costs():
    rates = _rates(ALL_FLAT, start="2018-06-01", months=50)
    res = fc.backtest(_spot(flat=True), rates, "time_series", cost_bps=0.0, start="2019-06-01", end="2021-12-31")
    pos = res["positions"]
    expected = (pos * (rates.iloc[-1][list(PAIRS)] - rates.iloc[-1]["USD"]) / 100 / 12).sum(axis=1)
    assert res["net"].iloc[3:].to_numpy() == pytest.approx(expected.iloc[3:].to_numpy(), abs=1e-12)
    assert (res["spot_only"].abs() < 1e-12).all()                 # le change ne bouge pas : tout vient du portage
    # signes : EUR (-1 pt) , JPY (-0,5 pt) et CHF (-1,5 pt) sous le dollar donc vendues ; GBP à 0 pt d'écart (taux égal) à plat ; AUD, NZD, CAD achetées ; poids égaux entre les six devises à signal
    assert pos.iloc[5].to_dict() == pytest.approx({"EUR": -1 / 6, "GBP": 0.0, "AUD": 1 / 6, "NZD": 1 / 6, "JPY": -1 / 6, "CAD": 1 / 6, "CHF": -1 / 6}, abs=1e-9)


def test_costs_are_charged_on_the_turnover_only():
    rates = _rates(ALL_FLAT, start="2018-06-01", months=50)
    free = fc.backtest(_spot(flat=True), rates, "time_series", cost_bps=0.0, start="2019-06-01", end="2021-12-31")
    costly = fc.backtest(_spot(flat=True), rates, "time_series", cost_bps=20.0, start="2019-06-01", end="2021-12-31")
    gap = (free["net"] - costly["net"]).iloc[1:]
    assert gap.abs().max() < 1e-12                               # signaux constants : après l'ouverture, aucune rotation, donc aucun frais
    assert (free["net"] - costly["net"]).iloc[0] == pytest.approx(costly["turnover"].iloc[0] * 20e-4)


def test_decisions_never_read_later_rates_or_prices():
    rates, spot = _rates(ALL_FLAT, start="2018-06-01", months=50), _spot(seed=3)
    base = fc.backtest(spot, rates, "cross_section", start="2019-06-01", end="2021-12-31")
    later_rates, later_spot = rates.copy(), spot.copy()
    later_rates.loc["2021-01-01":] *= -3.0                       # tout ce qui est publié après fin 2020 change
    later_spot.loc["2021-03-01":] *= 2.0
    other = fc.backtest(later_spot, later_rates, "cross_section", start="2019-06-01", end="2021-12-31")
    cut = pd.Timestamp("2020-12-31")
    pd.testing.assert_frame_equal(base["positions"].loc[:cut], other["positions"].loc[:cut])


def test_stats_on_a_known_series():
    r = pd.Series([0.01, -0.005, 0.02, 0.0] * 6, index=pd.date_range("2020-01-31", periods=24, freq="ME"))
    s = fc.stats(r)
    assert s["n"] == 24 and s["sharpe"] == pytest.approx(r.mean() / r.std(ddof=1) * np.sqrt(12)) and s["max_drawdown"] <= 0
    assert fc.stats(r.iloc[:5]) == {"n": 5}
