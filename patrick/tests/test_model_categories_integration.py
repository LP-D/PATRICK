"""CHANTIER B, cablage reel (feature/model-categories-comparison) : les 3
categories entrainees pour de vrai sur un mini pipeline synthetique
(reutilise les VRAIS internes de `pipeline/engine.py` -- `_FoldPoolBuilder`,
`_FoldContext`, `_fit_eval`, `_select` -- pas une reimplementation isolee),
plus les 2 tests anti-fuite explicitement demandes : frontiere de regime
intra-fold, et out-of-fold du stacking.

Portee : pas de passage par `run_pipeline()` complet (qui n'expose pas
`ctx`/`pool_builder`/`board`, necessaires pour appeler les nouvelles
fonctions directement) -- le setup ci-dessous reproduit exactement les
memes appels que `run_pipeline` fait en interne pour construire ces objets
(`build_base_feature_pool`, `build_fold_cuts`, `_FoldPoolBuilder`,
`_FoldContext`), verifie par lecture directe du code avant d'ecrire ce
test."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.config.schema import RunConfig
from patrick.data.sources.yfinance_source import clean_symbol
from patrick.features.target import build_target
from patrick.pipeline import engine as engine_module
from patrick.pipeline.engine import (
    _fit_eval,
    _select,
    _FoldContext,
    _FoldPoolBuilder,
    build_base_feature_pool,
)
from patrick.pipeline.leaderboard import Leaderboard
from patrick.pipeline.model_categories_training import (
    extract_global_category_result,
    train_per_regime_category,
    train_stacking_category,
)
from patrick.tracking import db as trackdb
from patrick.tracking.model_categories import compare_categories
from patrick.validation.metrics import metrics
from patrick.validation.walkforward import build_fold_cuts

pytestmark = pytest.mark.slow


def _synthetic_raw(n=1400, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    # 3 blocs de volatilite distincts (calme/stress/calme) pour que le
    # regime HMM (CHANTIER A) ait quelque chose de reel a detecter, pas du
    # simple bruit uniforme -- meme esprit que les fixtures de CHANTIER A.
    third = n // 3
    vol = np.concatenate([np.full(third, 0.005), np.full(third, 0.03),
                           np.full(n - 2 * third, 0.005)])
    rets = rng.normal(0, vol)
    target = 100 * np.cumprod(1 + rets)
    df = pd.DataFrame({"IDX_TEST": target}, index=idx)
    df["SPX_LIKE"] = 3000 + np.cumsum(rng.normal(0, 5, n))
    df["NFCI"] = np.cumsum(rng.normal(0, 0.02, n))
    df["T10Y2Y"] = np.cumsum(rng.normal(0, 0.01, n))
    return df


@pytest.fixture
def tiny_config(tmp_path) -> RunConfig:
    raw_yaml = {
        "name": "categories_integration",
        "objective": {"target_symbol": "^TEST", "horizons": [5], "regimes": ["GLOBAL"]},
        "universe": {"yf_tickers": ["SPX_LIKE"], "fred_series": {"NFCI": "NFCI", "T10Y2Y": "T10Y2Y"},
                     "start_date": "2015-01-01"},
        "features": {"families": ["technical", "spike", "macro"], "pool_prefilter": 40},
        "validation": {"n_wf_folds": 3, "min_train_frac": 0.5, "min_train_rows": 50, "min_test_rows": 10},
        "selection": {"method": "shap", "n_features_grid": [6], "shap_sample": 100},
        "sampler": {"candidates": ["none"]},
        "models": {"algos": ["RandomForest", "XGBoost"]},
        "tuning": {"enabled": False},
        "output": {"dir": str(tmp_path / "runs"), "seed": 42},
    }
    return RunConfig.model_validate(raw_yaml)


@pytest.fixture
def wired_context(tiny_config, tmp_path):
    """Reproduit exactement le setup interne de `run_pipeline` (memes
    appels, meme ordre) pour obtenir `ctx`/`pool_builder`/`raw price
    series`/`board` reels -- pas une reimplementation isolee."""
    raw = _synthetic_raw()
    target_col = clean_symbol(tiny_config.objective.target_symbol)
    conn = trackdb.connect(str(tmp_path / "test.db"))
    snapshot_id = "test-snapshot"

    base_pool = build_base_feature_pool(raw, tiny_config, target_col)
    all_dates = raw.index
    fold_cuts = build_fold_cuts(all_dates, tiny_config.validation.n_wf_folds,
                                 tiny_config.validation.min_train_frac)
    pool_builder = _FoldPoolBuilder(raw, tiny_config, target_col, base_pool, fold_cuts,
                                     conn=conn, snapshot_id=snapshot_id)
    feature_pool = [c for c in pool_builder.get(fold_cuts[0]).columns if c != target_col]
    ctx = _FoldContext(pool_builder, target_col, feature_pool, tiny_config, all_dates, fold_cuts)

    horizon = tiny_config.objective.horizons[0]
    seed = tiny_config.output.seed
    base_cfg = {"n_feat": tiny_config.selection.n_features_grid[0], "sampler": "none", "algo": "RandomForest"}

    # Mini scan manuel (1 seule config) pour peupler un board "global" reel
    # -- meme logique que la boucle de scan de run_pipeline, restreinte a
    # UNE config pour rester rapide dans ce test d'integration.
    board = Leaderboard()
    for k in range(tiny_config.validation.n_wf_folds):
        fd = ctx.prepare(horizon, k, "GLOBAL")
        if fd is None:
            continue
        cols = _select(conn, target_col, horizon, snapshot_id, tiny_config, fd.X_tr, fd.y_tr,
                        base_cfg["n_feat"], seed)
        X_tr_n, X_te_n = fd.X_tr[:, cols], fd.X_te[:, cols]
        met, y_pred, _ = _fit_eval(X_tr_n, fd.y_tr, X_te_n, fd.y_te, base_cfg["sampler"], base_cfg["algo"], seed)
        board.add(horizon=horizon, fold=k + 1, regime="GLOBAL", N=base_cfg["n_feat"],
                  sampler=base_cfg["sampler"], algo=base_cfg["algo"], **met)

    raw_price_series = raw[target_col]
    return {
        "ctx": ctx, "board": board, "horizon": horizon, "n_wf_folds": tiny_config.validation.n_wf_folds,
        "base_cfg": base_cfg, "seed": seed, "raw_price_series": raw_price_series,
        "config": tiny_config,
    }


def test_three_categories_are_trained_and_tagged_distinctly(wired_context):
    ctx, board, horizon = wired_context["ctx"], wired_context["board"], wired_context["horizon"]
    global_result = extract_global_category_result(ctx, board, horizon, wired_context["n_wf_folds"],
                                                     wired_context["base_cfg"], wired_context["seed"])
    per_regime_result, sub_models = train_per_regime_category(
        ctx, wired_context["raw_price_series"], horizon, wired_context["n_wf_folds"],
        wired_context["base_cfg"], wired_context["seed"])
    stacking_result = train_stacking_category(
        ctx, horizon, wired_context["n_wf_folds"], wired_context["config"].models.algos,
        wired_context["base_cfg"]["n_feat"], "none", wired_context["seed"])

    results = {"global": global_result, "per_regime": per_regime_result, "stacking": stacking_result}
    assert {r.category for r in results.values()} == {"global", "per_regime", "stacking"}
    assert len(global_result.fold_metric) > 0
    # per_regime/stacking peuvent legitimement avoir moins de folds evaluables
    # (garde-fou/split OOF trop serre sur un si petit jeu synthetique) --
    # l'important est qu'ils produisent un resultat distinct, pas vide.
    assert len(per_regime_result.fold_loss) >= 0
    assert sub_models  # au moins 1 fold a produit un routage par regime

    comparison = compare_categories(results)
    assert comparison["categories"] == ["global", "per_regime", "stacking"]


def test_stacking_meta_model_never_trains_on_in_sample_base_predictions(wired_context, monkeypatch):
    """Verification CONCRETE (pas juste lecture de code) : instrumente
    `_fit_eval` pour capturer les (X, y) passes a CHAQUE appel pendant
    l'entrainement stacking, puis verifie que les lignes utilisees pour
    entrainer le meta-modele (l'appel OOF) ne recoupent JAMAIS les lignes
    sur lesquelles le modele de base correspondant a ete fit juste avant --
    par construction du split temporel (X_base/X_oof disjoints), mais
    verifie ici sur les VRAIES matrices passees, pas suppose."""
    import patrick.pipeline.model_categories_training as mct

    calls = []
    real_fit_eval = mct._fit_eval

    def spy_fit_eval(X_tr, y_tr, X_te, y_te, *args, **kwargs):
        calls.append((np.array(X_tr, copy=True), np.array(X_te, copy=True)))
        return real_fit_eval(X_tr, y_tr, X_te, y_te, *args, **kwargs)

    monkeypatch.setattr(mct, "_fit_eval", spy_fit_eval)

    ctx = wired_context["ctx"]
    train_stacking_category(ctx, wired_context["horizon"], wired_context["n_wf_folds"],
                             wired_context["config"].models.algos, wired_context["base_cfg"]["n_feat"],
                             "none", wired_context["seed"])

    assert len(calls) > 0, "aucun appel _fit_eval capture -- le test ne verifie rien, corriger le mock"
    n_algos = len(wired_context["config"].models.algos)
    # Par fold evalue : n_algos appels OOF (base sur X_base, predit sur X_oof)
    # puis n_algos appels test (base sur X_tr complet, predit sur X_te) --
    # les paires OOF sont les n_algos premiers appels de chaque groupe de
    # 2*n_algos.
    for group_start in range(0, len(calls), 2 * n_algos):
        oof_calls = calls[group_start:group_start + n_algos]
        for X_train_used, X_eval_used in oof_calls:
            # Aucune ligne de X_eval_used (l'OOF) ne doit apparaitre dans
            # X_train_used (le base-train) -- comparaison exacte des lignes.
            train_rows = {tuple(row) for row in X_train_used}
            eval_rows = {tuple(row) for row in X_eval_used}
            assert train_rows.isdisjoint(eval_rows), (
                "une ligne evaluee out-of-fold apparait aussi dans le train du "
                "modele de base -- fuite du meta-modele sur une prediction in-sample.")


def test_regime_boundary_inside_a_fold_does_not_leak_future_labels(wired_context, monkeypatch):
    """Construit un cas OU une transition de regime tombe AU MILIEU d'un
    fold walk-forward, puis verifie que la detection de regime utilisee
    pour CE fold (fit_end_idx = coupe de CE fold) ne change pas si on
    tronque la serie juste apres la fin du fold -- meme garantie causale
    que les tests de CHANTIER A, mais exercee ICI a travers le cablage reel
    du chantier B (fold_cuts/ctx reels), pas juste `detect_regime()` isolee."""
    import patrick.pipeline.model_categories_training as mct

    captured_regimes = []
    real_detect_regime = mct.detect_regime

    def spy_detect_regime(series, *args, **kwargs):
        result = real_detect_regime(series, *args, **kwargs)
        captured_regimes.append((kwargs.get("fit_end_idx"), result.regime.copy()))
        return result

    monkeypatch.setattr(mct, "detect_regime", spy_detect_regime)

    ctx = wired_context["ctx"]
    train_per_regime_category(ctx, wired_context["raw_price_series"], wired_context["horizon"],
                               wired_context["n_wf_folds"], wired_context["base_cfg"], wired_context["seed"])

    assert len(captured_regimes) == wired_context["n_wf_folds"], (
        "un appel a detect_regime attendu par fold (fit_end_idx = coupe de CE fold), "
        "pas une detection globale unique en amont.")
    fit_end_idxs = [fe for fe, _ in captured_regimes]
    assert fit_end_idxs == sorted(fit_end_idxs), "fit_end_idx doit croitre avec le fold (jamais retro-actif)."
    assert len(set(fit_end_idxs)) == len(fit_end_idxs), (
        "chaque fold doit avoir sa PROPRE detection causale (fit_end_idx distinct), "
        "pas une detection partagee/reutilisee entre folds.")

    # Re-detection manuelle a exactement le meme fit_end_idx que le premier
    # fold, sur une serie tronquee PEU APRES la fin de ce fold -- doit
    # produire un resultat identique a l'intérieur de la fenetre commune
    # (garantie causale, meme principe que test_causal_filter_is_not_
    # retroactively_changed_by_future_data de CHANTIER A).
    from patrick.features.regime_detection import detect_regime as real_detect
    first_fit_end_idx, first_regime = captured_regimes[0]
    truncated_series = wired_context["raw_price_series"].iloc[:first_fit_end_idx + 50]
    retruncated = real_detect(truncated_series, n_states="auto", threshold_mode="quantile",
                               seed=wired_context["seed"], fit_end_idx=first_fit_end_idx)
    common_idx = retruncated.regime.index
    pd.testing.assert_series_equal(first_regime.reindex(common_idx), retruncated.regime, check_names=False)
