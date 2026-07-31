"""Orchestrateur du pipeline complet : ingestion -> construction des features ->
walk-forward (régime/horizon/fold) -> grille sélection×sampler×N×algo -> meilleur
modèle -> tuning Optuna sur le top-K -> leaderboard + modèle exporté.

Généralise, en une seule commande, la séquence manuelle
VIX_FINAL_FEATURES -> VIX_FINAL_ML_SCAN -> VIX_FINAL_OPTUNA.

Phase 0 (correctness) : les features "paramétriques" (EGARCH/Kalman/HMM/AR/MA/
ARMA/ARIMA de vol_models.py, filtre particulaire de spike.py) estiment des
paramètres globaux avant de produire une sortie récursive causale — les estimer
une seule fois sur tout l'historique (comme avant ce fix) fait fuir de
l'information du test d'un fold vers le train d'un autre, même si la sortie
point-par-point est elle-même causale (cf. `tests/test_leakage.py`, test de
corruption du futur). Le pool de features est donc scindé en deux :
- `build_base_feature_pool` : technical/spike(hors filtre particulaire)/macro —
  fenêtres glissantes pures, aucun paramètre global, calculé une seule fois.
- `build_parametric_pool` : vol_models paramétriques + filtre particulaire,
  réajustés par fold via `fit_end_idx` (train du fold uniquement), mis en cache
  par coupure de fold (indépendante de l'horizon, donc `n_wf_folds` variantes,
  pas `n_wf_folds × n_horizons`).
Les interactions sont découvertes une fois sur le fold pilote (comme avant) mais
leurs FORMULES (déterministes, algébriques) sont réappliquées à chaque pool de
fold — pas de fuite : une formule appliquée à des valeurs déjà correctement
recalculées par fold ne réintroduit rien.

Phase 1 (persistance SQLite) : chaque évaluation (pas seulement la gagnante) est
écrite dans `~/.patrick/patrick.db` — une ligne `run` par (target, horizon) de la
config (ils partagent le même `snapshot_id`), une ligne `trial` par combinaison
(régime, N, sampler, algo) réellement testée, une ligne `fold_metric` par
(trial, fold, métrique), une ligne `prediction` par observation de test. Le CSV/
leaderboard existant n'est pas remplacé, seulement complété : la base sert la
Phase 2 (validité statistique), pas un remplacement de l'export actuel.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass

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
from patrick.models.calibration import calibrate_classifier, predict_with_threshold, search_threshold
from patrick.models.registry import get_classifier
from patrick.models.samplers import get_sampler
from patrick.models.sequential_forest import SequentialBootstrapRandomForestClassifier
from patrick.models.uniqueness import average_uniqueness, build_indicator_matrix, effective_sample_size
from patrick.pipeline.leaderboard import Leaderboard
from patrick.selection.registry import select_features
from patrick.selection.stability import feature_selection_stability
from patrick.tracking import db as trackdb
from patrick.tracking import holdout_diagnostic as trackholdout
from patrick.tracking import stats as trackstats
from patrick.tracking.export import export_best_model
from patrick.tuning.optuna_runner import tune_config
from patrick.validation.baselines import compute_baselines
from patrick.validation.diebold_mariano import diebold_mariano
from patrick.validation.embargo import embargo_mask
from patrick.validation.metrics import metrics
from patrick.validation.purge import purge_mask
from patrick.validation.walkforward import build_fold_cuts, describe_folds


def build_base_feature_pool(raw: pd.DataFrame, config: RunConfig, target_col: str) -> pd.DataFrame:
    """Features causales par construction (fenêtres glissantes/lags, aucun
    paramètre estimé globalement) : technical, spike (hors filtre particulaire),
    macro, + estimateurs de vol OHLC de la cible. Calculé une seule fois, partagé
    par tous les folds/horizons d'un run — sans risque de fuite (cf. docstring de
    module)."""
    families = config.features.families
    parts: list[pd.DataFrame] = [raw]

    for col in raw.columns:
        s = raw[col]
        if "technical" in families:
            parts.append(technical.build_technical_features(s, prefix=col))
        if "spike" in families:
            parts.append(spike.build_spike_features_base(s, prefix=col))
        if "vol_models" in families:
            parts.append(vol_models.build_vol_model_features_base(
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
    return pool


def build_parametric_pool(raw: pd.DataFrame, config: RunConfig,
                           fit_end_idx: int | None,
                           test_end_idx: int | None = None) -> pd.DataFrame:
    """vol_models paramétriques (EGARCH/Kalman/HMM/AR/MA/ARMA/ARIMA) + filtre
    particulaire (spike) — réestimés sur `raw.iloc[:fit_end_idx]` uniquement
    (train du fold), appliqués causalement sur tout l'historique sans
    ré-estimation. `fit_end_idx=None` : fit sur toute la série (utilisé pour le
    modèle de production final, qui n'a plus de test à protéger).

    `test_end_idx` (rapport de correction, D2 -> N1) : fin du fold de TEST
    courant. `raw` couvre tout le dataset (pas seulement ce fold), donc sans
    cette borne EGARCH appliquerait `.fix()` sur une série s'étendant bien
    au-delà du fold -- canal de fuite `variance_bounds` mesuré réel mais inerte
    sur données réalistes (D2), fermé ici par construction à coût nul (mesuré
    gratuit). Ignoré par les autres modèles paramétriques (récursions causales
    non affectées, cf. docstring de `vol_models._PARAMETRIC_MODELS`)."""
    families = config.features.families
    parts: list[pd.DataFrame] = []

    for col in raw.columns:
        s = raw[col]
        if "vol_models" in families:
            parts.append(vol_models.build_vol_model_features_parametric(
                s, prefix=col, models=config.features.vol_models,
                fit_end_idx=fit_end_idx, test_end_idx=test_end_idx))
        if "spike" in families:
            parts.append(spike.build_spike_features_parametric(s, prefix=col, fit_end_idx=fit_end_idx))

    if not parts:
        return pd.DataFrame(index=raw.index)
    pool = pd.concat(parts, axis=1)
    pool = pool.loc[:, ~pool.columns.duplicated()]
    return pool


def _discover_interaction_formulas(pool: pd.DataFrame, config: RunConfig,
                                     target_col: str, pilot_split_idx: int) -> list[str]:
    """Découvre les formules d'interaction (VIX_FINAL_FEATURES) sur le fold
    pilote (train du premier fold) — retourne les noms de colonnes retenues, qui
    encodent la paire de features + le type d'interaction (cf.
    `INTERACTION_TYPES`), réutilisables tels quels par `_apply_interaction_formulas`
    sur le pool (base + paramétrique) de n'importe quel fold."""
    pilot_horizon = config.objective.horizons[len(config.objective.horizons) // 2]
    pilot_target, _, _ = build_target(pool[target_col], pilot_horizon, pilot_split_idx,
                                       config.objective.flat_thr)
    pilot_idx = pilot_target.index
    pilot_cut_date = pool.index[pilot_split_idx]
    pilot_train_mask = np.asarray(pilot_idx < pilot_cut_date)
    y_pilot_tr = pilot_target.values[pilot_train_mask].astype(int)
    if len(y_pilot_tr) < 100:
        print("  [INTERACTIONS] pas assez de données sur le fold pilote — étape sautée.")
        return []

    feature_cols = [c for c in pool.columns if c != target_col]
    X_pilot_tr = pool.loc[pilot_idx[pilot_train_mask], feature_cols].fillna(0.0)

    inter_df = discover_interactions(
        X_pilot_tr, y_pilot_tr,
        top_base=config.features.interact_top_base,
        top_pairs=config.features.interact_top_pairs,
        final_n=config.features.interact_final_n,
        seed=config.output.seed,
    )
    return list(inter_df.columns)


def _apply_interaction_formulas(pool: pd.DataFrame, formula_names: list[str]) -> pd.DataFrame:
    """Applique des formules d'interaction déjà découvertes (noms de colonnes
    encodant paire + type) aux valeurs de `pool` — opération algébrique/fenêtre
    glissante déterministe, sans risque de fuite tant que `pool` lui-même est
    correct pour le fold considéré."""
    if not formula_names:
        return pd.DataFrame(index=pool.index)
    full_inter = pd.DataFrame(index=pool.index)
    for col_name in formula_names:
        for tname, fn in INTERACTION_TYPES.items():
            marker = f"__{tname}__"
            if marker in col_name:
                a_name, b_name = col_name.split(marker, 1)
                if a_name in pool.columns and b_name in pool.columns:
                    try:
                        full_inter[col_name] = fn(pool[a_name], pool[b_name])
                    except Exception:
                        pass
                break
    return full_inter


class _FoldPoolBuilder:
    """Construit et met en cache (par coupure de fold, indépendante de l'horizon)
    le pool complet base+paramétrique+interactions d'un fold."""

    def __init__(self, raw: pd.DataFrame, config: RunConfig, target_col: str,
                 base_pool: pd.DataFrame, fold_cuts: list[int]):
        self.raw = raw
        self.config = config
        self.target_col = target_col
        self.base_pool = base_pool
        self.fold_cuts = fold_cuts
        self._cache: dict[int, pd.DataFrame] = {}
        self.interaction_formulas: list[str] = []
        if "interactions" in config.features.families:
            self._init_interactions()

    def _merge_base_and_parametric(self, cut_idx: int) -> pd.DataFrame:
        # D2 -> N1 : `cut_idx` est à la fois la fin du train et le début du test
        # de son fold (`fold_cuts[k]`) -- la fin de CE fold de test est donc la
        # coupure suivante dans la même liste (`fold_cuts[k+1]`), ou None au-delà
        # du dernier fold connu (pas de troncature, comportement d'origine).
        pos = self.fold_cuts.index(cut_idx)
        test_end_idx = self.fold_cuts[pos + 1] if pos + 1 < len(self.fold_cuts) else None
        param_pool = build_parametric_pool(self.raw, self.config, fit_end_idx=cut_idx,
                                            test_end_idx=test_end_idx)
        merged = pd.concat([self.base_pool, param_pool], axis=1)
        return merged.loc[:, ~merged.columns.duplicated()]

    def _init_interactions(self) -> None:
        pilot_cut = self.fold_cuts[0]
        pilot_pool = self._merge_base_and_parametric(pilot_cut)
        self.interaction_formulas = _discover_interaction_formulas(
            pilot_pool, self.config, self.target_col, pilot_cut)
        print(f"  [INTERACTIONS] {len(self.interaction_formulas)} formules découvertes (fold pilote).")
        inter = _apply_interaction_formulas(pilot_pool, self.interaction_formulas)
        self._cache[pilot_cut] = pd.concat([pilot_pool, inter], axis=1)

    def get(self, cut_idx: int) -> pd.DataFrame:
        if cut_idx not in self._cache:
            merged = self._merge_base_and_parametric(cut_idx)
            if self.interaction_formulas:
                inter = _apply_interaction_formulas(merged, self.interaction_formulas)
                merged = pd.concat([merged, inter], axis=1)
            self._cache[cut_idx] = merged
        return self._cache[cut_idx]


@dataclass
class FoldData:
    """Sortie de `_FoldContext.prepare()` — un objet nommé plutôt qu'un tuple
    positionnel : la Phase 1 (persistance) a besoin de `test_dates` (une date par
    ligne de test, pour la table `prediction`) en plus de ce qu'utilisait déjà la
    Phase 0, et un 8e élément positionnel commençait à être illisible/fragile à
    l'appel."""
    X_tr: np.ndarray
    y_tr: np.ndarray
    X_te: np.ndarray
    y_te: np.ndarray
    test_start: str
    test_end: str
    test_dates: list[str]
    baselines: dict | None = None
    baseline_predictions: dict | None = None
    # Phase 6.2 (P6.2) -- poids d'unicité (une valeur par ligne de X_tr, même
    # ordre) + matrice indicatrice observation x barre (pour le bootstrap
    # séquentiel) + taille d'échantillon effective (somme des unicités,
    # TOUJOURS calculée -- propriété des labels, indépendante du sampler).
    sample_weight: np.ndarray | None = None
    ind_matrix: np.ndarray | None = None
    effective_n: float | None = None


class _FoldContext:
    """Prépare X_tr/y_tr/X_te/y_te pour un (horizon, fold, régime) donné — utilisé
    à la fois par le scan principal et par la ré-évaluation post-Optuna, pour
    garantir que les deux passes appliquent exactement la même logique (masques,
    purge, embargo, mise à l'échelle)."""

    def __init__(self, pool_builder: _FoldPoolBuilder, target_col: str, feature_pool: list[str],
                 config: RunConfig, all_dates: pd.DatetimeIndex, fold_cuts: list[int]):
        self.pool_builder = pool_builder
        self.target_col = target_col
        self.feature_pool = feature_pool
        self.config = config
        self.all_dates = all_dates
        self.fold_cuts = fold_cuts

    def prepare(self, horizon: int, fold_idx: int, regime: str,
                want_baselines: bool = False) -> FoldData | None:
        cfg = self.config
        cut, nxt = self.fold_cuts[fold_idx], self.fold_cuts[fold_idx + 1]
        cut_date, nxt_date = self.all_dates[cut], self.all_dates[nxt - 1]
        pool = self.pool_builder.get(cut)

        target_series, reg_r, thr = build_target(
            pool[self.target_col], horizon, cut, cfg.objective.flat_thr)
        idx = target_series.index
        tr_mask = np.asarray(idx < cut_date)
        te_mask = np.asarray((idx >= cut_date) & (idx <= nxt_date))
        reg_al = reg_r.reindex(idx).fillna("NORMAL").values
        sel = (reg_al == regime) if regime != "GLOBAL" else np.ones(len(idx), dtype=bool)
        tr_mask = tr_mask & sel
        te_mask = te_mask & sel

        if cfg.validation.purge:
            tr_mask = purge_mask(idx, tr_mask, self.all_dates, horizon, cut_date)
        if cfg.validation.embargo_enabled:
            e = cfg.validation.embargo_bars if cfg.validation.embargo_bars is not None else horizon
            te_mask = embargo_mask(idx, te_mask, cut_date, e)

        y_tr = target_series.values[tr_mask].astype(int)
        y_te = target_series.values[te_mask].astype(int)
        if (len(y_tr) < cfg.validation.min_train_rows
                or len(y_te) < cfg.validation.min_test_rows):
            # Rapport de correction, D3 : la garde existait déjà (min_train_rows/
            # min_test_rows) mais excluait le fold SILENCIEUSEMENT -- l'incident
            # de débogage C3 (dernier fold walk-forward effondré à 10-13 lignes de
            # test, `None` renvoyé sans un mot) a montré que ça oblige à
            # instrumenter le code à la main pour comprendre un budget Optuna/SCAN
            # incomplet. Avertissement explicite désormais systématique.
            print(f"  [WARN] fold {fold_idx + 1} exclu (h={horizon}j régime={regime}) : "
                  f"train={len(y_tr)} (min {cfg.validation.min_train_rows}), "
                  f"test={len(y_te)} (min {cfg.validation.min_test_rows}).")
            return None

        X_pool_df = pool[self.feature_pool].reindex(idx)
        sc = RobustScaler()
        X_tr = sc.fit_transform(np.nan_to_num(X_pool_df.values[tr_mask]))
        X_te = sc.transform(np.nan_to_num(X_pool_df.values[te_mask]))
        test_dates = [str(d.date()) for d in idx[te_mask]]

        # Phase 6.2 (P6.2) : spans de label [position, position+horizon] des
        # observations de TRAIN sur la grille de barres du fold (`self.
        # all_dates`, pas `idx` -- `idx` a des trous, cf. `build_target`, lignes
        # "flat" et fin de série retirées, alors que le chevauchement de labels
        # se raisonne sur le calendrier réel des barres). Fenêtre locale (pas
        # tout l'historique) : borne la taille de la matrice indicatrice à la
        # taille réelle du bloc train, pas à des milliers de jours d'historique.
        train_dates = idx[tr_mask]
        start_positions_global = self.all_dates.get_indexer(train_dates)
        valid = start_positions_global >= 0
        if valid.all() and len(start_positions_global):
            min_pos = int(start_positions_global.min())
            n_bars_local = int(start_positions_global.max()) + horizon - min_pos + 1
            local_positions = start_positions_global - min_pos
            ind_matrix = build_indicator_matrix(local_positions, horizon, n_bars_local)
            avg_uniqueness = average_uniqueness(ind_matrix)
            effective_n = effective_sample_size(avg_uniqueness)
            sample_weight = avg_uniqueness
        else:
            ind_matrix, sample_weight, effective_n = None, None, float(len(y_tr))

        baselines = None
        baseline_predictions = None
        if want_baselines:
            # Un seul calcul (return_predictions=True) : les métriques agrégées
            # (leaderboard) ET les prédictions brutes (Diebold-Mariano, Phase 2.5)
            # viennent de la même passe, pas de deux appels redondants.
            baseline_predictions = compute_baselines(
                pool[self.target_col], target_series, idx, tr_mask, te_mask,
                y_tr, y_te, horizon, thr, reg_r, return_predictions=True)
            baselines = {name: metrics(y_te, pred) for name, pred in baseline_predictions.items()}

        return FoldData(X_tr, y_tr, X_te, y_te, str(cut_date.date()), str(nxt_date.date()),
                         test_dates, baselines, baseline_predictions,
                         sample_weight, ind_matrix, effective_n)


def _select(config: RunConfig, X_tr: np.ndarray, y_tr: np.ndarray, n_feat: int, seed: int) -> list[int]:
    return select_features(config.selection.method, X_tr, y_tr, n_feat,
                            config.features.pool_prefilter, seed=seed,
                            shap_sample=config.selection.shap_sample)


def _fit_eval(X_tr: np.ndarray, y_tr: np.ndarray, X_te: np.ndarray, y_te: np.ndarray,
              sampler_name: str, algo: str, seed: int, calibration: bool = False,
              sample_weight: np.ndarray | None = None, ind_matrix: np.ndarray | None = None,
              uniqueness_weights_enabled: bool = True, **algo_overrides):
    """Retourne (metrics_dict, y_pred, confiance_prédite) — `confiance_prédite`
    (probabilité de la classe prédite, une valeur par ligne de test) alimente
    `prediction.y_proba`, qui n'a qu'une colonne (pas un vecteur par classe).

    `sampler_name="none"` (Phase 5.3, `models/samplers.py::_NoResample`) : pas
    de rééchantillonnage, s'appuie sur `class_weight`/`auto_class_weights`
    déjà câblé en dur pour RandomForest/LightGBM/CatBoost
    (`models/registry.py`) -- XGBoost/GradientBoosting n'ont pas d'équivalent
    natif en multiclasse et restent donc non pondérés dans ce cas.

    `calibration=True` (Phase 5.3, `config.models.calibration`) : calibration
    isotonique + recherche de seuil causal (`models/calibration.py`,
    jusqu'ici non branché) plutôt qu'un simple `argmax`. La tranche de
    validation du seuil est les 15% les PLUS RÉCENTS du train rééchantillonné
    (les lignes sont déjà en ordre chronologique à ce stade) -- jamais le
    test, cohérent avec le reste du pipeline.

    `sample_weight`/`ind_matrix` (Phase 6.2, P6.2) : poids d'unicité et
    matrice indicatrice observation x barre, calculés sur `X_tr`/`y_tr` AVANT
    rééchantillonnage. Appliqués seulement si `sampler_name=="none"` (`Xr`
    reste alors X_tr inchangé, même ordre/nombre de lignes -- SMOTE et les
    autres suréchantillonneurs synthétisent des observations sans span réel,
    limite assumée documentée dans `SamplingConfig`). Pour RandomForest :
    bootstrap séquentiel (`SequentialBootstrapRandomForestClassifier`) plutôt
    que le bootstrap uniforme de sklearn. Pour les autres algos qui le
    supportent : `sample_weight` passé directement à `.fit()`. Combinaison
    avec `calibration=True` non gérée (hors périmètre P6.2, limite documentée) :
    le chemin calibré reste non pondéré même si les poids sont disponibles."""
    apply_uniqueness = (uniqueness_weights_enabled and sampler_name == "none"
                         and sample_weight is not None)
    try:
        Xr, yr = get_sampler(sampler_name, seed).fit_resample(X_tr, y_tr)
    except Exception:
        Xr, yr = X_tr, y_tr
    weight_applies = apply_uniqueness and len(Xr) == len(X_tr)
    clf = get_classifier(algo, seed=seed, **algo_overrides)

    n_val = max(int(len(Xr) * 0.15), 20)
    if calibration and n_val < len(Xr) - 20:
        X_fit, y_fit = Xr[:-n_val], yr[:-n_val]
        X_val, y_val = Xr[-n_val:], yr[-n_val:]
        cal_clf = calibrate_classifier(clf, X_fit, y_fit)
        threshold, _ = search_threshold(cal_clf, X_val, y_val)
        y_pred = predict_with_threshold(cal_clf, X_te, threshold)
        y_proba = cal_clf.predict_proba(X_te)
        classes = list(cal_clf.classes_)
        confidence = np.array([row[classes.index(p)] if p in classes else np.nan
                                for row, p in zip(y_proba, y_pred)])
    else:
        if weight_applies and algo == "RandomForest":
            clf = SequentialBootstrapRandomForestClassifier(seed=seed)
            clf.fit(Xr, yr, ind_matrix=ind_matrix, sample_weight=sample_weight)
        elif weight_applies:
            try:
                clf.fit(Xr, yr, sample_weight=sample_weight)
            except TypeError:
                clf.fit(Xr, yr)
        else:
            clf.fit(Xr, yr)
        y_pred = np.asarray(clf.predict(X_te)).ravel()
        y_proba = None
        confidence = None
        if hasattr(clf, "predict_proba"):
            try:
                y_proba = clf.predict_proba(X_te)
                confidence = y_proba[np.arange(len(y_pred)), y_pred.astype(int)]
            except Exception:
                y_proba = None
    met = metrics(y_te, y_pred, y_proba=y_proba)
    return met, y_pred, confidence


def _parse_params(raw_params) -> dict:
    if not raw_params:
        return {}
    if isinstance(raw_params, str):
        return ast.literal_eval(raw_params)
    return raw_params


def _walk_forward_span(all_dates: pd.DatetimeIndex, holdout_months: int, min_train_frac: float) -> int:
    """Position (exclue) où s'arrête le domaine walk-forward : les
    `holdout_months` derniers mois d'historique sont réservés (Phase 2.1),
    jamais vus par la sélection de features, le tuning ou le tri du
    leaderboard — seulement par une unique réévaluation finale de la config
    déjà choisie (`_evaluate_holdout`). Renvoie `len(all_dates)` (holdout
    désactivé) si `holdout_months<=0` ou si l'historique est trop court pour à
    la fois entraîner (`min_train_frac`) et garder un holdout de la durée
    demandée — le run continue sans holdout plutôt que de planter, avec un
    avertissement explicite."""
    n = len(all_dates)
    if holdout_months <= 0 or n == 0:
        return n
    holdout_start_date = all_dates[-1] - pd.DateOffset(months=holdout_months)
    n_wf = int((all_dates < holdout_start_date).sum())
    if n_wf < max(int(n * min_train_frac) + 1, 100):
        print(f"  [WARN] historique trop court pour un holdout de {holdout_months} mois "
              f"en plus de l'entraînement walk-forward — holdout désactivé pour ce run.")
        return n
    return n_wf


def _evaluate_holdout(pool_builder: "_FoldPoolBuilder", target_col: str, feature_pool: list[str],
                       config: RunConfig, all_dates_full: pd.DatetimeIndex, n_wf: int,
                       best_cfg: dict, seed: int) -> dict | None:
    """Réévalue la config gagnante (Phase 2.1) sur le holdout terminal : le
    modèle est réentraîné UNIQUEMENT sur les données antérieures au holdout
    (`pool_builder.get(n_wf)` -> paramétrique fit sur `raw.iloc[:n_wf]`, même
    mécanisme causal que les folds walk-forward), puis testé sur les lignes
    jamais vues. Une seule config évaluée ici — celle déjà choisie par le scan
    walk-forward — jamais utilisée pour choisir entre plusieurs (anti-pattern
    #1 du plan fourni : ne rien trier/sélectionner sur le holdout)."""
    horizon = int(best_cfg["horizon"])
    regime = best_cfg["regime"]
    n_feat = int(best_cfg["N"])
    sampler_name, algo = best_cfg["sampler"], best_cfg["algo"]
    best_params = _parse_params(best_cfg.get("best_params"))

    pool = pool_builder.get(n_wf)
    target_series, reg_r, _thr = build_target(pool[target_col], horizon, n_wf, config.objective.flat_thr)
    idx = target_series.index
    holdout_start_date = all_dates_full[n_wf]
    tr_mask = np.asarray(idx < holdout_start_date)
    te_mask = np.asarray(idx >= holdout_start_date)
    reg_al = reg_r.reindex(idx).fillna("NORMAL").values
    sel = (reg_al == regime) if regime != "GLOBAL" else np.ones(len(idx), dtype=bool)
    tr_mask, te_mask = tr_mask & sel, te_mask & sel

    y_tr = target_series.values[tr_mask].astype(int)
    y_te = target_series.values[te_mask].astype(int)
    if len(y_tr) < config.validation.min_train_rows or len(y_te) < config.validation.min_test_rows:
        print(f"  [WARN] holdout exclu (h={horizon}j régime={regime}) : "
              f"train={len(y_tr)} (min {config.validation.min_train_rows}), "
              f"test={len(y_te)} (min {config.validation.min_test_rows}).")
        return None

    X_pool_df = pool[feature_pool].reindex(idx)
    sc = RobustScaler()
    X_tr = sc.fit_transform(np.nan_to_num(X_pool_df.values[tr_mask]))
    X_te = sc.transform(np.nan_to_num(X_pool_df.values[te_mask]))
    cols = _select(config, X_tr, y_tr, n_feat, seed)
    met, y_pred, confidence = _fit_eval(X_tr[:, cols], y_tr, X_te[:, cols], y_te,
                                         sampler_name, algo, seed,
                                         calibration=config.models.calibration, **best_params)
    test_dates = [str(d.date()) for d in idx[te_mask]]
    return {"metrics": met, "y_pred": y_pred, "y_proba": confidence, "y_true": y_te,
            "test_dates": test_dates, "n_train": len(y_tr), "n_test": len(y_te)}


def _evaluate_diebold_mariano(ctx: "_FoldContext", best_cfg: dict, last_fold: int, seed: int) -> dict | None:
    """DM (Phase 2.5) entre la config gagnante et la meilleure des baselines
    systématiques (Phase 0.6), sur le fold walk-forward le plus récent — la
    période la plus proche du régime de marché actuel, plutôt qu'une moyenne
    sur tout l'historique qui diluerait un éventuel changement de régime."""
    horizon, regime = int(best_cfg["horizon"]), best_cfg["regime"]
    n_feat, sampler_name, algo = int(best_cfg["N"]), best_cfg["sampler"], best_cfg["algo"]
    best_params = _parse_params(best_cfg.get("best_params"))

    fd = ctx.prepare(horizon, last_fold, regime, want_baselines=True)
    if fd is None or not fd.baseline_predictions:
        return None
    cols = _select(ctx.config, fd.X_tr, fd.y_tr, n_feat, seed)
    _, y_pred, _ = _fit_eval(fd.X_tr[:, cols], fd.y_tr, fd.X_te[:, cols], fd.y_te,
                              sampler_name, algo, seed,
                              calibration=ctx.config.models.calibration, **best_params)

    best_baseline_name, best_baseline_pred, best_f1 = None, None, -1.0
    for name, pred in fd.baseline_predictions.items():
        f1 = (fd.baselines or {}).get(name, {}).get("F1_dir")
        if f1 is not None and f1 == f1 and f1 > best_f1:
            best_f1, best_baseline_name, best_baseline_pred = f1, name, pred
    if best_baseline_pred is None:
        return None

    loss_model = (np.asarray(y_pred).ravel() != fd.y_te).astype(float)
    loss_baseline = (np.asarray(best_baseline_pred).ravel() != fd.y_te).astype(float)
    dm = diebold_mariano(loss_model, loss_baseline, h=horizon)
    dm["baseline"] = best_baseline_name
    return dm


def _config_hash(config: RunConfig) -> str:
    return hashlib.sha256(config.model_dump_json().encode()).hexdigest()[:16]


def _snapshot_context(raw: pd.DataFrame) -> tuple[str, str, int | None, int | None, str | None, list]:
    """Lit le contexte de snapshot déposé par `ingest()` sur `raw.attrs` (Phase
    1.6). En repli — `raw` vient d'un `ingest` monkeypatché par un test, sans
    `.attrs` — calcule un identifiant ad-hoc à partir du contenu, pour que la
    persistance reste fonctionnelle/testable même sans le vrai `ingest()`.

    `quality_issues` (Phase 6.5, P6.5) : liste de dicts (`[]` par défaut sur un
    `ingest` monkeypatché, cf. `data/ingest.py::_attach_snapshot_context`)."""
    snapshot_id = raw.attrs.get("snapshot_id")
    data_hash = raw.attrs.get("data_hash")
    if not snapshot_id:
        data_hash = hashlib.sha256(
            pd.util.hash_pandas_object(raw, index=True).values.tobytes()).hexdigest()[:12]
        snapshot_id = f"adhoc__{data_hash}"
    return snapshot_id, data_hash or snapshot_id, raw.attrs.get("n_tickers"), \
        raw.attrs.get("n_fred_series"), raw.attrs.get("fred_source"), raw.attrs.get("quality_issues", [])


def run_pipeline(config: RunConfig, store: DataStore | None = None,
                  force_ingest: bool = False, db_path: str | None = None,
                  job_id: str | None = None) -> dict:
    store = store or DataStore()
    seed = config.output.seed
    t0 = time.time()

    raw = ingest(config.objective, config.universe, store, force=force_ingest,
                 data_quality=config.data_quality)
    target_col = clean_symbol(config.objective.target_symbol)

    conn = trackdb.connect(db_path)
    snapshot_id, data_hash, n_tickers, n_fred_series, fred_src, quality_issues = _snapshot_context(raw)
    trackdb.upsert_snapshot(conn, snapshot_id, data_hash, n_tickers, n_fred_series, fred_src)
    trackdb.add_data_quality_issues(conn, snapshot_id, quality_issues)
    config_json = config.model_dump_json()
    config_hash = _config_hash(config)
    git_sha = trackdb.current_git_sha()

    run_ids: dict[int, str] = {}
    for horizon in config.objective.horizons:
        run_id = f"{config.name}_h{horizon}_{uuid.uuid4().hex[:8]}"
        trackdb.create_run(conn, run_id, target=config.objective.target_symbol, horizon=horizon,
                            snapshot_id=snapshot_id, config_json=config_json,
                            config_hash=config_hash, git_sha=git_sha, seed=seed, job_id=job_id)
        run_ids[horizon] = run_id

    all_dates_full = raw.index
    n_wf = _walk_forward_span(all_dates_full, config.validation.holdout_months,
                               config.validation.min_train_frac)
    all_dates = all_dates_full[:n_wf]
    fold_cuts = build_fold_cuts(all_dates, config.validation.n_wf_folds,
                                 config.validation.min_train_frac)
    describe_folds(all_dates, fold_cuts)
    if n_wf < len(all_dates_full):
        print(f"[HOLDOUT] {len(all_dates_full) - n_wf} lignes réservées "
              f"({all_dates_full[n_wf].date()} -> {all_dates_full[-1].date()}), "
              "jamais vues par la sélection/le tuning.")

    print("[FEATURES] construction du pool de base (causal, partagé par tous les folds)...")
    base_pool = build_base_feature_pool(raw, config, target_col)
    print(f"[FEATURES] pool de base: {base_pool.shape[1]} colonnes ({time.time()-t0:.1f}s)")
    # base_pool est construit sur `raw` (historique complet, holdout inclus) :
    # comparer à all_dates_full, pas à all_dates (domaine walk-forward tronqué
    # du holdout, cf. _walk_forward_span).
    assert (base_pool.index == all_dates_full).all(), "la construction des features ne doit pas changer l'index de dates"

    pool_builder = _FoldPoolBuilder(raw, config, target_col, base_pool, fold_cuts)
    feature_pool = [c for c in pool_builder.get(fold_cuts[0]).columns if c != target_col]
    print(f"[FEATURES] pool complet (fold 1, base+paramétrique+interactions): {len(feature_pool)} colonnes")
    ctx = _FoldContext(pool_builder, target_col, feature_pool, config, all_dates, fold_cuts)

    board = Leaderboard()
    baseline_rows: list[dict] = []
    baseline_accum: dict[tuple[str, str], list[dict]] = {}
    trial_ids: dict[tuple, int] = {}
    n_trials_per_run: dict[str, int] = {h: 0 for h in run_ids.values()}
    last_fold = config.validation.n_wf_folds - 1

    for horizon in config.objective.horizons:
        run_id = run_ids[horizon]
        for k in range(config.validation.n_wf_folds):
            for regime in config.objective.regimes:
                fd = ctx.prepare(horizon, k, regime, want_baselines=True)
                if fd is None:
                    continue

                for baseline_name, base_met in (fd.baselines or {}).items():
                    baseline_rows.append({"horizon": horizon, "fold": k + 1, "regime": regime,
                                           "N": None, "sampler": None, "algo": baseline_name,
                                           "features": "", "n_train": len(fd.y_tr), "n_test": len(fd.y_te),
                                           "test_start": fd.test_start, "test_end": fd.test_end, **base_met})
                    baseline_accum.setdefault((run_id, baseline_name), []).append(base_met)

                for n_feat in config.selection.n_features_grid:
                    cols = _select(config, fd.X_tr, fd.y_tr, n_feat, seed)
                    X_tr_n, X_te_n = fd.X_tr[:, cols], fd.X_te[:, cols]
                    feat_names = [feature_pool[c] for c in cols]

                    for sampler_name in config.sampler.candidates:
                        for algo in config.models.algos:
                            met, y_pred, confidence = _fit_eval(
                                X_tr_n, fd.y_tr, X_te_n, fd.y_te, sampler_name, algo, seed,
                                calibration=config.models.calibration,
                                sample_weight=fd.sample_weight, ind_matrix=fd.ind_matrix,
                                uniqueness_weights_enabled=config.sampling.uniqueness_weights)
                            board.add(horizon=horizon, fold=k + 1, regime=regime, N=n_feat,
                                      sampler=sampler_name, algo=algo,
                                      features="|".join(feat_names),
                                      n_train=len(fd.y_tr), n_test=len(fd.y_te),
                                      # Phase 6.2 (P6.2) : taille d'échantillon effective (somme
                                      # des unicités) à côté de n_train -- toujours calculée.
                                      effective_n_train=fd.effective_n,
                                      test_start=fd.test_start, test_end=fd.test_end, **met)

                            trial_key = (horizon, regime, n_feat, sampler_name, algo)
                            if trial_key not in trial_ids:
                                trial_ids[trial_key] = trackdb.create_trial(
                                    conn, run_id, regime, algo, sampler_name, n_feat,
                                    selector=config.selection.method)
                                n_trials_per_run[run_id] += 1
                            trial_id = trial_ids[trial_key]
                            # Phase 6.2 (P6.2) : n_eff stocké comme un "metric" de plus
                            # (schéma générique trial/fold_index/split/metric/value, pas de
                            # colonne dédiée) -- lu par le rapport HTML à côté de F1_dir/etc.
                            met_with_n = dict(met)
                            met_with_n["n_train"] = float(len(fd.y_tr))
                            if fd.effective_n is not None:
                                met_with_n["effective_n_train"] = fd.effective_n
                            trackdb.add_fold_metrics(conn, trial_id, fold_index=k + 1,
                                                      split="test", metrics=met_with_n)
                            trackdb.add_predictions(conn, trial_id, fold_index=k + 1, split="test",
                                                     ts=fd.test_dates, y_true=fd.y_te,
                                                     y_pred=y_pred, y_proba=confidence)

            print(f"  h={horizon:2d}j fold{k+1}: {len(board.rows)} lignes cumulées "
                  f"[{time.time()-t0:.0f}s]")

    print(f"\n[SCAN] {len(board.rows)} évaluations en {(time.time()-t0)/60:.1f}min")
    best = board.best(metric="F1_dir")
    if best:
        print(f"[BEST avant Optuna] h={best['horizon']}j {best['regime']} N={best['N']} "
              f"{best['sampler']} {best['algo']} -> F1_dir={best['F1_dir']}")

    # Phase 6.3 (P6.3) -- stabilité de la sélection de features, PAR HORIZON
    # (chaque run_id est scopé à un horizon, cf. schéma Phase 1.2) : pour la
    # config (regime, N) localement gagnante de CET horizon (moyenne F1_dir
    # sur ses folds, indépendant du choix global `final_best` ci-dessous, qui
    # ne retient qu'UN SEUL horizon), stabilité mesurée sur les features
    # réellement retenues par fold (déjà capturées dans `board.rows[...]
    # ["features"]`, pas de re-sélection). sampler/algo n'influencent pas la
    # sélection (faite avant leur boucle) : les dédupliquer avant Jaccard.
    if config.selection.track_stability:
        for horizon in config.objective.horizons:
            board_h = Leaderboard()
            board_h.rows = [r for r in board.rows if r.get("horizon") == horizon and r.get("N") is not None]
            top_h = board_h.top_k(1, metric="F1_dir")
            if not top_h:
                continue
            winner = top_h[0]
            fold_feature_sets: dict[int, list[str]] = {}
            for r in board_h.rows:
                if r["regime"] == winner["regime"] and r["N"] == winner["N"]:
                    fold_feature_sets.setdefault(r["fold"], r["features"].split("|") if r["features"] else [])
            stability = feature_selection_stability(fold_feature_sets)
            trackdb.save_feature_stability(conn, run_ids[horizon], stability["mean_jaccard"],
                                            stability["n_folds"], stability["selection_freq"])
            if stability["warning"]:
                print(f"  [STABILITÉ] h={horizon}j : {stability['warning']}")

    # Rapport d'audit, C4 -- diagnostic holdout de TOUTE la grille SCAN (pas
    # seulement le gagnant final), écrit dans `holdout_diagnostic` (table
    # séparée de `fold_metric`, jamais lue par la sélection/le tuning) : permet
    # une corrélation de rang test/holdout après coup, sans jamais influencer
    # le choix de la config gagnante.
    if n_wf < len(all_dates_full) and trial_ids:
        print(f"[HOLDOUT DIAGNOSTIC] évaluation de {len(trial_ids)} trials sur le holdout "
              "(lecture seule, ne choisit rien)...")
        for (h, regime, n_feat, sampler_name, algo), tid in trial_ids.items():
            diag_cfg = {"horizon": h, "regime": regime, "N": n_feat,
                        "sampler": sampler_name, "algo": algo, "best_params": {}}
            diag_eval = _evaluate_holdout(pool_builder, target_col, feature_pool, config,
                                           all_dates_full, n_wf, diag_cfg, seed)
            if diag_eval is not None:
                trackholdout.write_holdout_diagnostic(conn, tid, diag_eval["metrics"])

    tuned_rows = []
    tuned_trial_ids: dict[tuple, int] = {}
    if config.tuning.enabled and len(board.rows):
        if config.tuning.optuna_select_top_k_per_horizon:
            # Rapport d'audit, C3 : sélection top_k PAR horizon (pas globale) --
            # sinon un horizon dont le meilleur essai SCAN domine peut capter
            # 100% du budget Optuna, laissant les autres horizons à zéro essai.
            top_configs = []
            for horizon in config.objective.horizons:
                board_h = Leaderboard()
                board_h.rows = [r for r in board.rows if r.get("horizon") == horizon]
                top_configs.extend(board_h.top_k(config.tuning.top_k, metric="F1_dir"))
        else:
            top_configs = board.top_k(config.tuning.top_k, metric="F1_dir")
        print(f"\n[OPTUNA] affinage des {len(top_configs)} meilleures configs "
              f"({config.tuning.n_trials} essais, CV={config.tuning.cv_splits}, "
              f"par_horizon={config.tuning.optuna_select_top_k_per_horizon})...")
        # Phase 3.2 (`patrick resume`) : étude Optuna persistée dans un fichier
        # SQLite dédié (jamais `patrick.db`), un `study_name` déterministe par
        # config testée -> un `patrick run`/`patrick resume` relancé sur la
        # même config (même config_hash, donc même nom d'étude) après une
        # interruption reprend les essais déjà faits au lieu de repartir à
        # zéro (cf. `tune_config`, `optuna_runner.py`).
        os.makedirs(config.output.dir, exist_ok=True)
        optuna_storage_path = os.path.join(config.output.dir, "optuna.db")
        for cfg in top_configs:
            horizon, regime, n_feat = int(cfg["horizon"]), cfg["regime"], int(cfg["N"])
            sampler_name, algo = cfg["sampler"], cfg["algo"]
            run_id = run_ids[horizon]

            fd = ctx.prepare(horizon, last_fold, regime)
            if fd is None:
                continue
            if len(fd.y_tr) < config.validation.min_train_rows * 2:
                continue
            cols = _select(config, fd.X_tr, fd.y_tr, n_feat, seed)
            X_tr_n = fd.X_tr[:, cols]

            study_name = f"{config.name}_{config_hash}_h{horizon}_{regime}_N{n_feat}_{sampler_name}_{algo}"
            best_params, best_cv = tune_config(X_tr_n, fd.y_tr, algo, sampler_name,
                                                n_trials=config.tuning.n_trials,
                                                cv_splits=config.tuning.cv_splits, seed=seed,
                                                storage_path=optuna_storage_path, study_name=study_name)
            print(f"  h={horizon}j {regime} N={n_feat} {sampler_name} {algo}: "
                  f"cv_F1_dir={best_cv:.4f} params={best_params}")

            tuned_key = (horizon, regime, n_feat, sampler_name, algo, json.dumps(best_params, sort_keys=True))
            tuned_trial_ids[tuned_key] = trackdb.create_trial(
                conn, run_id, regime, algo, sampler_name, n_feat,
                selector=config.selection.method, params_json=json.dumps(best_params))
            n_trials_per_run[run_id] += 1
            tuned_trial_id = tuned_trial_ids[tuned_key]

            for k in range(config.validation.n_wf_folds):
                fd = ctx.prepare(horizon, k, regime)
                if fd is None:
                    continue
                cols = _select(config, fd.X_tr, fd.y_tr, n_feat, seed)
                X_tr_n, X_te_n = fd.X_tr[:, cols], fd.X_te[:, cols]
                met, y_pred, confidence = _fit_eval(
                    X_tr_n, fd.y_tr, X_te_n, fd.y_te, sampler_name, algo, seed,
                    calibration=config.models.calibration,
                    sample_weight=fd.sample_weight, ind_matrix=fd.ind_matrix,
                    uniqueness_weights_enabled=config.sampling.uniqueness_weights, **best_params)
                tuned_rows.append({"horizon": horizon, "fold": k + 1, "regime": regime,
                                    "N": n_feat, "sampler": sampler_name, "algo": algo,
                                    "best_params": str(best_params), "effective_n_train": fd.effective_n,
                                    "test_start": fd.test_start, "test_end": fd.test_end, **met})
                trackdb.add_fold_metrics(conn, tuned_trial_id, fold_index=k + 1, split="test", metrics=met)
                trackdb.add_predictions(conn, tuned_trial_id, fold_index=k + 1, split="test",
                                         ts=fd.test_dates, y_true=fd.y_te, y_pred=y_pred, y_proba=confidence)

    tuned_df = pd.DataFrame(tuned_rows)
    if baseline_rows:
        board.rows.extend(baseline_rows)
    csv_path = board.export(config.output.dir, config.name)
    if len(tuned_df):
        os.makedirs(config.output.dir, exist_ok=True)
        tuned_path = os.path.join(config.output.dir, f"{config.name}_tuned.csv")
        tuned_df.to_csv(tuned_path, index=False)
        print(f"[EXPORT] {tuned_path}")
    print(f"[EXPORT] {csv_path}")

    # baseline_metric n'a pas de colonne fold_index (schéma Phase 1.2) : agrégée
    # (moyenne) par run plutôt qu'écrite par fold — cf. rapport de phase.
    for (run_id, baseline_name), fold_dicts in baseline_accum.items():
        agg = {}
        for m in {k for d in fold_dicts for k in d}:
            values = [v for v in (d.get(m) for d in fold_dicts) if v is not None and v == v]
            if values:
                agg[m] = float(np.mean(values))
        trackdb.add_baseline_metrics(conn, run_id, baseline_name, split="test", metrics=agg)

    final_best = dict(best) if best else None
    if len(tuned_df):
        group_cols = ["horizon", "regime", "N", "sampler", "algo"]
        tuned_agg = (tuned_df.groupby(group_cols + ["best_params"])["F1_dir"]
                     .mean().reset_index().sort_values("F1_dir", ascending=False))
        if len(tuned_agg) and (final_best is None or tuned_agg.iloc[0]["F1_dir"] > final_best["F1_dir"]):
            final_best = tuned_agg.iloc[0].to_dict()

    model_path = None
    holdout_result = None
    dm_result = None
    pbo_result = None
    cumulative_trials = 0
    holdout_diagnostic_result = None
    if final_best is not None:
        full_pool = pd.concat(
            [base_pool, build_parametric_pool(raw, config, fit_end_idx=None)], axis=1)
        full_pool = full_pool.loc[:, ~full_pool.columns.duplicated()]
        if pool_builder.interaction_formulas:
            full_inter = _apply_interaction_formulas(full_pool, pool_builder.interaction_formulas)
            full_pool = pd.concat([full_pool, full_inter], axis=1)
        model_path = export_best_model(full_pool, target_col, feature_pool, config,
                                        final_best, config.output.dir, seed=seed,
                                        interaction_formulas=pool_builder.interaction_formulas)

        best_key = (int(final_best["horizon"]), final_best["regime"], int(final_best["N"]),
                    final_best["sampler"], final_best["algo"])
        best_trial_id = trial_ids.get(best_key)
        if best_trial_id is None and "best_params" in final_best:
            parsed_params = _parse_params(final_best["best_params"])
            tuned_key = best_key + (json.dumps(parsed_params, sort_keys=True),)
            best_trial_id = tuned_trial_ids.get(tuned_key)
        if best_trial_id is not None:
            trackdb.mark_best_trial(conn, best_trial_id, artifact_path=model_path)

        # Phase 2.1 — holdout terminal : une seule réévaluation de la config déjà
        # choisie, jamais utilisée pour choisir entre plusieurs (cf. docstring
        # de _evaluate_holdout).
        if n_wf < len(all_dates_full):
            holdout_eval = _evaluate_holdout(pool_builder, target_col, feature_pool, config,
                                              all_dates_full, n_wf, final_best, seed)
            if holdout_eval is not None:
                holdout_result = holdout_eval["metrics"]
                if best_trial_id is not None:
                    trackdb.add_fold_metrics(conn, best_trial_id, fold_index=0, split="holdout",
                                              metrics=holdout_result)
                    trackdb.add_predictions(conn, best_trial_id, fold_index=0, split="holdout",
                                             ts=holdout_eval["test_dates"], y_true=holdout_eval["y_true"],
                                             y_pred=holdout_eval["y_pred"], y_proba=holdout_eval["y_proba"])

        # Phase 2.5 — Diebold-Mariano vs meilleure baseline (dernier fold walk-forward).
        dm_result = _evaluate_diebold_mariano(ctx, final_best, last_fold, seed)

        # Phase 2.2 — essais cumulés sur cette cible/horizon, tout l'historique de
        # runs confondu (pas seulement ce run). Phase 2.4 — PBO sur ce même historique.
        cumulative_trials = trackstats.count_cumulative_trials(
            conn, config.objective.target_symbol, int(final_best["horizon"]))
        pbo_result = trackstats.pbo_for_target(
            conn, config.objective.target_symbol, int(final_best["horizon"]), final_best["regime"])

        # Rapport d'audit, C4 -- diagnostic (LECTURE SEULE, cf. holdout_diagnostic.py) :
        # la procédure de sélection généralise-t-elle du test vers le holdout ?
        # N'influence jamais final_best, calculé après coup uniquement.
        holdout_diagnostic_result = trackholdout.spearman_test_vs_holdout(
            conn, run_ids[int(final_best["horizon"])], metric="F1_dir")

    for run_id in run_ids.values():
        trackdb.finish_run(conn, run_id, status="done", n_trials=n_trials_per_run[run_id])
    conn.close()

    return {
        "leaderboard": board.as_df(),
        "tuned": tuned_df,
        "best_before_tuning": best,
        "final_best": final_best,
        "model_path": model_path,
        "elapsed_s": time.time() - t0,
        "holdout": holdout_result,
        "diebold_mariano": dm_result,
        "cumulative_trials": cumulative_trials,
        "pbo": pbo_result,
        "holdout_diagnostic": holdout_diagnostic_result,
    }
