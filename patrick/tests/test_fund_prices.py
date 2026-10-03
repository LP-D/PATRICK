"""Cotations des stratégies : persistance définitive, hors ligne, pence, change, taux de référence."""
from __future__ import annotations

import datetime as dt

import fund_support as fs
import pandas as pd
import pytest

from patrick.data.sources import fred_source
from patrick.fund import prices


@pytest.fixture(autouse=True)
def _quotes(monkeypatch):
    fs.install(monkeypatch)


def test_pence_quotes_are_converted_to_pounds(conn):
    res = prices.ensure_bars(conn, "VOD.L")
    assert res.currency == "GBP" and res.df["close"].iloc[0] == pytest.approx(0.70)
    assert prices.iso_currency("GBp") == ("GBP", 0.01) and prices.iso_currency("USD") == ("USD", 1.0)
    assert prices.iso_currency(None) == (None, 1.0)


def test_prices_are_persisted_and_served_offline_after_expiry_of_the_cache(conn, monkeypatch):
    prices.ensure_bars(conn, "MC.PA")
    monkeypatch.setattr(prices, "download_bars", lambda s, start=None: (None, None))
    later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=7)
    res = prices.ensure_bars(conn, "MC.PA", now=later)
    assert res.status == "stored" and len(res.df) == len(fs.IDX) and res.currency == "EUR"
    assert prices.ensure_bars(conn, "UNKNOWN").status == "missing"


def test_a_fresh_cache_is_not_downloaded_again_and_a_stale_one_refreshes_incrementally(conn):
    prices.ensure_bars(conn, "MC.PA")
    prices.ensure_bars(conn, "MC.PA")
    assert fs.CALLS == [("MC.PA", None)]
    later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=7)
    prices.ensure_bars(conn, "MC.PA", now=later)
    assert fs.CALLS[1][0] == "MC.PA" and fs.CALLS[1][1] == "2026-09-25"     # dernier jour stocké - 7 jours


def test_upsert_overwrites_revised_rows_without_duplicating(conn):
    df, ccy = fs.fake_download("MC.PA")
    prices.save_bars(conn, "MC.PA", df, ccy)
    revised = df.copy()
    revised.iloc[-1, revised.columns.get_loc("close")] = 1.0
    prices.save_bars(conn, "MC.PA", revised, ccy)
    stored = prices.load_bars(conn, "MC.PA")
    assert len(stored) == len(df) and stored["close"].iloc[-1] == 1.0


def test_fx_series_is_the_inverse_of_the_yahoo_pair(conn):
    s = prices.fx_series(conn, "EUR", "USD")
    assert s.iloc[0] == pytest.approx(1 / 1.10) and prices.fx_symbol("EUR", "USD") == "EURUSD=X"
    assert prices.fx_series(conn, "EUR", "SEK") is None


def test_build_market_collects_bars_fx_rates_and_notes(conn):
    orders = [
        {"symbol": "AAPL", "currency": "USD", "instrument_kind": "equity"},
        {"symbol": "^GSPC", "currency": "USD", "instrument_kind": "cfd"},
        {"symbol": "MC.PA", "currency": "EUR", "instrument_kind": "equity"},
        {"symbol": "GHOST", "currency": "EUR", "instrument_kind": "equity"},
        {"symbol": "TTE.PA", "currency": "SEK", "instrument_kind": "equity"},   # devise sans paire de change
    ]
    market, notes = prices.build_market(conn, orders, "EUR")
    assert set(market.bars) == {"AAPL", "^GSPC", "MC.PA", "TTE.PA"} and set(market.fx) == {"USD"}
    assert market.ref_rates == {"USD": 0.04}
    assert any("GHOST" in n and "aucune cotation" in n for n in notes)
    assert any("change EUR/SEK indisponible" in n for n in notes)
    assert any("taux de référence USD" in n for n in notes)


def test_stored_prices_are_flagged_as_offline_in_the_notes(conn, monkeypatch):
    prices.ensure_bars(conn, "MC.PA")
    conn.execute("UPDATE fund_price_meta SET refreshed_at = '2020-01-01 00:00:00'")
    monkeypatch.setattr(prices, "download_bars", lambda s, start=None: (None, None))
    _, notes = prices.build_market(conn, [{"symbol": "MC.PA", "currency": "EUR", "instrument_kind": "equity"}])
    assert any("hors ligne" in n for n in notes)


def test_reference_rates_use_fred_when_the_key_is_set(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "key")
    seen = []
    monkeypatch.setattr(fred_source, "download_series",
                        lambda name, sid, start: seen.append(sid) or pd.Series([4.5, 4.3]))
    rates, notes = prices.reference_rates({"USD", "JPY"})
    assert rates["USD"] == pytest.approx(0.043) and seen == ["SOFR"]
    assert rates["JPY"] == 0.005 and len(notes) == 1 and "JPY" in notes[0]


def test_reference_rates_fall_back_to_constants_without_the_key():
    rates, notes = prices.reference_rates({"EUR", "AUD"})
    assert rates == {"EUR": 0.02, "AUD": 0.03} and len(notes) == 2


def test_a_failed_download_is_not_retried_for_fifteen_minutes(conn, monkeypatch):
    prices.ensure_bars(conn, "MC.PA")
    calls = []

    def offline(symbol, start=None):
        calls.append(symbol)
        return None, None
    monkeypatch.setattr(prices, "download_bars", offline)
    t0 = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=7)
    assert prices.ensure_bars(conn, "MC.PA", now=t0).status == "stored"
    prices.ensure_bars(conn, "MC.PA", now=t0 + dt.timedelta(minutes=5))
    assert calls == ["MC.PA"]
    prices.ensure_bars(conn, "MC.PA", now=t0 + dt.timedelta(minutes=20))
    assert calls == ["MC.PA", "MC.PA"]
    prices.ensure_bars(conn, "GHOST", now=t0)
    prices.ensure_bars(conn, "GHOST", now=t0 + dt.timedelta(minutes=5))
    assert calls == ["MC.PA", "MC.PA", "GHOST"]


def test_reference_rates_are_cached_between_calls_even_when_fred_fails(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "key")
    seen = []
    monkeypatch.setattr(fred_source, "download_series", lambda name, sid, start: seen.append(sid) or pd.Series([4.5]))
    prices.reference_rates({"USD"})
    prices.reference_rates({"USD"})
    assert seen == ["SOFR"]
    prices._RATE_CACHE.clear()
    monkeypatch.setattr(fred_source, "download_series", lambda name, sid, start: seen.append("fail") or None)
    prices.reference_rates({"USD"})
    rates, notes = prices.reference_rates({"USD"})
    assert seen == ["SOFR", "fail"] and rates["USD"] == 0.04 and len(notes) == 1


def test_a_new_split_triggers_a_full_refetch_so_that_history_stays_consistent(conn, monkeypatch):
    full = fs.fake_download("MC.PA")[0]
    first = full[full.index <= "2026-01-09"]
    adjusted = full[full.index <= "2026-01-16"].copy()
    adjusted[["open", "high", "low", "close"]] = adjusted[["open", "high", "low", "close"]] / 10.0   # tout l'historique ajusté
    adjusted.loc["2026-01-13", "split"] = 10.0
    calls = []

    def downloader(symbol, start=None):
        calls.append(start)
        if len(calls) == 1:
            return first, "EUR"
        return (adjusted[adjusted.index >= start], "EUR") if start else (adjusted, "EUR")
    monkeypatch.setattr(prices, "download_bars", downloader)
    prices.ensure_bars(conn, "MC.PA")
    later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=7)
    prices.ensure_bars(conn, "MC.PA", now=later)
    assert calls == [None, "2026-01-02", None]
    stored = prices.load_bars(conn, "MC.PA")
    assert len(stored) == len(adjusted) and stored["split"].sum() == 10.0
    assert stored["close"].iloc[0] == pytest.approx(adjusted["close"].iloc[0])
    prices.ensure_bars(conn, "MC.PA", now=later + dt.timedelta(hours=7))
    assert len(calls) == 4 and calls[3] is not None            # déjà connu : pas de nouvel historique complet
