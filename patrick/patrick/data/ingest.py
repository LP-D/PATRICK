"""Ingestion orchestration: target + feature universe (yfinance + FRED),
aligned on a common index, cached in the local data lake.
"""
from __future__ import annotations

import os
import time

import pandas as pd

from patrick.cache_manager import LocalCache
from patrick.config.schema import DataQualityConfig, ObjectiveConfig, UniverseConfig
from patrick.data import quality as quality_module
from patrick.data.session_calendar import session_lag_days
from patrick.data.sources import fred_source, yfinance_source
from patrick.data.sources.fred_source import FRED_API_KEY_ENV
from patrick.data.store import DataStore


def _apply_session_lag(yf_df: pd.DataFrame, tickers: list[str], objective: ObjectiveConfig) -> pd.DataFrame:
    """Shifts by one bar the columns whose asset class closes after the
    target's (Phase 0.4 — see `data/session_calendar.py`): a "same calendar
    date" join implicitly treats as simultaneous market closes that aren't
    (e.g. a US close used "for the day" for a target that already closed
    earlier the same UTC day).

    `objective.disable_session_lag` (correction report, C7): toggle added
    only for `patrick audit degradation`, never used in production (default
    False -- fix always applied)."""
    if objective.disable_session_lag:
        return yf_df
    reverse = {yfinance_source.clean_symbol(t): t for t in tickers}
    out = yf_df.copy()
    lagged = []
    for col in out.columns:
        original_symbol = reverse.get(col, col)
        if session_lag_days(original_symbol, "yfinance",
                             objective.target_symbol, objective.target_source):
            out[col] = out[col].shift(1)
            lagged.append(original_symbol)
    if lagged:
        print(f"  [ALIGNMENT] {len(lagged)} tickers shifted by one bar "
              f"(close later than the target's): {', '.join(lagged[:8])}"
              f"{'...' if len(lagged) > 8 else ''}")
    return out


def _attach_snapshot_context(df: pd.DataFrame, universe: UniverseConfig,
                              quality_issues: list | None = None) -> None:
    """Context metadata (Phase 1.6) carried via `DataFrame.attrs` — read by
    `pipeline/engine.py` to populate the `snapshot` table without changing
    `ingest()`'s signature (which stays "returns a DataFrame", which every
    existing test already monkeypatches).

    `quality_issues` (Phase 6.5, P6.5): `None` on the cache-hit path (the
    exclusions happened during the original fetch, not replayed here --
    same accepted limitation as `n_tickers`/`fred_source`, recomputed on
    every call rather than persisted with the data itself)."""
    df.attrs["n_tickers"] = len(universe.yf_tickers)
    df.attrs["n_fred_series"] = len(universe.fred_series)
    df.attrs["fred_source"] = "api" if os.environ.get(FRED_API_KEY_ENV) else "scrape"
    df.attrs["quality_issues"] = [i.to_dict() for i in quality_issues] if quality_issues is not None else []


def _run_extra_quality_checks(df_cols: pd.DataFrame, requested_end: pd.Timestamp,
                               dq: DataQualityConfig, issues: list, *, prefilled: bool) -> list[str]:
    """P6.5 checks BEYOND coverage (already handled by `download_universe`/
    `download_fred_universe` themselves, see their `issues` parameter).

    `prefilled`: `download_universe` already does an internal `.ffill()`
    before returning the retained columns (coverage) -- real quoting gaps
    are therefore already filled (NaNs gone) by the time this module sees
    them; `check_quote_gaps`/`check_stale_tail` would be no-ops there (no
    more NaN to detect), BUT a real prolonged interruption shows up there as
    a frozen close (repeated ffilled value), already covered by
    `check_frozen_prices` -- an accepted convergence, not a gap in the
    guarantee. FRED series (`prefilled=False`) are not pre-filled here: all
    four checks apply as-is."""
    to_drop = []
    for col in df_cols.columns:
        s = df_cols[col]
        checks = (
            (quality_module.check_frozen_prices, {"max_run": dq.max_frozen_run}),
            (quality_module.check_aberrant_returns, {"max_robust_z": dq.max_robust_z}),
        ) if prefilled else (
            (quality_module.check_frozen_prices, {"max_run": dq.max_frozen_run}),
            (quality_module.check_aberrant_returns, {"max_robust_z": dq.max_robust_z}),
            (quality_module.check_quote_gaps, {"max_gap_bdays": dq.max_gap_bdays}),
            (quality_module.check_stale_tail, {"requested_end": requested_end, "max_gap_bdays": dq.max_gap_bdays}),
        )
        issue = None
        for check, kwargs in checks:
            issue = check(s, **kwargs)
            if issue is not None:
                break
        if issue is not None:
            issues.append(issue)
            to_drop.append(col)
    return to_drop


def ingest(objective: ObjectiveConfig, universe: UniverseConfig,
           store: DataStore | None = None, force: bool = False,
           data_quality: DataQualityConfig | None = None) -> pd.DataFrame:
    """`cache_key` only depends on `target_symbol`, not on `universe.
    vintage_realtime_date`/`objective.disable_session_lag` (correction
    report, C7): an existing cache can therefore mask a change to these two
    toggles. Callers that vary them for the same `target_symbol` (e.g.
    `patrick audit degradation`) MUST pass `force=True`.

    `data_quality` (Phase 6.5, P6.5): `None` -> `DataQualityConfig()` (gates
    active by default, never a silently disabled default)."""
    dq = data_quality if data_quality is not None else DataQualityConfig()
    store = store or DataStore()
    cache_key = f"raw_{objective.target_symbol}"
    local_cache = LocalCache()
    cached_local = local_cache.load_dataframe(f"{cache_key}_local", max_age_days=30)
    if not force and store.exists(cache_key):
        df = store.load(cache_key)
        _attach_snapshot_context(df, universe)
        print(f"[CACHE] {cache_key}: {df.shape} already cached (force=True to refresh).")
        return df
    if not force and cached_local is not None:
        df = cached_local.copy()
        _attach_snapshot_context(df, universe)
        print(f"[CACHE_LOCAL] {cache_key}: {df.shape} reused from local cache (missing rows only).")
        return df

    t0 = time.time()
    if objective.target_source == "yfinance":
        target = yfinance_source.download_target(objective.target_symbol, universe.start_date)
    else:
        target = fred_source.download_series(objective.target_symbol, objective.target_symbol,
                                               universe.start_date)
        if target is None:
            raise RuntimeError(f"Could not fetch FRED target '{objective.target_symbol}'.")

    df = target.to_frame()
    issues: list = []
    n_requested = len(universe.yf_tickers) + len(universe.fred_series)
    requested_end = pd.Timestamp(df.index.max()) if len(df) else pd.Timestamp.today()

    if universe.yf_tickers:
        yf_df = yfinance_source.download_universe(
            universe.yf_tickers, universe.start_date, universe.yf_coverage, t0=t0,
            issues=issues if dq.enabled else None)
        yf_df = _apply_session_lag(yf_df, universe.yf_tickers, objective)
        if dq.enabled and len(yf_df.columns):
            # `download_universe` already ffilled internally -- `check_quote_gaps`/
            # `check_stale_tail` would be no-ops there, see `prefilled` docstring.
            to_drop = _run_extra_quality_checks(yf_df, requested_end, dq, issues, prefilled=True)
            yf_df = yf_df.drop(columns=to_drop)
        df = df.join(yf_df, how="outer")

    if universe.fred_series:
        fred_df = fred_source.download_fred_universe(
            universe.fred_series, universe.start_date, realtime_date=universe.vintage_realtime_date,
            issues=issues if dq.enabled else None)
        if dq.enabled and len(fred_df.columns):
            # FRED series not pre-filled at this stage: all 4 checks apply.
            to_drop = _run_extra_quality_checks(fred_df, requested_end, dq, issues, prefilled=False)
            fred_df = fred_df.drop(columns=to_drop)
        if len(fred_df):
            fred_df = fred_df.reindex(df.index, method="ffill")
            df = pd.concat([df, fred_df], axis=1)

    if dq.enabled and n_requested > 0:
        exclusion_frac = len(issues) / n_requested
        if issues:
            print(f"  [QUALITY] {len(issues)}/{n_requested} series excluded from the universe "
                  f"({exclusion_frac:.0%}):")
            for i in issues:
                print(f"    - {i.series}: {i.reason} -- {i.detail}")

    # Patrick's local business rule: no longer requiring a rejection threshold on
    # the percentage of excluded universe. The only real condition to start is
    # having sufficiently old historical data (>= 20 years), without blocking a
    # run over a slightly degraded but still usable ticker list.
    earliest = df.index.min() if len(df) else pd.Timestamp.today()
    min_history = pd.Timestamp.today() - pd.Timedelta(days=20 * 365.25)
    if earliest > min_history:
        raise RuntimeError(
            "[QUALITY] Insufficient history: data must go back at least 20 years "
            f"(earliest observation {earliest.date()} < {min_history.date()})."
        )

    df = df.sort_index().ffill().dropna(subset=[target.name])
    print(f"[INGEST] {df.shape} ({time.time()-t0:.1f}s) | cible={target.name}")
    store.save(cache_key, df)
    local_cache.save_dataframe(f"{cache_key}_local", df, max_age_days=30)
    _attach_snapshot_context(df, universe, quality_issues=issues if dq.enabled else None)
    return df
