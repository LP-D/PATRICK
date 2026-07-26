"""Orchestrateur du pipeline complet : ingestion -> construction des features ->
walk-forward (régime/horizon/fold) -> grille sélection×sampler×N×algo -> meilleur
modèle -> tuning Optuna sur le top-K -> leaderboard + modèle exporté.

Généralise, en une seule commande, la séquence manuelle
VIX_FINAL_FEATURES -> VIX_FINAL_ML_SCAN -> VIX_FINAL_OPTUNA.
"""
from __future__ import annotations

import os
import time

import numpy as np
import pandas as pd
from sklearn.preprocessing import RobustScaler

from patrick.config.schema import RunConfig
from patrick.data.ingest import ingest
from patrick.data.sources.yfinance_source import clean_symbol, download_ohlc
from patrick.data.store import DataStore
from patrick.features import macro as feat_macro
from patrick.features import spike, technical, vol_models
from patrick.features.interactions import INTERACTION_TYPES, discover_interactions
from patrick.features.target import build_target
from patrick.models.registry import get_classifier
from patrick.models.samplers import get_sampler
from patrick.pipeline.leaderboard import Leaderboard
from patrick.selection.registry import select_features
from patrick.tracking.export import export_best_model
from patrick.tuning.optuna_runner import tune_config
from patrick.validation.metrics import metrics
from patrick.validation.purge import purge_mask
from patrick.validation.walkforward import build_fold_cuts, describe_folds


def build_feature_pool(raw: pd.DataFrame, config: RunConfig, target_col: str,
                        pilot_split_idx: int | None = None) -> pd.DataFrame:
    """Applique les familles de features activées à chaque colonne numérique du
    DataFrame brut ingéré (cible + univers de tickers), plus les jointures macro
    FRED et les estimateurs de vol OHLC de la cible.

    Les interactions (VIX_FINAL_FEATURES) sont découvertes une seule fois, sur un
    horizon "pilote" (le milieu de la grille) et le train du premier fold
    (`pilot_split_idx`) — pas re-découvertes par horizon/fold — puis les mêmes
    formules sont appliquées à tout l'historique. C'est la même architecture que
    le projet VIX : le POOL de features est construit une fois, partagé par tous
    les horizons du scan ; seule la sélection SHAP/RFE/LASSO (dans le moteur
    walk-forward, sur le train de CHAQUE fold) varie par horizon/fold."""
    families = config.features.families
    parts: list[pd.DataFrame] = [raw]

    for col in raw.columns:
        s = raw[col]
        if "technical" in families:
            parts.append(technical.build_technical_features(s, prefix=col))
        if "spike" in families:
            parts.append(spike.build_spike_features(s, prefix=col))
        if "vol_models" in families:
            parts.append(vol_models.build_vol_model_features(
                s, prefix=col, models=config.features.vol_models))

    if "macro" in families and config.universe.fred_series:
        macro_cols = list(config.universe.fred_series.keys())
        parts.append(feat_macro.build_macro_features(raw, macro_cols))

    if "technical" in families:
        ohlc = download_ohlc(config.objective.target_symbol, config.universe.start_date)
        if ohlc is not None:
            ohlc_aligned = ohlc.reindex(raw.index).ffill()
            parts.append(technical.ohlc_vol_features(ohlc_aligned, prefix=target_col))

    pool = pd.concat(parts, axis=1)
    pool = pool.loc[:, ~pool.columns.duplicated()]

    if "interactions" in families and pilot_split_idx is not None:
        pool = _add_interactions(pool, config, target_col, pilot_split_idx)

    return pool


def _add_interactions(pool: pd.DataFrame, config: RunConfig, target_col: str,
                       pilot_split_idx: int) -> pd.DataFrame:
    pilot_horizon = config.objective.horizons[len(config.objective.horizons) // 2]
    pilot_target, _, _ = build_target(pool[target_col], pilot_horizon, pilot_split_idx,
                                       config.objective.flat_thr)
    pilot_idx = pilot_target.index
    pilot_cut_date = pool.index[pilot_split_idx]
    pilot_train_mask = np.asarray(pilot_idx < pilot_cut_date)
    y_pilot_tr = pilot_target.values[pilot_train_mask].astype(int)
    if len(y_pilot_tr) < 100:
        print("  [INTERACTIONS] pas assez de données sur le fold pilote — étape sautée.")
        return pool

    feature_cols = [c for c in pool.columns if c != target_col]
    X_pilot_tr = pool.loc[pilot_idx[pilot_train_mask], feature_cols].fillna(0.0)

    inter_df = discover_interactions(
        X_pilot_tr, y_pilot_tr,
        top_base=config.features.interact_top_base,
        top_pairs=config.features.interact_top_pairs,
        final_n=config.features.interact_final_n,
        seed=config.output.seed,
    )
    if inter_df.empty:
        return pool

    full_inter = pd.DataFrame(index=pool.index)
    for col_name in inter_df.columns:
        for tname, fn in INTERACTION_TYPES.items():
            marker = f"__{tname}__"
            if marker in col_name:
                a_name, b_name = col_name.split(marker, 1)
                try:
                    full_inter[col_name] = fn(pool[a_name], pool[b_name])
                except Exception:
                    pass
                break

    print(f"  [INTERACTIONS] {full_inter.shape[1]} features d'interaction ajoutées "
          f"(pilote: h={pilot_horizon}j).")
    return pd.concat([pool, full_inter], axis=1)


class _FoldContext:
    """Prépare X_tr/y_tr/X_te/y_te pour un (horizon, fold, régime) donné — utilisé
    à la fois par le scan principal et par la ré-évaluation post-Optuna, pour
    garantir que les deux passes appliquent exactement la même logique (masques,
    purge, mise à l'échelle)."""

    def __init__(self, pool: pd.DataFrame, target_col: str, feature_pool: list[str],
                 config: RunConfig, all_dates: pd.DatetimeIndex, fold_cuts: list[int]):
        self.pool = pool
        self.target_col = target_col
        self.feature_pool = feature_pool
        self.config = config
        self.all_dates = all_dates
        self.fold_cuts = fold_cuts

    def prepare(self, horizon: int, fold_idx: int, regime: str):
        cfg = self.config
        cut, nxt = self.fold_cuts[fold_idx], self.fold_cuts[fold_idx + 1]
        cut_date, nxt_date = self.all_dates[cut], self.all_dates[nxt - 1]

        target_series, reg_r, _thr = build_target(
            self.pool[self.target_col], horizon, cut, cfg.objective.flat_thr)
        idx = target_series.index
        tr_mask = np.asarray(idx < cut_date)
        te_mask = np.asarray((idx >= cut_date) & (idx <= nxt_date))
        reg_al = reg_r.reindex(idx).fillna("NORMAL").values
        sel = (reg_al == regime) if regime != "GLOBAL" else np.ones(len(idx), dtype=bool)
        tr_mask = tr_mask & sel
        te_mask = te_mask & sel

        if cfg.validation.purge:
            tr_mask = purge_mask(idx, tr_mask, self.all_dates, horizon, cut_date)

        y_tr = target_series.values[tr_mask].astype(int)
        y_te = target_series.values[te_mask].astype(int)
        if (len(y_tr) < cfg.validation.min_train_rows
                or len(y_te) < cfg.validation.min_test_rows):
            return None

        X_pool_df = self.pool[self.feature_pool].reindex(idx)
        sc = RobustScaler()
        X_tr = sc.fit_transform(np.nan_to_num(X_pool_df.values[tr_mask]))
        X_te = sc.transform(np.nan_to_num(X_pool_df.values[te_mask]))
        return X_tr, y_tr, X_te, y_te, str(cut_date.date()), str(nxt_date.date())


def _select(config: RunConfig, X_tr: np.ndarray, y_tr: np.ndarray, n_feat: int, seed: int) -> list[int]:
    return select_features(config.selection.method, X_tr, y_tr, n_feat,
                            config.features.pool_prefilter, seed=seed,
                            shap_sample=config.selection.shap_sample)


def _fit_eval(X_tr: np.ndarray, y_tr: np.ndarray, X_te: np.ndarray, y_te: np.ndarray,
              sampler_name: str, algo: str, seed: int, **algo_overrides) -> dict:
    try:
        Xr, yr = get_sampler(sampler_name, seed).fit_resample(X_tr, y_tr)
    except Exception:
        Xr, yr = X_tr, y_tr
    clf = get_classifier(algo, seed=seed, **algo_overrides)
    clf.fit(Xr, yr)
    return metrics(y_te, clf.predict(X_te))


def run_pipeline(config: RunConfig, store: DataStore | None = None,
                  force_ingest: bool = False) -> dict:
    store = store or DataStore()
    seed = config.output.seed
    t0 = time.time()

    raw = ingest(config.objective, config.universe, store, force=force_ingest)
    target_col = clean_symbol(config.objective.target_symbol)

    all_dates = raw.index
    fold_cuts = build_fold_cuts(all_dates, config.validation.n_wf_folds,
                                 config.validation.min_train_frac)
    describe_folds(all_dates, fold_cuts)

    print("[FEATURES] construction du pool de features...")
    pool = build_feature_pool(raw, config, target_col, pilot_split_idx=fold_cuts[0])
    feature_pool = [c for c in pool.columns if c != target_col]
    print(f"[FEATURES] pool: {len(feature_pool)} colonnes ({time.time()-t0:.1f}s)")
    assert (pool.index == all_dates).all(), "la construction des features ne doit pas changer l'index de dates"
    ctx = _FoldContext(pool, target_col, feature_pool, config, all_dates, fold_cuts)

    board = Leaderboard()
    last_fold = config.validation.n_wf_folds - 1

    for horizon in config.objective.horizons:
        for k in range(config.validation.n_wf_folds):
            for regime in config.objective.regimes:
                prepared = ctx.prepare(horizon, k, regime)
                if prepared is None:
                    continue
                X_tr_full, y_tr, X_te_full, y_te, test_start, test_end = prepared

                for n_feat in config.selection.n_features_grid:
                    cols = _select(config, X_tr_full, y_tr, n_feat, seed)
                    X_tr_n, X_te_n = X_tr_full[:, cols], X_te_full[:, cols]
                    feat_names = [feature_pool[c] for c in cols]

                    for sampler_name in config.sampler.candidates:
                        for algo in config.models.algos:
                            met = _fit_eval(X_tr_n, y_tr, X_te_n, y_te, sampler_name, algo, seed)
                            board.add(horizon=horizon, fold=k + 1, regime=regime, N=n_feat,
                                      sampler=sampler_name, algo=algo,
                                      features="|".join(feat_names),
                                      n_train=len(y_tr), n_test=len(y_te),
                                      test_start=test_start, test_end=test_end, **met)

            print(f"  h={horizon:2d}j fold{k+1}: {len(board.rows)} lignes cumulées "
                  f"[{time.time()-t0:.0f}s]")

    print(f"\n[SCAN] {len(board.rows)} évaluations en {(time.time()-t0)/60:.1f}min")
    best = board.best(metric="F1_dir")
    if best:
        print(f"[BEST avant Optuna] h={best['horizon']}j {best['regime']} N={best['N']} "
              f"{best['sampler']} {best['algo']} -> F1_dir={best['F1_dir']}")

    tuned_rows = []
    if config.tuning.enabled and len(board.rows):
        top_configs = board.top_k(config.tuning.top_k, metric="F1_dir")
        print(f"\n[OPTUNA] affinage des {len(top_configs)} meilleures configs "
              f"({config.tuning.n_trials} essais, CV={config.tuning.cv_splits})...")
        for cfg in top_configs:
            horizon, regime, n_feat = int(cfg["horizon"]), cfg["regime"], int(cfg["N"])
            sampler_name, algo = cfg["sampler"], cfg["algo"]

            prepared = ctx.prepare(horizon, last_fold, regime)
            if prepared is None:
                continue
            X_tr_full, y_tr, _, _, _, _ = prepared
            if len(y_tr) < config.validation.min_train_rows * 2:
                continue
            cols = _select(config, X_tr_full, y_tr, n_feat, seed)
            X_tr_n = X_tr_full[:, cols]

            best_params, best_cv = tune_config(X_tr_n, y_tr, algo, sampler_name,
                                                n_trials=config.tuning.n_trials,
                                                cv_splits=config.tuning.cv_splits, seed=seed)
            print(f"  h={horizon}j {regime} N={n_feat} {sampler_name} {algo}: "
                  f"cv_F1_dir={best_cv:.4f} params={best_params}")

            for k in range(config.validation.n_wf_folds):
                prepared = ctx.prepare(horizon, k, regime)
                if prepared is None:
                    continue
                X_tr_full, y_tr, X_te_full, y_te, test_start, test_end = prepared
                cols = _select(config, X_tr_full, y_tr, n_feat, seed)
                X_tr_n, X_te_n = X_tr_full[:, cols], X_te_full[:, cols]
                met = _fit_eval(X_tr_n, y_tr, X_te_n, y_te, sampler_name, algo, seed, **best_params)
                tuned_rows.append({"horizon": horizon, "fold": k + 1, "regime": regime,
                                    "N": n_feat, "sampler": sampler_name, "algo": algo,
                                    "best_params": str(best_params),
                                    "test_start": test_start, "test_end": test_end, **met})

    tuned_df = pd.DataFrame(tuned_rows)
    csv_path = board.export(config.output.dir, config.name)
    if len(tuned_df):
        os.makedirs(config.output.dir, exist_ok=True)
        tuned_path = os.path.join(config.output.dir, f"{config.name}_tuned.csv")
        tuned_df.to_csv(tuned_path, index=False)
        print(f"[EXPORT] {tuned_path}")
    print(f"[EXPORT] {csv_path}")

    final_best = dict(best) if best else None
    if len(tuned_df):
        group_cols = ["horizon", "regime", "N", "sampler", "algo"]
        tuned_agg = (tuned_df.groupby(group_cols + ["best_params"])["F1_dir"]
                     .mean().reset_index().sort_values("F1_dir", ascending=False))
        if len(tuned_agg) and (final_best is None or tuned_agg.iloc[0]["F1_dir"] > final_best["F1_dir"]):
            final_best = tuned_agg.iloc[0].to_dict()

    model_path = None
    if final_best is not None:
        model_path = export_best_model(pool, target_col, feature_pool, config,
                                        final_best, config.output.dir, seed=seed)

    return {
        "leaderboard": board.as_df(),
        "tuned": tuned_df,
        "best_before_tuning": best,
        "final_best": final_best,
        "model_path": model_path,
        "elapsed_s": time.time() - t0,
    }
