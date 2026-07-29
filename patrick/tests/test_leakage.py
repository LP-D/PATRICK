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


def _corrupt_strictly_after(raw: pd.DataFrame, boundary_date, seed: int = 999) -> pd.DataFrame:
    """Comme `_corrupt_future` mais corrompt seulement les lignes STRICTEMENT
    postérieures à `boundary_date` (pas `>=`) — utilisé pour isoler une fuite
    qui affecterait le TEST via des données situées au-delà de la FIN de son
    propre fold (ex. une fenêtre glissante ou un as-of join qui déborderait sur
    le fold suivant), par opposition à `_corrupt_future` qui corrompt aussi la
    zone de test elle-même et ne peut donc pas isoler ce cas précis."""
    corrupted = raw.copy()
    future_mask = corrupted.index > boundary_date
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
@pytest.mark.slow  # ~23s mesuré (rapport de correction, D1) : features+sélection+entraînement complets
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

    X_tr_o, y_tr_o = prepared_orig.X_tr, prepared_orig.y_tr
    X_tr_c, y_tr_c = prepared_corr.X_tr, prepared_corr.y_tr

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


@pytest.mark.slow  # ~17s mesuré (rapport de correction, D1)
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

    X_te_o = prepared_orig.X_te
    X_te_c = prepared_corr.X_te
    # le bruit énorme de corruption change aussi le nombre de lignes "non plates"
    # retenues par build_target -> une forme différente est déjà la preuve que le
    # test a changé ; sinon comparaison de valeurs.
    changed = X_te_o.shape != X_te_c.shape or not np.allclose(X_te_o, X_te_c)
    assert changed, "le test aurait dû changer (il est dans la zone corrompue)."


@pytest.mark.slow  # ~20s/cas mesuré (rapport de correction, D1)
@pytest.mark.parametrize("shift_magnitude,purge_enabled,expect_detected", [
    (1, False, True),
    (1, True, False),    # magnitude(1) <= horizon(5) -> masqué par le purge (propriété documentée, pas un bug)
    (3, False, True),
    (3, True, False),    # magnitude(3) <= horizon(5) -> masqué par le purge, idem
    (10, False, True),
    (10, True, True),    # magnitude(10) > horizon(5) -> le purge ne peut plus masquer, détecté
])
def test_future_leak_detection_by_magnitude_and_purge(shift_magnitude, purge_enabled, expect_detected):
    """Rapport d'audit, C2.b — l'audit a montré (mutation M2, session d'audit)
    qu'une fuite `.shift(-1)` avec horizon=5/purge=True est ABSORBÉE par la
    marge de purge et non détectée par
    `test_corrupting_the_future_does_not_change_train_features_or_model`. Ce
    n'est PAS un test cassé : le purge retire du train toute ligne dont la
    fenêtre de label déborderait sur le test (`purge_mask`), donc toute ligne
    de train dont la fuite pointerait dans la zone corrompue est
    structurellement retirée AVANT même de pouvoir révéler la fuite — une
    PROPRIÉTÉ DU DISPOSITIF (documentée et vérifiée ici par la paramétrisation
    ci-dessus), pas une lacune du test 0.2 lui-même. Seuil vérifié
    empiriquement : masqué ssi `shift_magnitude <= horizon` (ici horizon=5) ;
    ce test échoue si ce seuil venait à changer sans être remarqué.

    Objectif explicite de l'audit : qu'aucune magnitude ne passe inaperçue
    dans AU MOINS UNE configuration testée — satisfait ici puisque chaque
    magnitude est testée à la fois avec purge désactivé (où la détection est
    garantie) et purge actif (où la détection dépend du seuil ci-dessus).

    La fuite est injectée en donnée BRUTE (pas une modification du pipeline) :
    `build_base_feature_pool` inclut `raw` tel quel dans le pool
    (`parts = [raw]`), donc une colonne brute contenant la cible décalée dans
    le futur apparaît comme feature sans toucher à
    `patrick/pipeline/engine.py`.

    `flat_thr=0.0` (comme le test 0.3) : `build_target` retire les lignes dont
    le rendement label est "plat" (`abs(ret) < flat_thr`) -- corrompre le
    futur change ce rendement pour les lignes de train proches de la coupure
    dont la fenêtre de label déborde dessus, ce qui peut faire BASCULER leur
    statut plat/non-plat et changer le NOMBRE de lignes de train entre
    original et corrompu (confondu avec l'effet de la fuite elle-même,
    surtout quand purge=False ne retire plus ces lignes). Sans rapport avec la
    fuite testée ici -- neutralisé en désactivant le filtre plat."""
    horizon = 5
    config = _make_config(
        objective={"flat_thr": 0.0},
        validation={"purge": purge_enabled, "embargo_enabled": purge_enabled},
    )
    assert config.objective.horizons[0] == horizon  # prérequis : le seuil documenté suppose horizon=5

    raw = _synthetic_raw()
    target_col = clean_symbol(config.objective.target_symbol)
    leak_col = f"LEAK_SHIFT_{shift_magnitude}"

    all_dates = raw.index
    fold_cuts = build_fold_cuts(all_dates, config.validation.n_wf_folds, config.validation.min_train_frac)
    cut_date = all_dates[fold_cuts[0]]
    raw_corrupted = _corrupt_future(raw, cut_date)
    assert raw.loc[raw.index < cut_date].equals(raw_corrupted.loc[raw_corrupted.index < cut_date])

    # La colonne de fuite est ajoutée APRÈS corruption, séparément sur `raw` et
    # `raw_corrupted`, chacune calculée à partir de SA PROPRE colonne cible --
    # sinon un `.shift()` unique calculé AVANT corruption "gèlerait" la
    # relation dans les lignes de train, empêchant mécaniquement la fuite de
    # se manifester (reproduit ce que fait la mutation M2 de l'audit : le
    # `.shift()` est recalculé à l'intérieur de `build_base_feature_pool`,
    # donc à partir de la version de `raw` qui lui est passée).
    raw[leak_col] = raw[target_col].shift(-shift_magnitude)
    raw_corrupted[leak_col] = raw_corrupted[target_col].shift(-shift_magnitude)

    prepared_orig, feat_orig = _prepare_fold(raw, config, fold_idx=0)
    prepared_corr, feat_corr = _prepare_fold(raw_corrupted, config, fold_idx=0)
    assert prepared_orig is not None and prepared_corr is not None
    assert feat_orig == feat_corr

    leak_idx = feat_orig.index(leak_col)
    col_o = prepared_orig.X_tr[:, leak_idx]
    col_c = prepared_corr.X_tr[:, leak_idx]
    detected = bool(np.any(np.abs(col_o - col_c) > 1e-8))

    if expect_detected:
        assert detected, (
            f"fuite shift={shift_magnitude} purge={purge_enabled} NON détectée alors qu'elle "
            f"devrait l'être (magnitude {shift_magnitude} vs horizon {horizon})."
        )
    else:
        assert not detected, (
            f"fuite shift={shift_magnitude} purge={purge_enabled} détectée alors que le purge "
            f"devrait la masquer (magnitude {shift_magnitude} <= horizon {horizon}) -- le seuil "
            f"documenté (masqué ssi magnitude <= horizon) a changé, à revérifier."
        )


@pytest.mark.xfail(
    strict=True,
    reason="Fuite CONFIRMÉE (pas un bug de ce test) : `egarch_conditional_vol` "
           "(patrick/features/vol_models.py) calcule la portion TEST via "
           "`am_full = arch_model(ret, ...); am_full.fix(...)` sur `ret` = LA SÉRIE "
           "COMPLÈTE (train+test+tout ce qui suit, pas juste jusqu'à la marge de "
           "label légitime). `arch` recalcule en interne, à partir de ce `ret` "
           "complet, le backcast et `variance_bounds` (statistiques GLOBALES type "
           "np.var/np.max sur tout l'array) qui influencent `conditional_volatility` "
           "même sur les lignes de TEST. Le docstring de la fonction documentait déjà "
           "ce canal pour le TRAIN (corrigé en isolant `res`, le fit train-only) mais "
           "ne traitait pas le TEST -- confirmé ici par ce test qui corrompt "
           "STRICTEMENT au-delà de la marge de label légitime (fin de fold de test + "
           "horizon) et observe un changement des colonnes *_egarch_vol sur le TEST. "
           "Kalman/HMM/AR/MA/ARMA/ARIMA (les autres modèles paramétriques du même "
           "module) sont des passes forward causales pures ou utilisent `.apply()` "
           "sans recalcul de statistiques globales -- non affectés, vérifié par "
           "inspection de code. Correction hors périmètre de cette session (nécessite "
           "de rendre le `.fix()` EGARCH incrémental/causal pour le TEST, ce qui casse "
           "le cache par coupure de fold documenté en tête de module) -- rapporté pour "
           "décision séparée, PAS corrigé ici (cf. rapport de session correction, C2.a). "
           "MàJ D2 : mesuré sur données réalistes (non adversariales), le canal est INERTE "
           "(variance_bounds ne clippe jamais, écart 0.0 vs référence causale, 3 graines) -- "
           "il ne s'active que sur des futurs ~100 000x hors échelle des rendements réels "
           "(comme la corruption de CE test). Recommandation N1 (tronquer la série à la fin "
           "du fold) mesurée gratuite en coût -- non appliquée ici, décision séparée.",
)
@pytest.mark.slow  # ~17s mesuré (rapport de correction, D1)
def test_corrupting_beyond_test_fold_does_not_change_test_features_or_predictions():
    """Rapport d'audit, C2.a — contrôle distinct de
    `test_corrupting_the_future_does_not_change_train_features_or_model` : ce
    dernier protège le TRAIN contre une fuite venant du futur, mais corrompt
    tout ce qui est >= cut_date, donc corrompt AUSSI la zone de test elle-même
    — il ne peut pas distinguer "le test a changé parce qu'il contient la
    corruption qu'on vient d'y injecter" de "le test a changé À CAUSE d'une
    fuite venant d'AU-DELÀ de sa propre fin" (ex. une feature calculée pour une
    ligne de test à la date t qui utiliserait des données à t+k avec k
    supérieur à la marge de purge/embargo -- invisible au test 0.2 principal).
    Ici, seules les données STRICTEMENT postérieures à la fin du fold de test
    sont corrompues : le test lui-même (et tout ce qui précède) reste
    bit-identique, donc toute divergence dans `X_te`/les prédictions ne peut
    venir que d'une fuite depuis au-delà du fold de test."""
    config = _make_config()
    raw = _synthetic_raw()
    all_dates = raw.index
    horizon = config.objective.horizons[0]
    fold_cuts = build_fold_cuts(all_dates, config.validation.n_wf_folds, config.validation.min_train_frac)
    cut_date = all_dates[fold_cuts[0]]
    nxt_idx = fold_cuts[1] - 1

    # La cible de la DERNIÈRE ligne de test a légitimement besoin du prix à
    # nxt_idx + horizon (`build_target` : `ret = s.shift(-horizon) / s - 1`) --
    # ce n'est pas une fuite, c'est ainsi qu'un label est construit. La marge à
    # corrompre doit donc commencer STRICTEMENT APRÈS cette borne légitime, pas
    # juste après la fin nominale du fold de test.
    boundary_idx = min(nxt_idx + horizon, len(all_dates) - 1)
    boundary_date = all_dates[boundary_idx]
    assert boundary_date < all_dates[-1], (
        "prérequis du test : il doit rester des données au-delà de la marge de label "
        "légitime (fin de fold de test + horizon) pour pouvoir les corrompre."
    )

    raw_corrupted = _corrupt_strictly_after(raw, boundary_date)
    assert raw.loc[raw.index <= boundary_date].equals(raw_corrupted.loc[raw_corrupted.index <= boundary_date]), (
        "prérequis : train+test+marge de label doivent être bit-identiques, seul l'au-delà "
        "de cette marge doit être corrompu -- sinon ce test ne prouve rien de plus que le "
        "0.2 principal (et confondrait le calcul légitime du label avec une fuite)."
    )

    prepared_orig, feat_orig = _prepare_fold(raw, config, fold_idx=0)
    prepared_corr, feat_corr = _prepare_fold(raw_corrupted, config, fold_idx=0)
    assert prepared_orig is not None and prepared_corr is not None
    assert feat_orig == feat_corr, "les deux pools doivent avoir les mêmes colonnes (mêmes noms)"

    X_te_o, y_te_o = prepared_orig.X_te, prepared_orig.y_te
    X_te_c, y_te_c = prepared_corr.X_te, prepared_corr.y_te
    np.testing.assert_array_equal(y_te_o, y_te_c)
    np.testing.assert_allclose(
        X_te_o, X_te_c, rtol=1e-8, atol=1e-10,
        err_msg="Le TEST a changé quand on a corrompu des données strictement postérieures à "
                "la fin de son propre fold -> fuite dans la construction des features de test "
                "(fenêtre/as-of join qui déborde au-delà du fold de test).",
    )

    # étend à la prédiction : un modèle entraîné sur le train (identique dans les
    # deux cas, cf. test 0.2 principal) doit produire des prédictions identiques
    # sur ce X_te identique -- pas seulement des features numériquement égales.
    X_tr_o, y_tr_o = prepared_orig.X_tr, prepared_orig.y_tr
    cols_o = list(_select(config, X_tr_o, y_tr_o, 5, seed=42))
    clf_o = get_classifier("RandomForest", seed=42)
    clf_o.fit(X_tr_o[:, cols_o], y_tr_o)
    np.testing.assert_array_equal(
        clf_o.predict(X_te_o[:, cols_o]), clf_o.predict(X_te_c[:, cols_o]),
        err_msg="Les prédictions sur le test diffèrent selon que l'au-delà du fold de test "
                "est corrompu ou non -> fuite.",
    )


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
    X_tr, y_tr, X_te, y_te = prepared.X_tr, prepared.y_tr, prepared.X_te, prepared.y_te

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
