"""La cible d'une ingestion forcée est retéléchargée (plus de cache de 7 jours), et une série d'entrée perdue s'annonce le jour même."""
from __future__ import annotations

import pandas as pd

from patrick.data.sources import yfinance_source
from patrick.tracking import home as trackhome
from patrick.tracking import relaunch_stats


class Provider:
    def __init__(self):
        self.days, self.calls, self.down = 100, 0, False

    def download(self, tickers, start=None, auto_adjust=True, progress=False):
        self.calls += 1
        if self.down:
            raise RuntimeError("fournisseur en panne")
        idx = pd.bdate_range("2025-01-01", periods=self.days)
        return pd.DataFrame({"Close": range(self.days)}, index=idx, dtype=float)


def _provider(monkeypatch) -> Provider:
    provider = Provider()
    monkeypatch.setattr(yfinance_source.yf, "download", provider.download)
    yfinance_source._download_one_cached.cache_clear()
    return provider


def test_a_cached_series_is_reused_unless_a_fresh_one_is_asked(monkeypatch):
    provider = _provider(monkeypatch)
    first = yfinance_source.download_one("AAA", "2025-01-01")
    provider.days = 103                                          # trois séances plus tard

    assert len(yfinance_source.download_one("AAA", "2025-01-01")) == len(first) == 100 and provider.calls == 1
    assert len(yfinance_source.download_one("AAA", "2025-01-01", fresh=True)) == 103 and provider.calls == 2
    assert len(yfinance_source.download_one("AAA", "2025-01-01")) == 103 and provider.calls == 2      # le cache disque a été réécrit


def test_a_forced_target_download_sees_the_bar_of_the_day_and_survives_an_outage(monkeypatch):
    provider = _provider(monkeypatch)
    yfinance_source.download_target("^TEST", "2025-01-01")
    provider.days = 101

    assert len(yfinance_source.download_target("^TEST", "2025-01-01")) == 100            # non forcé : le cache, comme avant
    assert len(yfinance_source.download_target("^TEST", "2025-01-01", fresh=True)) == 101
    provider.down = True
    assert len(yfinance_source.download_target("^TEST", "2025-01-01", fresh=True)) == 101     # panne : la copie en cache sert de secours


def _fail(conn, run_id: str, columns: list[str]) -> None:
    relaunch_stats.record_live_failure(conn, run_id, f"Training pool columns missing from the fresh data: {columns} -- the config may have changed")


def test_lost_series_are_counted_per_model_from_the_first_day(conn):
    _fail(conn, "r1", ["OJ=F_egarch_vol", "OJ=F_ret_5d"])
    _fail(conn, "r2", ["OJ=F_vol_10d"])
    _fail(conn, "r3", ["USD_CHF_vol_10d", "T10Y3M_Spread_ret_5d"])
    relaunch_stats.record_live_failure(conn, "r4", "HTTPSConnectionPool: Max retries exceeded")      # autre panne : pas une série perdue

    assert relaunch_stats.lost_series(conn) == [{"series": "OJ=F", "n_models": 2}, {"series": "T10Y3M_Spread", "n_models": 1},
                                                {"series": "USD_CHF", "n_models": 1}]
    conn.execute("UPDATE live_failure SET last_at = datetime('now', '-5 days')")
    conn.commit()
    assert relaunch_stats.lost_series(conn) == []                                          # réglé depuis : plus d'alerte


def test_the_home_page_lists_the_lost_series_among_what_needs_action(conn):
    assert [i["key"] for i in trackhome.action_items(conn, 0, 0)] == []
    _fail(conn, "r1", ["OJ=F_egarch_vol"])
    _fail(conn, "r2", ["OJ=F_vol_10d"])

    (item,) = trackhome.action_items(conn, 0, 0)

    assert (item["key"], item["n"], item["level"], item["series"]) == ("inputs_lost", 2, "error", "OJ=F (2)")
    from patrick.webapp.i18n import STRINGS
    assert "{s}" in STRINGS["hm_action_inputs_lost"]["fr"] and "{s}" in STRINGS["hm_action_inputs_lost"]["en"]
