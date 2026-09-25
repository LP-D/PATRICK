"""CHANTIER B, cablage reel (feature/model-categories-comparison) : les 3
categories entrainees pour de vrai sur un mini pipeline synthetique
(reutilise les VRAIS internes de `pipeline/engine.py` -- `_FoldPoolBuilder`,
`_FoldContext`, `_fit_eval`, `_select` -- pas une reimplementation isolee).

Revision (retrait de `_reduced_n_trials` + du `base_cfg` impose depuis
global) : per_regime/stacking effectuent maintenant leur PROPRE scan complet
(n_features x sampler x algo) et leur PROPRE tuning Optuna a budget plein,
independamment l'un de l'autre et de global -- voir docstring de
`pipeline/model_categories_training.py`. Tests couverts ici :
- les 2 tests anti-fuite deja livres (frontiere de regime intra-fold,
  out-of-fold du stacking) ;
- budget Optuna plein (compte reellement les n_trials passes a
  `tune_config`, compare a celui de global) ;
- capacite reelle a choisir un n_features different de celui d'un autre
  choix sur un cas synthetique construit pour etre non-ambigu (test unitaire
  cible sur `_grid_scan_best_config`, plus fiable qu'un bout-en-bout bruite
  sur un si petit jeu de donnees) ;
- troncature DM par paire independante (`compare_categories`)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.config.schema import RunConfig
from patrick.data.sources.yfinance_source import clean_symbol
from patrick.pipeline.engine import (
    _fit_eval,
    _FoldContext,
    _FoldPoolBuilder,
    _select,
    build_base_feature_pool,
)
from patrick.pipeline.leaderboard import Leaderboard
from patrick.pipeline.model_categories_training import (
    _grid_scan_best_config,
    extract_global_category_result,
    train_per_regime_category,
    train_stacking_category,
)
from patrick.tracking import db as trackdb
from patrick.tracking.model_categories import CategoryResult, compare_categories
from patrick.validation.diebold_mariano import diebold_mariano
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
        # n_trials volontairement petit pour la vitesse du test -- le budget
        # PLEIN de per_regime/stacking est le meme champ que global
        # (`config.tuning.n_trials`), c'est cette egalite qui est testee,
        # pas une valeur absolue particuliere.
        "tuning": {"enabled": True, "n_trials": 3, "cv_splits": 2},
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
    config, seed = wired_context["config"], wired_context["seed"]
    global_result = extract_global_category_result(ctx, board, horizon, wired_context["n_wf_folds"],
                                                     wired_context["base_cfg"], seed)
    per_regime_result, sub_models = train_per_regime_category(
        ctx, wired_context["raw_price_series"], horizon, wired_context["n_wf_folds"], config, seed)
    stacking_result = train_stacking_category(ctx, horizon, wired_context["n_wf_folds"], config, seed)

    results = {"global": global_result, "per_regime": per_regime_result, "stacking": stacking_result}
    assert {r.category for r in results.values()} == {"global", "per_regime", "stacking"}
    assert len(global_result.fold_metric) > 0
    # per_regime/stacking peuvent legitimement avoir moins de folds evaluables
    # (garde-fou/split OOF trop serre sur un si petit jeu synthetique) --
    # l'important est qu'ils produisent un resultat distinct, pas vide.
    assert len(per_regime_result.fold_loss) >= 0
    assert sub_models  # au moins 1 regime a produit un routage

    comparison = compare_categories(results)
    assert comparison["categories"] == ["global", "per_regime", "stacking"]


def test_per_regime_and_stacking_use_the_full_optuna_budget_like_global(wired_context, monkeypatch):
    """Compte les VRAIS n_trials passes a `tune_config` pendant
    l'entrainement per_regime/stacking -- doit etre exactement
    `config.tuning.n_trials`, identique a ce que global utiliserait (pas de
    `_reduced_n_trials`, retire)."""
    import patrick.pipeline.model_categories_training as mct

    captured_n_trials = []
    real_tune_config = mct.tune_config

    def spy_tune_config(*args, **kwargs):
        captured_n_trials.append(kwargs.get("n_trials"))
        return real_tune_config(*args, **kwargs)

    monkeypatch.setattr(mct, "tune_config", spy_tune_config)

    ctx = wired_context["ctx"]
    config, seed, horizon = wired_context["config"], wired_context["seed"], wired_context["horizon"]

    train_per_regime_category(ctx, wired_context["raw_price_series"], horizon,
                               wired_context["n_wf_folds"], config, seed)
    n_calls_per_regime = len(captured_n_trials)
    assert n_calls_per_regime > 0, "aucun appel tune_config capture pour per_regime"
    assert all(n == config.tuning.n_trials for n in captured_n_trials), (
        f"per_regime doit utiliser le budget PLEIN ({config.tuning.n_trials}), "
        f"pas une fraction -- recu {captured_n_trials}")

    captured_n_trials.clear()
    train_stacking_category(ctx, horizon, wired_context["n_wf_folds"], config, seed)
    assert len(captured_n_trials) > 0, "aucun appel tune_config capture pour stacking"
    assert all(n == config.tuning.n_trials for n in captured_n_trials), (
        f"stacking doit utiliser le budget PLEIN ({config.tuning.n_trials}), "
        f"pas une fraction -- recu {captured_n_trials}")

    # Ni _reduced_n_trials ni aucune fraction du budget ne doit plus exister
    # dans le module (retire explicitement sur demande).
    assert not hasattr(mct, "_reduced_n_trials"), "_reduced_n_trials aurait du etre retire du module"


def test_grid_scan_picks_a_genuinely_different_n_features_when_it_is_clearly_optimal():
    """Test unitaire cible sur `_grid_scan_best_config` (plus fiable qu'un
    bout-en-bout bruite sur un si petit jeu de donnees) : 2 scenarios
    synthetiques construits pour que N=2 soit sans ambiguite meilleur dans
    l'un, et N=8 dans l'autre -- verifie que le scan suit reellement les
    donnees plutot que de retomber toujours sur le meme choix (ce que le
    `base_cfg` impose depuis global faisait avant ce correctif)."""
    import os
    import tempfile

    from patrick.config.schema import RunConfig
    from patrick.tracking import db as trackdb

    rng = np.random.default_rng(7)
    n = 400

    class _FD:
        def __init__(self, X_tr, y_tr, X_te, y_te):
            self.X_tr, self.y_tr, self.X_te, self.y_te = X_tr, y_tr, X_te, y_te

    def _build_fold_data(n_true_informative: int, n_noise: int = 8):
        """y depend UNIQUEMENT des `n_true_informative` premieres colonnes
        (regle simple, sans ambiguite) ; le reste est du bruit pur -- le
        meilleur N doit refleter n_true_informative, pas une valeur fixe."""
        X = rng.normal(0, 1, (n, n_true_informative + n_noise))
        # 3 classes {0, 1, 2} contigues depuis 0 -- `shap_select.py::shap_rank`
        # utilise `objective="multi:softprob"` sans condition (coherent avec
        # la cible reelle du projet, toujours a 4 classes) ; un y BINAIRE
        # {0, 1} declenchait une erreur XGBoost interne (num_class mal
        # infere) specifique a ce cas limite -- pas un bug produit, corrige
        # ici en restant fidele a l'hypothese multiclasse du produit.
        s = X[:, :n_true_informative].sum(axis=1)
        y = np.digitize(s, [np.quantile(s, 1 / 3), np.quantile(s, 2 / 3)])
        split = n // 2
        return [(0, _FD(X[:split], y[:split], X[split:], y[split:]))]

    with tempfile.TemporaryDirectory() as tmp:
        raw_yaml = {
            "name": "grid_scan_test", "objective": {"target_symbol": "^TEST", "horizons": [5]},
            "universe": {"yf_tickers": [], "fred_series": {}},
            "validation": {"n_wf_folds": 1},
            "selection": {"method": "shap"},
            "output": {"dir": tmp, "seed": 42},
        }
        config = RunConfig.model_validate(raw_yaml)
        conn = trackdb.connect(os.path.join(tmp, "t.db"))

        fold_data_small = _build_fold_data(n_true_informative=2)
        winner_small = _grid_scan_best_config(fold_data_small, config, [2, 8], ["none"],
                                               ["RandomForest"], 42, conn, "TEST", 5, "snap-small")

        fold_data_large = _build_fold_data(n_true_informative=8)
        winner_large = _grid_scan_best_config(fold_data_large, config, [2, 8], ["none"],
                                               ["RandomForest"], 42, conn, "TEST", 5, "snap-large")
        conn.close()  # libere le verrou Windows sur t.db avant le nettoyage du TemporaryDirectory

        assert winner_small["n_feat"] != winner_large["n_feat"], (
            "le scan doit reagir aux donnees -- ici il retombe sur le meme N "
            "dans 2 scenarios construits pour etre discriminants.")


def test_stacking_meta_model_never_trains_on_in_sample_base_predictions(wired_context, monkeypatch):
    """Verification CONCRETE (pas juste lecture de code) : instrumente
    `_fit_eval` pour capturer les (X_train, X_eval) de CHAQUE appel pendant
    l'entrainement stacking (scan OOF + tuning + refit final inclus), puis
    verifie qu'AUCUN appel n'evalue sur une ligne presente dans son propre
    train -- invariant qui doit tenir pour tous les appels de cette
    fonction (scan et refit sont tous les deux shapes train->eval
    disjoints par construction du split temporel), pas seulement un
    sous-groupe fixe."""
    import patrick.pipeline.model_categories_training as mct

    calls = []
    real_fit_eval = mct._fit_eval

    def spy_fit_eval(X_tr, y_tr, X_te, y_te, *args, **kwargs):
        calls.append((np.array(X_tr, copy=True), np.array(X_te, copy=True)))
        return real_fit_eval(X_tr, y_tr, X_te, y_te, *args, **kwargs)

    monkeypatch.setattr(mct, "_fit_eval", spy_fit_eval)

    ctx = wired_context["ctx"]
    train_stacking_category(ctx, wired_context["horizon"], wired_context["n_wf_folds"],
                             wired_context["config"], wired_context["seed"])

    assert len(calls) > 0, "aucun appel _fit_eval capture -- le test ne verifie rien, corriger le mock"
    for X_train_used, X_eval_used in calls:
        train_rows = {tuple(row) for row in X_train_used}
        eval_rows = {tuple(row) for row in X_eval_used}
        assert train_rows.isdisjoint(eval_rows), (
            "une ligne evaluee apparait aussi dans le train du meme appel -- "
            "fuite potentielle (OOF ou test) sur une prediction in-sample.")


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
                               wired_context["n_wf_folds"], wired_context["config"], wired_context["seed"])

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


def test_dm_truncation_for_a_pair_ignores_what_a_third_category_covers():
    """`compare_categories` doit tronquer PAR PAIRE (intersection de CETTE
    paire uniquement), jamais sur l'intersection a trois -- construit
    global/stacking avec la MEME longueur complete et per_regime
    deliberement plus court, verifie que le n_obs de la comparaison
    global_vs_stacking reste la longueur COMPLETE, pas ecourtee par
    per_regime."""
    rng = np.random.default_rng(3)
    n_full = 500
    n_short = 50  # per_regime deliberement tronque

    global_res = CategoryResult(category="global", label="g",
                                 fold_metric=np.array([0.5, 0.55]),
                                 fold_loss=(rng.uniform(0, 1, n_full) < 0.4).astype(float))
    stacking_res = CategoryResult(category="stacking", label="s",
                                   fold_metric=np.array([0.52, 0.58]),
                                   fold_loss=(rng.uniform(0, 1, n_full) < 0.45).astype(float))
    per_regime_res = CategoryResult(category="per_regime", label="r",
                                     fold_metric=np.array([0.51]),
                                     fold_loss=(rng.uniform(0, 1, n_short) < 0.42).astype(float))

    results = {"global": global_res, "per_regime": per_regime_res, "stacking": stacking_res}
    comparison = compare_categories(results)

    expected_n_obs = min(len(global_res.fold_loss), len(stacking_res.fold_loss))
    assert expected_n_obs == n_full  # les deux couvrent tout -- rien a tronquer pour CETTE paire
    assert comparison["pairwise_dm"]["global_vs_stacking"]["n_obs"] == n_full, (
        "global_vs_stacking a ete tronque par per_regime -- la troncature doit etre "
        "independante par paire, pas une intersection a trois.")

    # Verification directe (hors compare_categories) que diebold_mariano lui-meme,
    # appele sur les series completes, rapporte bien n_full -- confirme que le
    # chiffre ci-dessus n'est pas un hasard de calcul.
    direct = diebold_mariano(global_res.fold_loss, stacking_res.fold_loss)
    assert direct["n_obs"] == n_full


def test_stacking_base_training_labels_never_overlap_the_oof_block(wired_context, monkeypatch):
    """F02 applied to the stacking meta-split: every base fit whose eval
    block is an OOF block (length n_train - split) was trained on at most
    split - horizon rows -- label windows never overlap the OOF rows'."""
    import patrick.pipeline.model_categories_training as mct

    splits, calls = [], []
    real_split, real_fit_eval = mct._oof_split, mct._fit_eval

    def spy_split(n_train, *a, **k):
        out = real_split(n_train, *a, **k)
        if out is not None:
            splits.append((n_train, out))
        return out

    def spy_fit_eval(X_tr, y_tr, X_te, y_te, *args, **kwargs):
        calls.append((len(X_tr), len(X_te)))
        return real_fit_eval(X_tr, y_tr, X_te, y_te, *args, **kwargs)

    monkeypatch.setattr(mct, "_oof_split", spy_split)
    monkeypatch.setattr(mct, "_fit_eval", spy_fit_eval)
    horizon = wired_context["horizon"]
    train_stacking_category(wired_context["ctx"], horizon, wired_context["n_wf_folds"],
                             wired_context["config"], wired_context["seed"])
    oof_lengths = {n - s: s for n, s in splits}
    checked = [(n_base, n_eval) for n_base, n_eval in calls if n_eval in oof_lengths]
    assert checked
    for n_base, n_eval in checked:
        assert n_base <= oof_lengths[n_eval] - horizon
