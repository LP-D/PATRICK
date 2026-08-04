"""Phase 6.5 (P6.5) -- portes de qualité de données à l'ingestion
(`patrick/data/quality.py`). Unités sur chaque contrôle, puis intégration au
niveau `ingest()` (sources monkeypatchées au niveau `yfinance.download`/
`requests.get`, jamais `ingest()` lui-même -- pour que le vrai code
d'exclusion/persistance tourne, cf. même idiome que `test_audit_degradation.py`).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.config.schema import DataQualityConfig, ObjectiveConfig, UniverseConfig
from patrick.data import ingest as ingest_module
from patrick.data import quality
from patrick.data.sources import fred_source, yfinance_source
from patrick.data.store import DataStore
from patrick.tracking import db as trackdb


def _clean_series(n=1000, seed=0, price=100.0) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    prices = price * np.cumprod(1 + rng.normal(0, 0.015, n))
    return pd.Series(np.round(prices, 2), index=idx, name="clean")


# ---------------------------------------------------------------------------
# Unités par contrôle
# ---------------------------------------------------------------------------

def test_check_frozen_prices_passes_clean_series():
    s = _clean_series()
    assert quality.check_frozen_prices(s) is None


def test_check_frozen_prices_detects_run():
    s = _clean_series().copy()
    s.iloc[100:106] = 123.45  # 6 clôtures identiques consécutives
    issue = quality.check_frozen_prices(s)
    assert issue is not None
    assert issue.reason == "prix_figes"


def test_check_quote_gaps_passes_clean_series():
    s = _clean_series()
    assert quality.check_quote_gaps(s) is None


def test_check_quote_gaps_detects_gap():
    s = _clean_series().copy()
    s.iloc[200:225] = np.nan  # ~25 jours ouvrés manquants (> seuil 10)
    issue = quality.check_quote_gaps(s)
    assert issue is not None
    assert issue.reason == "trou_de_cotation"


def test_check_aberrant_returns_passes_clean_series():
    s = _clean_series(n=2000, seed=1)
    assert quality.check_aberrant_returns(s) is None


def test_check_aberrant_returns_detects_outlier():
    s = _clean_series(n=2000, seed=1).copy()
    s.iloc[1000] = s.iloc[999] * 0.10  # -90%, split non ajusté typique
    issue = quality.check_aberrant_returns(s)
    assert issue is not None
    assert issue.reason == "rendement_aberrant"


def test_check_stale_tail_detects_early_end():
    s = _clean_series(n=500)
    requested_end = s.index.max() + pd.Timedelta(days=60)  # bien après la dernière obs
    issue = quality.check_stale_tail(s, requested_end)
    assert issue is not None
    assert issue.reason == "fin_de_serie_precoce"


def test_check_stale_tail_passes_when_up_to_date():
    s = _clean_series(n=500)
    issue = quality.check_stale_tail(s, s.index.max())
    assert issue is None


def test_check_fred_missing_detects_none_and_empty():
    assert quality.check_fred_missing("NFCI", None) is not None
    assert quality.check_fred_missing("NFCI", pd.Series(dtype=float)) is not None
    assert quality.check_fred_missing("NFCI", pd.Series([1.0, 2.0])) is None


def test_check_coverage_detects_insufficient():
    idx = pd.bdate_range("2020-01-01", periods=100)
    s = pd.Series(1.0, index=idx[:50]).reindex(idx)  # 50% de couverture
    issue = quality.check_coverage(s, idx, min_coverage=0.85)
    assert issue is not None
    assert issue.reason == "couverture_insuffisante"


def test_thresholds_measured_not_arbitrary_frozen_and_aberrant():
    """Reproduit (à plus petite échelle, pour la vitesse) la mesure qui a fixé
    DEFAULT_MAX_FROZEN_RUN=4 et DEFAULT_MAX_ROBUST_Z=40 (cf. docstring
    `data/quality.py`) : sur des séries PROPRES, ces seuils ne doivent
    (quasiment) jamais se déclencher ; sur une corruption injectée réaliste
    (split non ajusté), ils doivent se déclencher nettement."""
    n_series, n_days = 60, 2000
    frozen_fires = 0
    aberrant_fires = 0
    for seed in range(n_series):
        rng = np.random.default_rng(1000 + seed)
        idx = pd.bdate_range("2015-01-01", periods=n_days)
        # Student-t(df=5), queues épaisses réalistes -- cf. justification module.
        t = rng.standard_t(df=5, size=n_days) / np.sqrt(5 / 3) * 0.015
        prices = pd.Series(np.round(100 * np.cumprod(1 + t), 2), index=idx)
        if quality.check_frozen_prices(prices) is not None:
            frozen_fires += 1
        if quality.check_aberrant_returns(prices) is not None:
            aberrant_fires += 1
    assert frozen_fires / n_series < 0.05, f"seuil prix figés trop agressif ({frozen_fires}/{n_series})"
    assert aberrant_fires / n_series < 0.05, f"seuil rendement aberrant trop agressif ({aberrant_fires}/{n_series})"

    corrupted = _clean_series(n=2000, seed=99).copy()
    corrupted.iloc[1000] = corrupted.iloc[999] * 0.5  # split 2:1 non ajusté
    assert quality.check_aberrant_returns(corrupted) is not None


# ---------------------------------------------------------------------------
# Intégration `ingest()` -- sources monkeypatchées, jamais `ingest()` lui-même
# ---------------------------------------------------------------------------

def _make_yf_fake(good_tickers, bad_ticker, n=800):
    idx = pd.bdate_range("2018-01-01", periods=n)

    def fake_download(tickers, start=None, auto_adjust=True, progress=False):
        is_batch = isinstance(tickers, list)
        syms = tickers if is_batch else [tickers]
        cols = {}
        for field in ("Open", "High", "Low", "Close"):
            for s in syms:
                rng = np.random.default_rng(abs(hash((field, s))) % (2**32))
                base = 100 + np.cumsum(rng.normal(0, 1, n))
                if s == bad_ticker and field == "Close":
                    base = base.copy()
                    base[400:410] = base[399]  # 10 clôtures figées -> exclue
                cols[(field, s)] = base
        df = pd.DataFrame(cols, index=idx)
        df.columns = pd.MultiIndex.from_tuples(df.columns)
        if not is_batch:
            flat = df.copy()
            flat.columns = [c[0] for c in df.columns]
            return flat
        return df

    return fake_download


def test_ingest_excludes_series_with_explicit_reason_and_persists(tmp_path, monkeypatch):
    # 4 tickers propres + 1 figé : 20% d'exclusion, sous le seuil de refus par
    # défaut (30%) -- isole le comportement "une série exclue, le reste continue"
    # du comportement "trop d'exclusions, refus total" (couvert séparément).
    goods = ["GOOD1", "GOOD2", "GOOD3", "GOOD4"]
    bad = "BAD_TICKER"
    monkeypatch.setattr(yfinance_source.yf, "download", _make_yf_fake(goods, bad))
    monkeypatch.delenv(fred_source.FRED_API_KEY_ENV, raising=False)

    objective = ObjectiveConfig(target_symbol="^TEST", target_source="yfinance", disable_session_lag=True)
    universe = UniverseConfig(yf_tickers=[*goods, bad], start_date="2018-01-01")
    store = DataStore(root=str(tmp_path / "store"))

    df = ingest_module.ingest(objective, universe, store=store, force=True)

    for g in goods:
        assert yfinance_source.clean_symbol(g) in df.columns
    assert yfinance_source.clean_symbol(bad) not in df.columns
    issues = df.attrs["quality_issues"]
    assert any(i["series"] == yfinance_source.clean_symbol(bad) and i["reason"] == "prix_figes" for i in issues)


def test_ingest_ignores_exclusion_fraction_when_history_is_old_enough(tmp_path, monkeypatch):
    bad1, bad2, bad3 = "BAD1", "BAD2", "BAD3"

    def fake_download_all_frozen(tickers, start=None, auto_adjust=True, progress=False):
        idx = pd.bdate_range("2000-01-03", periods=5000)
        is_batch = isinstance(tickers, list)
        syms = tickers if is_batch else [tickers]
        cols = {}
        for field in ("Open", "High", "Low", "Close"):
            for s in syms:
                cols[(field, s)] = np.full(len(idx), 50.0)
        df = pd.DataFrame(cols, index=idx)
        df.columns = pd.MultiIndex.from_tuples(df.columns)
        if not is_batch:
            flat = df.copy()
            flat.columns = [c[0] for c in df.columns]
            return flat
        return df

    monkeypatch.setattr(yfinance_source.yf, "download", fake_download_all_frozen)
    monkeypatch.delenv(fred_source.FRED_API_KEY_ENV, raising=False)

    objective = ObjectiveConfig(target_symbol="^TEST", target_source="yfinance", disable_session_lag=True)
    universe = UniverseConfig(yf_tickers=[bad1, bad2, bad3], start_date="2000-01-01")
    store = DataStore(root=str(tmp_path / "store"))

    df = ingest_module.ingest(objective, universe, store=store, force=True)
    assert len(df) > 0
    assert df.index.min() <= pd.Timestamp("2006-08-02")


def test_data_quality_disabled_restores_pre_p6_5_behavior(tmp_path, monkeypatch):
    good, bad = "GOOD_TICKER", "BAD_TICKER"
    monkeypatch.setattr(yfinance_source.yf, "download", _make_yf_fake([good], bad))
    monkeypatch.delenv(fred_source.FRED_API_KEY_ENV, raising=False)

    objective = ObjectiveConfig(target_symbol="^TEST", target_source="yfinance", disable_session_lag=True)
    universe = UniverseConfig(yf_tickers=[good, bad], start_date="2018-01-01")
    store = DataStore(root=str(tmp_path / "store"))

    df = ingest_module.ingest(objective, universe, store=store, force=True,
                               data_quality=DataQualityConfig(enabled=False))

    # data_quality désactivé : la couverture (déjà en place avant P6.5) reste
    # active, mais les 4 contrôles P6.5 (dont prix figés) ne s'appliquent plus.
    assert yfinance_source.clean_symbol(bad) in df.columns
    assert df.attrs["quality_issues"] == []


def test_quality_issues_persisted_and_readable_via_run_pipeline(tmp_path, monkeypatch):
    """Vérifie le câblage complet ingest -> engine -> SQLite (sans dépendre du
    réseau) : un `ingest` monkeypatché POSE lui-même `.attrs["quality_issues"]`
    (ce que fait le vrai `ingest()`), et on vérifie que `run_pipeline` les
    persiste et que `trackdb.list_data_quality_issues` les relit."""
    from patrick.config.schema import RunConfig
    from patrick.pipeline import engine as engine_module

    def fake_ingest(objective, universe, store=None, force=False, data_quality=None):
        rng = np.random.default_rng(0)
        idx = pd.bdate_range("2015-01-01", periods=500)
        df = pd.DataFrame({"IDX_TEST": 100 + np.cumsum(rng.normal(0, 0.5, 500))}, index=idx)
        df.attrs["snapshot_id"] = "snap_test_quality_001"
        df.attrs["data_hash"] = "hash001"
        df.attrs["n_tickers"] = 0
        df.attrs["n_fred_series"] = 0
        df.attrs["fred_source"] = "scrape"
        df.attrs["quality_issues"] = [
            {"series": "IDX_BAD", "reason": "prix_figes", "detail": "5 clôtures identiques"},
        ]
        return df

    monkeypatch.setattr(engine_module, "ingest", fake_ingest)

    config = RunConfig.model_validate({
        "name": "quality_persist_test",
        "objective": {"target_symbol": "^TEST", "horizons": [5], "regimes": ["GLOBAL"]},
        "features": {"families": ["technical"]},
        "validation": {"n_wf_folds": 2, "min_train_frac": 0.5},
        "selection": {"method": "shap", "n_features_grid": [3]},
        "sampler": {"candidates": ["SMOTE"]},
        "models": {"algos": ["RandomForest"]},
        "tuning": {"enabled": False},
        "output": {"dir": str(tmp_path / "runs"), "seed": 42},
    })
    db_path = str(tmp_path / "patrick.db")
    engine_module.run_pipeline(config, store=DataStore(root=str(tmp_path / "store")), db_path=db_path)

    conn = trackdb.connect(db_path)
    issues = trackdb.list_data_quality_issues(conn, "snap_test_quality_001")
    conn.close()
    assert issues == [{"series": "IDX_BAD", "reason": "prix_figes", "detail": "5 clôtures identiques"}]
