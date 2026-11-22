"""Cible alpha, jalon 2b : le snapshot d'une cible alpha est séparé de celui de la cible brute (sinon un cache
`raw_<cible>` sans benchmark serait servi à un run alpha), et le benchmark y est décalé comme le reste de l'univers."""
from __future__ import annotations

import pandas as pd
import pytest
from test_data_quality import _OLD_ENOUGH_START, _make_yf_fake

from patrick.config.schema import ObjectiveConfig, RunConfig
from patrick.data import ingest as ingest_module
from patrick.data.sources import fred_source, yfinance_source
from patrick.data.store import DataStore


def _alpha_config(target="MC.PA", benchmark="^GSPC", **objective) -> RunConfig:
    return RunConfig.model_validate({
        "objective": {"target_symbol": target, "horizons": [5], "target_kind": "alpha", "benchmark": benchmark,
                      **objective},
        "universe": {"yf_tickers": ["GOOD1", "GOOD2"], "start_date": _OLD_ENOUGH_START}})


def _patch(monkeypatch):
    monkeypatch.setattr(yfinance_source.yf, "download", _make_yf_fake(["GOOD1", "GOOD2"], "NONE_BAD"))
    monkeypatch.delenv(fred_source.FRED_API_KEY_ENV, raising=False)


def test_cache_key_is_unchanged_for_raw_and_carries_the_benchmark_for_alpha():
    assert ObjectiveConfig(target_symbol="AAPL").raw_cache_key() == "raw_AAPL"
    assert _alpha_config("AAPL", "URTH").objective.raw_cache_key() == "raw_AAPL__alpha_URTH"
    assert _alpha_config("MC.PA", "^GSPC").objective.raw_cache_key() != _alpha_config("MC.PA", "^FCHI").objective.raw_cache_key()


def test_an_alpha_ingest_gets_its_own_snapshot_with_the_benchmark_column(tmp_path, monkeypatch):
    _patch(monkeypatch)
    cfg = _alpha_config()
    store = DataStore(root=str(tmp_path / "store"))

    df = ingest_module.ingest(cfg.objective, cfg.universe, store=store, force=True)

    assert yfinance_source.clean_symbol("^GSPC") in df.columns
    assert store.list_snapshots("raw_MC.PA__alpha_^GSPC") and not store.list_snapshots("raw_MC.PA")


def test_a_raw_ingest_is_never_served_the_alpha_snapshot_and_vice_versa(tmp_path, monkeypatch):
    _patch(monkeypatch)
    cfg = _alpha_config()
    store = DataStore(root=str(tmp_path / "store"))
    ingest_module.ingest(cfg.objective, cfg.universe, store=store, force=True)

    raw_objective = ObjectiveConfig(target_symbol="MC.PA", target_source="yfinance")
    raw = ingest_module.ingest(raw_objective, RunConfig.model_validate(
        {"objective": {"target_symbol": "MC.PA", "horizons": [5]},
         "universe": {"yf_tickers": ["GOOD1", "GOOD2"], "start_date": _OLD_ENOUGH_START}}).universe,
        store=store, force=False)

    assert yfinance_source.clean_symbol("^GSPC") not in raw.columns           # pas le snapshot alpha
    assert store.list_snapshots("raw_MC.PA")                                    # le sien, créé à cette occasion


def test_the_benchmark_is_shifted_one_bar_when_it_closes_after_the_target(tmp_path, monkeypatch):
    _patch(monkeypatch)
    lagged = _alpha_config(disable_session_lag=False)                          # ^GSPC (20 h) après MC.PA (16 h 30)
    plain = _alpha_config(disable_session_lag=True)
    a = ingest_module.ingest(lagged.objective, lagged.universe, store=DataStore(root=str(tmp_path / "s1")), force=True)
    b = ingest_module.ingest(plain.objective, plain.universe, store=DataStore(root=str(tmp_path / "s2")), force=True)
    col = yfinance_source.clean_symbol("^GSPC")

    pd.testing.assert_series_equal(a[col].iloc[2:], b[col].shift(1).iloc[2:], check_names=False, check_freq=False)
    assert not a[col].equals(b[col])                                            # le décalage a bien eu lieu


def test_replay_loads_the_alpha_snapshot_key(tmp_path, monkeypatch):
    _patch(monkeypatch)
    cfg = _alpha_config()
    store = DataStore(root=str(tmp_path / "store"))
    first = ingest_module.ingest(cfg.objective, cfg.universe, store=store, force=True)
    snapshot_id = first.attrs["snapshot_id"]

    replay = ingest_module.load_snapshot(cfg.objective, cfg.universe, snapshot_id, store=store)

    assert list(replay.columns) == list(first.columns)


def test_a_benchmark_dropped_by_the_quality_gate_fails_with_a_clear_message(tmp_path, monkeypatch):
    """Le contrôle qualité peut écarter le benchmark : message explicite, pas une KeyError plus loin."""
    from patrick.pipeline import engine as engine_module
    cfg = _alpha_config()
    frame = pd.DataFrame({"MC.PA": range(10), "GOOD1": range(10)})          # pas de colonne benchmark
    monkeypatch.setattr(engine_module, "ingest", lambda *a, **k: frame)

    with pytest.raises(ValueError, match="benchmark .* écarté par le contrôle qualité"):
        engine_module.run_pipeline(cfg, store=DataStore(root=str(tmp_path / "store")), db_path=str(tmp_path / "p.db"))
