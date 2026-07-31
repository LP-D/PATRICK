"""Orchestration de l'ingestion : cible + univers de features (yfinance + FRED),
alignés sur un même index, mis en cache dans le data lake local.
"""
from __future__ import annotations

import os
import time

import pandas as pd

from patrick.config.schema import DataQualityConfig, ObjectiveConfig, UniverseConfig
from patrick.data import quality as quality_module
from patrick.data.session_calendar import session_lag_days
from patrick.data.sources import fred_source, yfinance_source
from patrick.data.sources.fred_source import FRED_API_KEY_ENV
from patrick.data.store import DataStore


def _apply_session_lag(yf_df: pd.DataFrame, tickers: list[str], objective: ObjectiveConfig) -> pd.DataFrame:
    """Décale d'une barre les colonnes dont la classe d'actif clôture après celle
    de la cible (Phase 0.4 — cf. `data/session_calendar.py`) : une jointure "même
    date calendaire" traite implicitement comme simultanées des clôtures de
    marché qui ne le sont pas (ex. clôture US utilisée "du jour" pour une cible
    qui a déjà clôturé plus tôt dans la même journée UTC).

    `objective.disable_session_lag` (rapport de correction, C7) : bascule
    ajoutée uniquement pour `patrick audit degradation`, jamais utilisée en
    production (défaut False -- correction toujours appliquée)."""
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
        print(f"  [ALIGNEMENT] {len(lagged)} tickers décalés d'une barre "
              f"(clôture postérieure à celle de la cible) : {', '.join(lagged[:8])}"
              f"{'...' if len(lagged) > 8 else ''}")
    return out


def _attach_snapshot_context(df: pd.DataFrame, universe: UniverseConfig,
                              quality_issues: list | None = None) -> None:
    """Métadonnées de contexte (Phase 1.6) transportées via `DataFrame.attrs` —
    lues par `pipeline/engine.py` pour peupler la table `snapshot` sans changer
    la signature de `ingest()` (qui reste "retourne un DataFrame", ce que
    monkeypatchent déjà tous les tests existants).

    `quality_issues` (Phase 6.5, P6.5) : `None` sur le chemin cache-hit (les
    exclusions ont eu lieu lors de la récupération d'origine, non rejouées ici
    -- même limite assumée que `n_tickers`/`fred_source`, recalculés à chaque
    appel plutôt que persistés avec les données elles-mêmes)."""
    df.attrs["n_tickers"] = len(universe.yf_tickers)
    df.attrs["n_fred_series"] = len(universe.fred_series)
    df.attrs["fred_source"] = "api" if os.environ.get(FRED_API_KEY_ENV) else "scrape"
    df.attrs["quality_issues"] = [i.to_dict() for i in quality_issues] if quality_issues is not None else []


def _run_extra_quality_checks(df_cols: pd.DataFrame, requested_end: pd.Timestamp,
                               dq: DataQualityConfig, issues: list, *, prefilled: bool) -> list[str]:
    """Contrôles P6.5 AU-DELÀ de la couverture (déjà gérée par `download_universe`/
    `download_fred_universe` elles-mêmes, cf. leur paramètre `issues`).

    `prefilled` : `download_universe` fait déjà un `.ffill()` interne avant de
    renvoyer les colonnes retenues (couverture) -- les vrais trous de cotation
    y sont donc déjà comblés (NaN disparus) au moment où ce module les voit ;
    `check_quote_gaps`/`check_stale_tail` y seraient des no-op (plus de NaN à
    détecter), MAIS une vraie interruption prolongée y apparaît comme une
    clôture figée (valeur ffillée répétée), déjà couverte par
    `check_frozen_prices` -- convergence assumée, pas un trou dans la garantie.
    Les séries FRED (`prefilled=False`) ne sont pas pré-remplies ici : les
    quatre contrôles s'appliquent tels quels."""
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
    """`cache_key` ne dépend que de `target_symbol`, pas de `universe.
    vintage_realtime_date`/`objective.disable_session_lag` (rapport de
    correction, C7) : un cache existant peut donc masquer un changement de ces
    deux bascules. Appelants qui les font varier pour un même `target_symbol`
    (ex. `patrick audit degradation`) DOIVENT passer `force=True`.

    `data_quality` (Phase 6.5, P6.5) : `None` -> `DataQualityConfig()` (portes
    actives par défaut, jamais un défaut silencieusement désactivé)."""
    dq = data_quality if data_quality is not None else DataQualityConfig()
    store = store or DataStore()
    cache_key = f"raw_{objective.target_symbol}"
    if not force and store.exists(cache_key):
        df = store.load(cache_key)
        _attach_snapshot_context(df, universe)
        print(f"[CACHE] {cache_key}: {df.shape} déjà en cache (force=True pour rafraîchir).")
        return df

    t0 = time.time()
    if objective.target_source == "yfinance":
        target = yfinance_source.download_target(objective.target_symbol, universe.start_date)
    else:
        target = fred_source.download_series(objective.target_symbol, objective.target_symbol,
                                               universe.start_date)
        if target is None:
            raise RuntimeError(f"Impossible de récupérer la cible FRED '{objective.target_symbol}'.")

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
            # `download_universe` a déjà ffillé en interne -- `check_quote_gaps`/
            # `check_stale_tail` y seraient des no-op, cf. docstring `prefilled`.
            to_drop = _run_extra_quality_checks(yf_df, requested_end, dq, issues, prefilled=True)
            yf_df = yf_df.drop(columns=to_drop)
        df = df.join(yf_df, how="outer")

    if universe.fred_series:
        fred_df = fred_source.download_fred_universe(
            universe.fred_series, universe.start_date, realtime_date=universe.vintage_realtime_date,
            issues=issues if dq.enabled else None)
        if dq.enabled and len(fred_df.columns):
            # Séries FRED non pré-remplies à ce stade : les 4 contrôles s'appliquent.
            to_drop = _run_extra_quality_checks(fred_df, requested_end, dq, issues, prefilled=False)
            fred_df = fred_df.drop(columns=to_drop)
        if len(fred_df):
            fred_df = fred_df.reindex(df.index, method="ffill")
            df = pd.concat([df, fred_df], axis=1)

    if dq.enabled and n_requested > 0:
        exclusion_frac = len(issues) / n_requested
        if exclusion_frac > dq.max_universe_exclusion_frac:
            details = "; ".join(f"{i.series} ({i.reason})" for i in issues)
            raise RuntimeError(
                f"[QUALITÉ] {len(issues)}/{n_requested} séries de l'univers exclues "
                f"({exclusion_frac:.0%} > seuil {dq.max_universe_exclusion_frac:.0%}) -- "
                f"ingestion refusée plutôt que de continuer sur un univers décimé. "
                f"Motifs : {details}"
            )
        if issues:
            print(f"  [QUALITÉ] {len(issues)}/{n_requested} séries exclues de l'univers "
                  f"({exclusion_frac:.0%}) :")
            for i in issues:
                print(f"    - {i.series} : {i.reason} -- {i.detail}")

    df = df.sort_index().ffill().dropna(subset=[target.name])
    print(f"[INGEST] {df.shape} ({time.time()-t0:.1f}s) | cible={target.name}")
    store.save(cache_key, df)
    _attach_snapshot_context(df, universe, quality_issues=issues if dq.enabled else None)
    return df
