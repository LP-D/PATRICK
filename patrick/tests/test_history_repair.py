"""Une série dont le fournisseur tronque l'historique (Yahoo, `OJ=F`, 2026-11-12) est reprise depuis le magasin : les modèles qui la
lisent continuent de prédire. Une série morte depuis trop longtemps, ou écartée par une porte de qualité, reste exclue."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from conftest import OLD_ENOUGH_START

from patrick.config.schema import ObjectiveConfig, UniverseConfig
from patrick.data import history_repair
from patrick.data import ingest as ingest_module
from patrick.data.sources import fred_source, yfinance_source
from patrick.data.store import DataStore

N = 800
GOODS = ["GOOD1", "GOOD2", "GOOD3"]
LOST = "LOST=F"


class Provider:
    """Faux Yahoo : `days` séances servies ; `LOST=F` ne garde que ses `keep_last` dernières barres une fois tronquée."""

    def __init__(self):
        self.days, self.keep_last = N, None

    def download(self, tickers, start=None, auto_adjust=True, progress=False):
        idx = pd.bdate_range(OLD_ENOUGH_START, periods=self.days)
        syms = tickers if isinstance(tickers, list) else [tickers]
        cols = {}
        for field in ("Open", "High", "Low", "Close"):
            for s in syms:
                rng = np.random.default_rng(sum(map(ord, field + s)))
                values = 100 + np.cumsum(rng.normal(0, 1, N + 50))[: self.days]
                if s == LOST and self.keep_last is not None:
                    values = np.where(np.arange(self.days) >= self.days - self.keep_last, values, np.nan)
                cols[(field, s)] = values
        df = pd.DataFrame(cols, index=idx)
        df.columns = pd.MultiIndex.from_tuples(df.columns)
        if not isinstance(tickers, list):
            df.columns = [c[0] for c in df.columns]
            df = df.dropna(how="all")
        return df


@pytest.fixture
def world(tmp_path, monkeypatch):
    provider = Provider()
    monkeypatch.setattr(yfinance_source.yf, "download", provider.download)
    monkeypatch.delenv(fred_source.FRED_API_KEY_ENV, raising=False)
    yfinance_source._download_one_cached.cache_clear()
    # pas de cache disque de 7 jours entre deux ingestions du test : chacune est « un autre jour » (cible comprise)
    monkeypatch.setattr(yfinance_source.LocalCache, "load_dataframe", lambda *args, **kwargs: None)
    objective =ObjectiveConfig(target_symbol="^TEST", target_source="yfinance", disable_session_lag=True)
    universe = UniverseConfig(yf_tickers=[*GOODS, LOST], start_date=OLD_ENOUGH_START)
    store = DataStore(root=str(tmp_path / "store"))

    def ingest():
        yfinance_source._download_one_cached.cache_clear()
        return ingest_module.ingest(objective, universe, store=store, force=True)
    return provider, store, ingest


def test_a_series_truncated_by_the_provider_keeps_its_history_from_the_data_lake(world):
    provider, store, ingest = world
    before = ingest()
    assert before.attrs["history_repaired"] == [] and before[LOST].notna().all()

    provider.days, provider.keep_last = N + 2, 1               # deux séances plus tard, le fournisseur ne sert plus que la dernière barre
    after = ingest()

    assert after.attrs["history_repaired"] == [LOST] and LOST in after.columns
    assert not any(i["series"] == LOST for i in after.attrs["quality_issues"])
    pd.testing.assert_series_equal(after[LOST].iloc[:N], before[LOST], check_freq=False)     # l'historique d'avant, intact
    fresh = provider.download(LOST)["Close"]
    assert after[LOST].iloc[-1] == fresh.iloc[-1]                                           # la barre du jour est la vraie
    assert after[LOST].iloc[-2] == before[LOST].iloc[-1]                                    # le jour manquant reporte la dernière valeur
    assert store.series_observation(LOST)["date_max"] == str(after.index[-1].date())

    provider.days, provider.keep_last = N + 3, 2               # le lendemain : la reprise repart de l'instantané déjà réparé
    later = ingest()
    assert later.attrs["history_repaired"] == [LOST] and later[LOST].iloc[-1] == provider.download(LOST)["Close"].iloc[-1]
    pd.testing.assert_series_equal(later[LOST].iloc[: N + 2], after[LOST], check_freq=False)


def test_a_series_dead_for_too_long_stays_excluded(world):
    provider, _, ingest = world
    ingest()

    provider.days, provider.keep_last = N + 15, 0              # trois semaines sans une seule barre : ce n'est plus une panne passagère
    after = ingest()

    assert LOST not in after.columns and after.attrs["history_repaired"] == []
    assert any(i["series"] == LOST for i in after.attrs["quality_issues"])


def test_a_short_outage_carries_the_last_value_until_the_limit(world):
    provider, _, ingest = world
    before = ingest()

    provider.days, provider.keep_last = N + 3, 0               # trois séances sans barre : la dernière valeur connue est reportée
    after = ingest()

    assert after.attrs["history_repaired"] == [LOST] and (after[LOST].iloc[-3:] == before[LOST].iloc[-1]).all()


def test_a_series_never_seen_in_the_data_lake_is_not_invented(world):
    provider, _, ingest = world
    provider.keep_last = 1                                     # tronquée dès la première ingestion : aucun instantané ne la contient

    df = ingest()

    assert LOST not in df.columns and df.attrs["history_repaired"] == []


class _Store:
    def __init__(self, tmp_path, column: pd.Series, last_real: str | None, pit: str = "v"):
        self.path = str(tmp_path / "snap.parquet")
        column.to_frame().to_parquet(self.path)
        self.last_real, self.pit = last_real, pit

    def list_snapshots(self, key):
        return [{"path": "absent.parquet", "pit_version": self.pit}, {"path": self.path, "pit_version": self.pit}]

    def series_observation(self, symbol):
        return {"date_max": self.last_real} if self.last_real else None


def _restore(store, fresh: pd.Series, *, lagged=False, pit="v", end="2026-01-09"):
    return history_repair.restore(store, "raw_x", pit, {"S": "S=F"}, {"S": fresh}, {"S"} if lagged else set(), pd.Timestamp(end))


def test_restore_applies_the_session_lag_to_the_fresh_bars_and_skips_unreadable_snapshots(tmp_path):
    stored = pd.Series([1.0, 2.0, 3.0], index=pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07"]), name="S")
    fresh = pd.Series([30.0, 40.0, 50.0], index=pd.to_datetime(["2026-01-07", "2026-01-08", "2026-01-09"]), name="S")
    store = _Store(tmp_path, stored, "2026-01-07")

    plain, observed = _restore(store, fresh)
    shifted, _ = _restore(store, fresh, lagged=True)

    assert plain["S"].tolist() == [1.0, 2.0, 3.0, 40.0, 50.0] and observed == {"S=F": "2026-01-09"}
    assert shifted["S"].tolist() == [1.0, 2.0, 3.0, 30.0, 40.0]              # décalées d'une barre, comme l'historique repris


def test_restore_refuses_another_point_in_time_rule_an_unknown_last_observation_and_a_long_gap(tmp_path):
    stored = pd.Series([1.0, 2.0], index=pd.to_datetime(["2026-01-05", "2026-01-06"]), name="S")
    fresh = pd.Series([9.0], index=pd.to_datetime(["2026-01-09"]), name="S")

    assert _restore(_Store(tmp_path, stored, "2026-01-06"), fresh, pit="autre") == ({}, {})
    assert _restore(_Store(tmp_path, stored, None), fresh) == ({}, {})
    assert _restore(_Store(tmp_path, stored, "2026-01-06"), fresh.rename(index={fresh.index[0]: pd.Timestamp("2026-01-30")}),
                    end="2026-01-30") == ({}, {})
    assert "S" in _restore(_Store(tmp_path, stored, "2026-01-06"), fresh)[0]
