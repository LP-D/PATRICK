"""Phase 0 — tests de fuite (0.2 corruption du futur, 0.3 décalage de cible).

Ces deux tests couvrent le pipeline entier (construction des features -> pool
base+paramétrique+interactions -> masques train/test -> mise à l'échelle ->
sélection -> entraînement), pas un module isolé : c'est délibéré, une fuite peut
se cacher à n'importe laquelle de ces étapes (et une l'était : cf.
`features/vol_models.py`/`features/spike.py`, paramètres EGARCH/Kalman/HMM/AR/MA/
ARMA/ARIMA/filtre particulaire estimés sur toute la série avant ce fix — trouvé
en écrivant ce test).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.config.schema import RunConfig
from patrick.data.sources.yfinance_source import clean_symbol
from patrick.models.registry import get_classifier
from patrick.pipeline.engine import (
    _FoldContext,
    _FoldPoolBuilder,
    _select,
    build_base_feature_pool,
)
from patrick.validation.metrics import metrics
from patrick.validation.walkforward import build_fold_cuts


def _synthetic_raw(n=1500, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    target = 15 + np.cumsum(rng.normal(0, 0.5, n)).clip(min=-10)
    df = pd.DataFrame({"IDX_TEST": target}, index=idx)
    df["SPX_LIKE"] = 3000 + np.cumsum(rng.normal(0, 5, n))
    df["NFCI"] = np.cumsum(rng.normal(0, 0.02, n))
    df["T10Y2Y"] = np.cumsum(rng.normal(0, 0.01, n))
    return df


def _driver_raw(n=1500, seed=0, k=4.0) -> pd.DataFrame:
    """Série où le rendement de d à d+1 est causé par `DRIVER[d]` (connu à la date
    de décision d) — `DRIVER` est i.i.d. (aucune autocorrélation d'un jour sur
    l'autre), exposé comme colonne brute donc directement visible comme feature.

    Volontairement PAS un processus à mémoire (type AR(1) sur les rendements) : un
    modèle entraîné sur la cible décalée de +1 barre resterait alors partiellement
    prédictif par la seule autocorrélation du processus (chevauchement mécanique,
    pas une fuite) — ça a été constaté en écrivant ce test avec un premier essai
    à base de momentum AR(1), qui rendait le test ininterprétable. Avec un driver
    i.i.d., le signal disponible à la date d est, par construction, sans aucun
    rapport avec le rendement de d+1 à d+2 (celui de la cible décalée) : un
    modèle qui reste performant sur la cible décalée n'a pu apprendre ça que par
    fuite."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    driver = rng.normal(0, 1.0, n)
    noise = rng.normal(0, 0.3, n)
    steps = np.empty(n)
    steps[0] = noise[0]
    steps[1:] = k * driver[:-1] + noise[1:]  # steps[t] causé par driver[t-1]
    price = 100 + np.cumsum(steps)
    df = pd.DataFrame({"IDX_TEST": price}, index=idx)
    df["DRIVER"] = driver
    df["SPX_LIKE"] = 3000 + np.cumsum(rng.normal(0, 5, n))
    return df


def _corrupt_future(raw: pd.DataFrame, cut_date, seed: int = 999) -> pd.DataFrame:
    """Remplace toutes les observations à `cut_date` ou après par du bruit sans
    rapport avec le process réel (échelle et distribution différentes) — si une
    étape du pipeline utilise ces valeurs pour construire les features/le modèle
    du TRAIN, le résultat divergera de façon flagrante."""
    corrupted = raw.copy()
    future_mask = corrupted.index >= cut_date
    rng = np.random.default_rng(seed)
    n_future = int(future_mask.sum())
    for col in corrupted.columns:
        corrupted.loc[future_mask, col] = rng.normal(loc=1_000_000, scale=100_000, size=n_future)
    return corrupted


def _make_config(**overrides) -> RunConfig:
    raw_yaml = {
        "name": "leak_test",
        "objective": {"target_symbol": "^TEST", "horizons": [5], "regimes": ["GLOBAL"]},
        "universe": {"yf_tickers": ["SPX_LIKE"], "start_date": "2015-01-01"},
        "features": {
            "families": ["technical", "spike", "vol_models"],
            "vol_models": ["egarch", "kalman", "hmm", "ar"],
        },
        # purge=True : sans elle, les tout derniers points de train dont la
        # fenêtre de label (shift(-horizon)) déborde sur le test sont un leak
        # marginal déjà documenté et mesuré négligeable dans le projet d'origine
        # (VIX_PURGED_CV, delta F1_dir≈-0.002) — resté désactivé par défaut pour
        # continuité, mais ce test valide la chaîne complètement protégée
        # (purge+embargo), pas la config par défaut.
        "validation": {"n_wf_folds": 2, "min_train_frac": 0.5, "purge": True, "embargo_enabled": True},
        "selection": {"method": "shap", "n_features_grid": [5], "shap_sample": 200},
        "sampler": {"candidates": ["SMOTE"]},
        "models": {"algos": ["RandomForest"]},
        "tuning": {"enabled": False},
        "output": {"seed": 42},
    }
    for section, patch in overrides.items():
        raw_yaml[section].update(patch)
    return RunConfig.model_validate(raw_yaml)


def _prepare_fold(raw: pd.DataFrame, config: RunConfig, fold_idx: int = 0):
    target_col = clean_symbol(config.objective.target_symbol)
    all_dates = raw.index
    fold_cuts = build_fold_cuts(all_dates, config.validation.n_wf_folds, config.validation.min_train_frac)
    base_pool = build_base_feature_pool(raw, config, target_col)
    pool_builder = _FoldPoolBuilder(raw, config, target_col, base_pool, fold_cuts)
    feature_pool = [c for c in pool_builder.get(fold_cuts[0]).columns if c != target_col]
    ctx = _FoldContext(pool_builder, target_col, feature_pool, config, all_dates, fold_cuts)
    horizon = config.objective.horizons[0]
    prepared = ctx.prepare(horizon, fold_idx, "GLOBAL")
    return prepared, feature_pool


# ---------------------------------------------------------------------------
# 0.2 — corruption du futur : le TRAIN (features + sélection + entraînement) ne
# doit strictement rien changer si on corrompt tout ce qui est postérieur à la
# coupure du fold.
# ---------------------------------------------------------------------------
def test_corrupting_the_future_does_not_change_train_features_or_model():
    config = _make_config()
    raw = _synthetic_raw()
    all_dates = raw.index
    fold_cuts = build_fold_cuts(all_dates, config.validation.n_wf_folds, config.validation.min_train_frac)
    cut_date = all_dates[fold_cuts[0]]

    raw_corrupted = _corrupt_future(raw, cut_date)
    # le train (avant la coupure) doit être bit-identique par construction : sinon
    # le test ne prouverait rien (il faut isoler l'effet de la corruption du futur).
    assert raw.loc[raw.index < cut_date].equals(raw_corrupted.loc[raw_corrupted.index < cut_date])

    prepared_orig, feat_orig = _prepare_fold(raw, config, fold_idx=0)
    prepared_corr, feat_corr = _prepare_fold(raw_corrupted, config, fold_idx=0)
    assert prepared_orig is not None and prepared_corr is not None
    assert feat_orig == feat_corr, "les deux pools doivent avoir les mêmes colonnes (mêmes noms)"

    X_tr_o, y_tr_o, _, _, _, _, _ = prepared_orig
    X_tr_c, y_tr_c, _, _, _, _, _ = prepared_corr

    np.testing.assert_array_equal(y_tr_o, y_tr_c)
    np.testing.assert_allclose(
        X_tr_o, X_tr_c, rtol=1e-8, atol=1e-10,
        err_msg="Le train a changé quand on a corrompu le futur -> fuite dans la construction des features.",
    )

    # étend la vérification à la sélection de features et à l'entraînement du
    # modèle (pas seulement les features brutes) : toute la chaîne, comme demandé.
    cols_o = list(_select(config, X_tr_o, y_tr_o, 5, seed=42))
    cols_c = list(_select(config, X_tr_c, y_tr_c, 5, seed=42))
    assert cols_o == cols_c, "la sélection de features a changé -> fuite en amont d'elle."

    clf_o = get_classifier("RandomForest", seed=42)
    clf_o.fit(X_tr_o[:, cols_o], y_tr_o)
    clf_c = get_classifier("RandomForest", seed=42)
    clf_c.fit(X_tr_c[:, cols_c], y_tr_c)
    np.testing.assert_array_equal(
        clf_o.predict(X_tr_o[:, cols_o]), clf_c.predict(X_tr_c[:, cols_c]),
        err_msg="Le modèle entraîné diffère selon que le futur est corrompu ou non -> fuite.",
    )


def test_corrupting_the_future_changes_test_set_predictably():
    """Contre-épreuve du test précédent : corrompre le futur DOIT changer le
    comportement sur le TEST (qui, lui, se trouve dans la zone corrompue) — sinon
    le test ci-dessus serait trivialement vrai parce que rien ne distinguerait
    jamais train et test dans ce pipeline."""
    config = _make_config()
    raw = _synthetic_raw()
    all_dates = raw.index
    fold_cuts = build_fold_cuts(all_dates, config.validation.n_wf_folds, config.validation.min_train_frac)
    cut_date = all_dates[fold_cuts[0]]
    raw_corrupted = _corrupt_future(raw, cut_date)

    prepared_orig, _ = _prepare_fold(raw, config, fold_idx=0)
    prepared_corr, _ = _prepare_fold(raw_corrupted, config, fold_idx=0)

    _, _, X_te_o, _, _, _, _ = prepared_orig
    _, _, X_te_c, _, _, _, _ = prepared_corr
    # le bruit énorme de corruption change aussi le nombre de lignes "non plates"
    # retenues par build_target -> une forme différente est déjà la preuve que le
    # test a changé ; sinon comparaison de valeurs.
    changed = X_te_o.shape != X_te_c.shape or not np.allclose(X_te_o, X_te_c)
    assert changed, "le test aurait dû changer (il est dans la zone corrompue)."


# ---------------------------------------------------------------------------
# 0.3 — décalage de cible : entraîner sur une cible décalée de +1 barre (donc
# décorrélée des features à la date de décision) doit effondrer la performance
# vers la baseline.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("k,seed", [(30.0, 0), (30.0, 7), (30.0, 13)])
def test_shifting_target_by_one_bar_collapses_performance_to_baseline(k, seed):
    # horizon=1 : fenêtres de label de longueur 1 barre, décalées de 1 barre ->
    # entièrement disjointes (pas de chevauchement mécanique). Avec un horizon
    # plus long (ex. 5), décaler de 1 barre laisse 4/5 de chevauchement entre les
    # deux fenêtres -> une corrélation résiduelle "normale", pas une fuite,
    # fausserait le test (chevauchement mécanique confondu avec une vraie fuite).
    # flat_thr=0 et une seule famille de features (technical) : le strict
    # nécessaire pour que le signal DRIVER->rendement soit appris de façon fiable
    # et reproductible par un simple RandomForest sur un petit jeu synthétique —
    # ce test vérifie l'alignement temporel du pipeline, pas la capacité de SHAP/
    # RandomForest à extraire un signal noyé dans du bruit.
    config = _make_config(
        objective={"horizons": [1], "flat_thr": 0.0},
        features={"families": ["technical"]},
        selection={"n_features_grid": [3]},
    )
    raw = _driver_raw(seed=seed, k=k)

    prepared, feature_pool = _prepare_fold(raw, config, fold_idx=0)
    assert prepared is not None
    X_tr, y_tr, X_te, y_te, _, _, _ = prepared

    cols_true = _select(config, X_tr, y_tr, 3, seed=42)
    clf_true = get_classifier("RandomForest", seed=42)
    clf_true.fit(X_tr[:, cols_true], y_tr)
    met_true = metrics(y_te, clf_true.predict(X_te[:, cols_true]))

    # décale la cible de +1 barre : chaque ligne se voit attribuer le label de la
    # ligne suivante -> à la date de décision d, les features connues à d ne
    # décrivent plus (rien ne garantit qu'elles décrivent) la fenêtre de label
    # utilisée, qui correspond maintenant à d+1.
    y_tr_shift = np.roll(y_tr, -1)[:-1]
    X_tr_shift = X_tr[:-1]
    y_te_shift = np.roll(y_te, -1)[:-1]
    X_te_shift = X_te[:-1]
    assert len(y_tr_shift) >= 50 and len(y_te_shift) >= 10, "pas assez de données pour un test significatif."

    cols_shift = _select(config, X_tr_shift, y_tr_shift, 3, seed=42)
    clf_shift = get_classifier("RandomForest", seed=42)
    clf_shift.fit(X_tr_shift[:, cols_shift], y_tr_shift)
    met_shift = metrics(y_te_shift, clf_shift.predict(X_te_shift[:, cols_shift]))

    majority = np.bincount(y_tr_shift).argmax()
    baseline_pred = np.full(len(y_te_shift), majority)
    met_baseline = metrics(y_te_shift, baseline_pred)

    assert met_true["F1_dir"] >= 0.8, (
        f"Prérequis du test : le modèle doit apprendre un vrai signal fort sur la "
        f"cible NON décalée (F1_dir={met_true['F1_dir']}) — sinon le test suivant "
        f"(collapse vers la baseline) ne prouve rien, un signal faible pourrait "
        f"collapser pour n'importe quelle raison."
    )
    excess_true = met_true["F1_dir"] - met_baseline["F1_dir"]
    destroyed = met_true["F1_dir"] - met_shift["F1_dir"]
    collapse_ratio = destroyed / excess_true if excess_true > 0 else 1.0
    assert collapse_ratio >= 0.6, (
        f"F1_dir vrai={met_true['F1_dir']}, décalé={met_shift['F1_dir']}, "
        f"baseline={met_baseline['F1_dir']} -> seulement {collapse_ratio:.0%} de l'avantage "
        f"au-dessus de la baseline a disparu avec le décalage (attendu : >=60%) -> "
        f"fuite : le modèle garde un edge sur une cible qui ne devrait plus en avoir un."
    )
