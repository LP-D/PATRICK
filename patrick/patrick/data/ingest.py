"""Ingestion orchestration: target + feature universe (yfinance + FRED),
aligned on a common index, cached in the local data lake.
"""
from __future__ import annotations

import os
import time

import pandas as pd

from patrick.cache_manager import LocalCache
from patrick.config.schema import DataQualityConfig, ObjectiveConfig, UniverseConfig
from patrick.data import publication_lag
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


def _last_date(s: pd.Series) -> str | None:
    valid = s.dropna().index
    return str(pd.Timestamp(valid.max()).date()) if len(valid) else None


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
    df.attrs["pit_version"] = f"{publication_lag.PIT_VERSION}:{universe.fred_point_in_time}"
    df.attrs["n_tickers"] = len(universe.yf_tickers)
    df.attrs["n_fred_series"] = len(universe.fred_series)
    df.attrs["fred_source"] = "api" if os.environ.get(FRED_API_KEY_ENV) else "scrape"
    df.attrs["quality_issues"] = [i.to_dict() for i in quality_issues] if quality_issues is not None else []


def _run_extra_quality_checks(df_cols: pd.DataFrame, requested_end: pd.Timestamp,
                               dq: DataQualityConfig, issues: list, *, prefilled: bool,
                               fred_ids: dict[str, str] | None = None) -> list[str]:
    """P6.5 checks BEYOND coverage (already handled by `download_universe`/
    `download_fred_universe` themselves, see their `issues` parameter).

    `prefilled`: whether `df_cols` was forward-filled (only the frozen-
    price and aberrant-return gates then apply). `ingest` no longer passes a
    filled frame: yfinance series are checked on their REPORTED closes
    (`download_universe(return_unfilled=True)`) -- on a filled frame a
    holiday bridge reads as frozen prices, which excluded GC=F, ^VIX,
    EURUSD=X and every other future on real data.

    `fred_ids` ({column: FRED id}): FRED columns go through
    `quality.check_fred_series` instead -- the same gates on the series'
    own publication calendar (frequency-aware gap/tail thresholds, no
    frozen-price gate, see its docstring)."""
    to_drop = []
    for col in df_cols.columns:
        s = df_cols[col]
        if fred_ids is not None:
            issue = quality_module.check_fred_series(
                s.rename(col), fred_ids.get(col, col), requested_end,
                max_gap_bdays=dq.max_gap_bdays, max_robust_z=dq.max_robust_z)
            if issue is not None:
                issues.append(issue)
                to_drop.append(col)
            continue
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
    # F01: a cached frame built under another point-in-time rule (or before
    # F01 -- no version recorded: FRED series on their reference dates) is
    # stale whatever its age, never served.
    pit = f"{publication_lag.PIT_VERSION}:{universe.fred_point_in_time}"
    latest = store.latest_entry(cache_key)
    if not force and latest is not None and latest.get("pit_version") == pit:
        df = store.load(cache_key)
        _attach_snapshot_context(df, universe)
        print(f"[CACHE] {cache_key}: {df.shape} already cached (force=True to refresh).")
        return df
    if not force and cached_local is not None and \
            local_cache.read_meta(f"{cache_key}_local").get("pit_version") == pit:
        df = cached_local.copy()
        # Registered in the data lake (content-deduplicated): the run then
        # records a real snapshot_id that `/simulate` and `explain` can
        # reload, never an ad hoc one that exists nowhere on disk.
        store.save(cache_key, df, meta={"pit_version": pit})
        _attach_snapshot_context(df, universe)
        print(f"[CACHE_LOCAL] {cache_key}: {df.shape} reused from local cache (missing rows only).")
        return df
    if not force and latest is not None:
        print(f"[CACHE] {cache_key}: cached snapshot built without point-in-time alignment "
              f"({latest.get('pit_version') or 'pre-F01'}) -- refetching.")

    t0 = time.time()
    if objective.target_source == "yfinance":
        target = yfinance_source.download_target(objective.target_symbol, universe.start_date)
    else:
        target = fred_source.download_series(objective.target_symbol, objective.target_symbol,
                                               universe.start_date)
        if target is None:
            raise RuntimeError(f"Could not fetch FRED target '{objective.target_symbol}'.")
        # F01: a FRED target is placed on its publication dates too -- the
        # label then predicts the next PUBLISHED values, the only thing
        # observable at each decision date.
        if universe.fred_point_in_time != "reference_date":
            target = publication_lag.to_availability_index(target, objective.target_symbol)

    df = target.to_frame()
    store.record_series_observations({objective.target_symbol: _last_date(target)},
                                     source=objective.target_source)
    issues: list = []
    n_requested = len(universe.yf_tickers) + len(universe.fred_series)
    requested_end = pd.Timestamp(df.index.max()) if len(df) else pd.Timestamp.today()

    if universe.yf_tickers:
        yf_df, yf_reported = yfinance_source.download_universe(
            universe.yf_tickers, universe.start_date, universe.yf_coverage, t0=t0,
            issues=issues if dq.enabled else None, return_unfilled=True)
        reverse = {yfinance_source.clean_symbol(t): t for t in universe.yf_tickers}
        store.record_series_observations(
            {reverse.get(c, c): _last_date(yf_reported[c]) for c in yf_reported.columns}, source="yfinance")
        yf_df = _apply_session_lag(yf_df, universe.yf_tickers, objective)
        if dq.enabled and len(yf_df.columns):
            # Gates on the closes as REPORTED, never on the forward-filled
            # frame: a filled holiday bridge reads as "frozen prices" (see
            # `download_universe(return_unfilled=True)`), and real quoting
            # gaps are only visible before the fill.
            to_drop = _run_extra_quality_checks(yf_reported, requested_end, dq, issues, prefilled=False)
            yf_df = yf_df.drop(columns=[c for c in to_drop if c in yf_df.columns])
        df = df.join(yf_df, how="outer")

    if universe.fred_series:
        use_alfred = universe.fred_point_in_time == "alfred"
        fred_df = fred_source.download_fred_universe(
            universe.fred_series, universe.start_date, realtime_date=universe.vintage_realtime_date,
            issues=issues if dq.enabled else None, first_release=use_alfred)
        already_pit = bool(fred_df.attrs.get("point_in_time"))
        if not already_pit:
            store.record_series_observations(
                {universe.fred_series.get(c, c): _last_date(fred_df[c]) for c in fred_df.columns}, source="fred")
        if use_alfred and not already_pit:
            print("  [WARN] fred_point_in_time='alfred' requires FRED_API_KEY: falling back to the "
                  "publication-lag table (data/publication_lag.py).")
        if dq.enabled and len(fred_df.columns):
            # FRED series not pre-filled at this stage: all 4 checks apply.
            to_drop = _run_extra_quality_checks(fred_df, requested_end, dq, issues, prefilled=False,
                                                fred_ids=universe.fred_series)
            fred_df = fred_df.drop(columns=to_drop)
        if len(fred_df):
            # F01: every observation enters on its availability date, series
            # by series (see `publication_lag.align_to_calendar` for why not
            # one `reindex(method="ffill")` on the concatenated frame).
            fred_df = publication_lag.align_fred_frame(
                fred_df, universe.fred_series, df.index,
                already_point_in_time=already_pit or universe.fred_point_in_time == "reference_date")
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
    # having sufficiently old historical data, without blocking a run over a
    # slightly degraded but still usable ticker list.
    #
    # CHANTIER (feature/equity-asset-class, suite): the threshold itself used
    # to be a hardcoded 20 years, with zero test coverage of this branch
    # (confirmed by grep, see the chantier's investigation report) --
    # `dq.min_history_years` (config.schema.DataQualityConfig, default
    # `D.DEFAULT_MIN_HISTORY_YEARS`) makes it a parameter instead, set by the
    # web form/CLI/YAML per run, the effective value cited in the message.
    earliest = df.index.min() if len(df) else pd.Timestamp.today()
    min_history = pd.Timestamp.today() - pd.Timedelta(days=dq.min_history_years * 365.25)
    if earliest > min_history:
        raise RuntimeError(
            f"[QUALITY] Insufficient history: data must go back at least {dq.min_history_years} years "
            f"(earliest observation {earliest.date()} > {min_history.date()})."
        )

    df = df.sort_index().ffill().dropna(subset=[target.name])
    print(f"[INGEST] {df.shape} ({time.time()-t0:.1f}s) | cible={target.name}")
    store.save(cache_key, df, meta={"pit_version": pit})
    local_cache.save_dataframe(f"{cache_key}_local", df, max_age_days=30, extra_meta={"pit_version": pit})
    _attach_snapshot_context(df, universe, quality_issues=issues if dq.enabled else None)
    return df
