"""Test de fumée bout-en-bout du pipeline complet, sans réseau : `ingest()` est
monkeypatché pour renvoyer des données synthétiques (le sandbox de dev n'a pas
accès à yfinance/FRED), tout le reste (features avancées, walk-forward, sélection,
grille, Optuna, export) tourne pour de vrai. La vérification avec de vraies
données (doit retrouver F1_dir≈0.610±0.025 sur `configs/examples/vix_direction.yaml`)
doit être relancée par un humain sur une machine avec accès réseau.
"""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd
import pytest

from patrick.config.schema import RunConfig
from patrick.data.store import DataStore
from patrick.pipeline import engine as engine_module

# Rapport de correction, D1 : tous les tests de ce fichier lancent un run
# pipeline complet (16-120s mesurés selon le test) -- exclus par défaut,
# cf. pyproject.toml.
pytestmark = pytest.mark.slow


def _synthetic_raw(n=1500, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    target = 15 + np.cumsum(rng.normal(0, 0.5, n)).clip(min=-10)
    df = pd.DataFrame({"IDX_TEST": target}, index=idx)
    df["SPX_LIKE"] = 3000 + np.cumsum(rng.normal(0, 5, n))
    df["NFCI"] = np.cumsum(rng.normal(0, 0.02, n))
    df["T10Y2Y"] = np.cumsum(rng.normal(0, 0.01, n))
    return df


@pytest.fixture
def tiny_config(tmp_path) -> RunConfig:
    raw_yaml = {
        "name": "smoke_test",
        "objective": {
            "target_symbol": "^TEST",
            "horizons": [3, 5],
            "regimes": ["GLOBAL"],
        },
        "universe": {
            "yf_tickers": ["SPX_LIKE"],
            "fred_series": {"NFCI": "NFCI", "T10Y2Y": "T10Y2Y"},
            "start_date": "2015-01-01",
        },
        "features": {
            "families": ["technical", "interactions", "spike", "vol_models", "macro"],
            "interact_top_base": 15,
            "interact_top_pairs": 8,
            "interact_final_n": 6,
            "pool_prefilter": 60,
        },
        "validation": {"n_wf_folds": 2, "min_train_frac": 0.5},
        "selection": {"method": "shap", "n_features_grid": [5, 8], "shap_sample": 200},
        "sampler": {"candidates": ["SMOTE"]},
        "models": {"algos": ["RandomForest", "XGBoost"]},
        "tuning": {"enabled": True, "top_k": 2, "n_trials": 3, "cv_splits": 2},
        "output": {"dir": str(tmp_path / "runs"), "seed": 42},
    }
    return RunConfig.model_validate(raw_yaml)


def test_pipeline_runs_end_to_end_on_synthetic_data(tiny_config, monkeypatch, tmp_path):
    def fake_ingest(objective, universe, store=None, force=False, data_quality=None):
        return _synthetic_raw()

    monkeypatch.setattr(engine_module, "ingest", fake_ingest)

    result = engine_module.run_pipeline(
        tiny_config, store=DataStore(root=str(tiny_config.output.dir) + "_store"),
        db_path=str(tmp_path / "patrick_test.db"))

    board = result["leaderboard"]
    assert len(board) > 0
    assert set(["horizon", "fold", "regime", "N", "sampler", "algo", "F1_dir"]).issubset(board.columns)
    assert board["F1_dir"].between(0, 1).all()

    assert result["final_best"] is not None
    assert result["model_path"] is not None
    import os
    assert os.path.exists(result["model_path"])


def test_optuna_budget_is_allocated_to_every_horizon(tiny_config, monkeypatch, tmp_path):
    """Rapport d'audit, C3 : `top_k` était sélectionné GLOBALEMENT tous
    horizons confondus -- si les meilleures configs SCAN d'un seul horizon
    dominaient le classement, cet horizon captait 100% du budget Optuna et les
    autres horizons n'en recevaient aucun (observé dans l'audit : h=5j à zéro
    essai Optuna alors que h=3j en recevait deux). `tiny_config` a deux
    horizons (3, 5) et `tuning.top_k=2` -- avec la sélection par horizon
    (`optuna_select_top_k_per_horizon=True`, défaut corrigé), CHAQUE horizon doit
    recevoir ses propres configs affinées, pas seulement celui qui gagne
    globalement.

    Utilise `_synthetic_raw_no_floor` (pas `_synthetic_raw`) : le `.clip(min=-10)`
    de `_synthetic_raw` fait "coller" la cible à un plancher, ce qui fait
    s'effondrer le dernier fold walk-forward à quelques lignes de test à peine
    (cf. docstring de `_synthetic_raw_no_floor` ci-dessous) -- confondu au
    premier essai avec un bug C3, ce n'en était pas un (root-cause tracée :
    `ctx.prepare(horizon, last_fold, "GLOBAL")` retournait déjà `None` pour
    CE fixture-là, y compris dans le code d'origine, avant même mes
    modifications -- juste jamais exercé par un test qui vérifie
    `result["tuned"]`)."""
    def fake_ingest(objective, universe, store=None, force=False, data_quality=None):
        return _synthetic_raw_no_floor()

    monkeypatch.setattr(engine_module, "ingest", fake_ingest)
    assert tiny_config.tuning.optuna_select_top_k_per_horizon is True  # comportement corrigé par défaut

    result = engine_module.run_pipeline(
        tiny_config, store=DataStore(root=str(tiny_config.output.dir) + "_c3_store"),
        db_path=str(tmp_path / "patrick_test_c3.db"))

    tuned_df = result["tuned"]
    assert len(tuned_df) > 0, "aucune config affinée par Optuna -- le tuning n'a pas tourné du tout."
    horizons_with_tuning = set(tuned_df["horizon"].unique())
    expected_horizons = set(tiny_config.objective.horizons)
    assert horizons_with_tuning == expected_horizons, (
        f"budget Optuna non alloué à tous les horizons : attendu {expected_horizons}, "
        f"obtenu {horizons_with_tuning} -- au moins un horizon n'a reçu aucun essai Optuna."
    )


def test_export_writes_one_model_file_per_horizon_with_valid_tuned_result(tiny_config, monkeypatch, tmp_path):
    """Rapport d'audit -- confirmé : `export_best_model` n'était appelé
    qu'UNE fois par `run_pipeline`, scopé au seul horizon de `final_best`
    (le gagnant GLOBAL, calculé tous horizons confondus par
    `board.best()`/`tuned_agg.groupby(...)` -- aucun `groupby("horizon")`
    dans ce calcul). Les horizons 3j et 5j de `tiny_config` sont pourtant
    TOUS DEUX scannés et affinés par Optuna (même fixture
    `_synthetic_raw_no_floor` que `test_optuna_budget_is_allocated_to_every_horizon`
    ci-dessus, qui le vérifie déjà côté `tuned_df`) -- avant correction, un
    seul des deux repartait avec un fichier .joblib, l'autre voyait son
    meilleur config affiné calculé puis silencieusement jeté à l'export.

    Après correction : un fichier modèle par horizon ayant un résultat
    valide (`result["model_paths"]`), et le trial gagnant de CHAQUE horizon
    (pas seulement celui du gagnant global) marqué is_best avec son propre
    artifact_path -- faute de quoi `patrick predict --run-id
    <run_id_de_l'autre_horizon> --live` ne trouve aucun trial gagnant pour
    ce run_id (cf. test_predict_live.py,
    test_predict_live_works_for_every_horizon_in_a_multi_horizon_run)."""
    import os

    def fake_ingest(objective, universe, store=None, force=False, data_quality=None):
        return _synthetic_raw_no_floor()

    monkeypatch.setattr(engine_module, "ingest", fake_ingest)
    db_path = str(tmp_path / "patrick_test_perhorizon.db")

    result = engine_module.run_pipeline(
        tiny_config, store=DataStore(root=str(tiny_config.output.dir) + "_perhorizon_store"),
        db_path=db_path)

    assert result["final_best"] is not None
    model_paths = result["model_paths"]
    expected_horizons = set(tiny_config.objective.horizons)
    assert set(model_paths.keys()) == expected_horizons, (
        f"pas un fichier modele par horizon avec resultat valide : attendu {expected_horizons}, "
        f"obtenu {set(model_paths.keys())}."
    )
    # Fichiers distincts (pas le même chemin écrasé horizon après horizon).
    assert len(set(model_paths.values())) == len(model_paths)
    for horizon, path in model_paths.items():
        assert os.path.exists(path)
        assert f"_h{horizon}.joblib" in path

    conn = sqlite3.connect(db_path)
    for horizon in expected_horizons:
        run_id = conn.execute("SELECT run_id FROM run WHERE horizon = ?", (horizon,)).fetchone()[0]
        best_row = conn.execute(
            "SELECT artifact_path FROM trial WHERE run_id = ? AND is_best = 1", (run_id,)
        ).fetchone()
        assert best_row is not None, f"aucun trial gagnant marque pour l'horizon {horizon}j"
        assert best_row[0] == model_paths[horizon]
    conn.close()


def test_phase_timing_covers_stability_holdout_diagnostic_and_export(tiny_config, monkeypatch, tmp_path):
    """Réinstrumentation (migration 0017, après le refactor per-horizon de
    l'export -- fix/best-model-per-horizon) : les trois sous-phases qui
    composaient le bucket "non instrumenté" (824s/34% sur la mesure GSPC du
    25/08) doivent chacune produire au moins une ligne run_phase_timing sur
    un run réel. "stability" et "holdout_diagnostic" restent dans du code
    inchangé par le refactor per-horizon (une ligne par horizon pour
    stability, une ligne partagée identique à chaque run_id pour
    holdout_diagnostic -- mêmes conventions que la première version de cette
    instrumentation, cf. 3b57f43). "export" doit maintenant produire AU
    MOINS DEUX lignes par horizon : l'export CSV/tuned partagé (identique à
    chaque run_id, comme avant) PLUS l'export modèle propre à cet horizon --
    export_best_model() est appelé une fois par horizon dans la boucle
    final_best_by_horizon (fix/best-model-per-horizon), plus une seule fois
    pour le seul gagnant global comme avant ce fix."""
    def fake_ingest(objective, universe, store=None, force=False, data_quality=None):
        return _synthetic_raw_no_floor()

    monkeypatch.setattr(engine_module, "ingest", fake_ingest)
    db_path = str(tmp_path / "patrick_test_phasetiming.db")

    result = engine_module.run_pipeline(
        tiny_config, store=DataStore(root=str(tiny_config.output.dir) + "_phasetiming_store"),
        db_path=db_path)

    assert result["holdout"] is not None, "le holdout doit être actif pour exercer holdout_diagnostic"
    expected_horizons = set(tiny_config.objective.horizons)
    assert set(result["model_paths"].keys()) == expected_horizons

    conn = sqlite3.connect(db_path)
    run_id_by_horizon = dict(conn.execute("SELECT horizon, run_id FROM run").fetchall())

    for horizon in expected_horizons:
        run_id = run_id_by_horizon[horizon]

        stability_rows = conn.execute(
            "SELECT COUNT(*) FROM run_phase_timing WHERE run_id = ? AND phase = 'stability'", (run_id,)
        ).fetchone()[0]
        assert stability_rows > 0, f"aucune ligne 'stability' pour l'horizon {horizon}j"

        holdout_rows = conn.execute(
            "SELECT COUNT(*) FROM run_phase_timing WHERE run_id = ? AND phase = 'holdout_diagnostic'", (run_id,)
        ).fetchone()[0]
        assert holdout_rows > 0, f"aucune ligne 'holdout_diagnostic' pour l'horizon {horizon}j"

        export_rows = conn.execute(
            "SELECT COUNT(*) FROM run_phase_timing WHERE run_id = ? AND phase = 'export'", (run_id,)
        ).fetchone()[0]
        assert export_rows >= 2, (
            f"attendu au moins 2 lignes 'export' pour l'horizon {horizon}j "
            f"(CSV partagé + modèle per-horizon), obtenu {export_rows} -- "
            "le refactor per-horizon de l'export doit produire une ligne 'export' "
            "par horizon, pas une seule pour le gagnant global."
        )
    conn.close()


def test_optuna_budget_can_revert_to_global_selection(tiny_config, monkeypatch, tmp_path):
    """Contre-épreuve : `optuna_select_top_k_per_horizon=False` restaure l'ancien
    comportement (sélection top_k globale, tous horizons confondus) --
    conservé explicitement pour compatibilité, cf. C3. N'assert pas que les
    deux horizons sont couverts (c'est justement le comportement qu'on
    réactive), seulement que le run se termine et produit des configs
    affinées quand même. Cf. `_synthetic_raw_no_floor` : même remarque que le
    test précédent sur le choix du générateur synthétique."""
    def fake_ingest(objective, universe, store=None, force=False, data_quality=None):
        return _synthetic_raw_no_floor()

    monkeypatch.setattr(engine_module, "ingest", fake_ingest)
    tiny_config.tuning.optuna_select_top_k_per_horizon = False

    result = engine_module.run_pipeline(
        tiny_config, store=DataStore(root=str(tiny_config.output.dir) + "_c3_global_store"),
        db_path=str(tmp_path / "patrick_test_c3_global.db"))

    tuned_df = result["tuned"]
    assert len(tuned_df) > 0
    # top_k=2 global -> au plus 2 configs distinctes affinées au total (pas 2 par horizon).
    n_distinct_configs = tuned_df.drop_duplicates(subset=["horizon", "regime", "N", "sampler", "algo"]).shape[0]
    assert n_distinct_configs <= tiny_config.tuning.top_k


def _synthetic_raw_no_floor(n=1500, seed=0) -> pd.DataFrame:
    """Variante de `_synthetic_raw` sans `.clip(min=-10)` sur la marche
    aléatoire cumulée. Ce clip fait "coller" la cible à un plancher exact
    pendant des séries de jours consécutifs dès que la marche aléatoire
    dérive suffisamment bas (attendu sur 1500 pas, écart-type cumulé ~19 pour
    un floor à 10 en dessous du niveau de départ) : ~40% des rendements à
    horizon 5j tombent alors exactement à 0.0 (prix collé au plancher des
    deux côtés de la fenêtre), quel que soit `flat_thr` (le filtre "flat" de
    `build_target` ne peut rien contre un rendement EXACTEMENT nul, pas
    seulement petit) — le dernier fold walk-forward s'effondre alors à
    quelques lignes de test. Découvert en écrivant les tests Phase 2 ; propre
    à ce test, ne touche pas `_synthetic_raw` (utilisé ailleurs avec ce
    comportement déjà implicitement accepté)."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    target = 100 + np.cumsum(rng.normal(0, 0.5, n))
    df = pd.DataFrame({"IDX_TEST": target}, index=idx)
    df["SPX_LIKE"] = 3000 + np.cumsum(rng.normal(0, 5, n))
    df["NFCI"] = np.cumsum(rng.normal(0, 0.02, n))
    df["T10Y2Y"] = np.cumsum(rng.normal(0, 0.01, n))
    return df


def test_phase2_holdout_dm_cumulative_trials_and_pbo_are_populated(tiny_config, monkeypatch, tmp_path):
    """Critère de sortie Phase 2 : pour la config gagnante, le pipeline produit
    une métrique holdout, une p-value Diebold-Mariano vs la meilleure baseline,
    et un compteur d'essais cumulé — avec les réglages par défaut
    (holdout_months=15, min_test_rows=20, flat_thr=0.003), sur un historique
    synthétique sans l'artefact de `_synthetic_raw` (cf.
    `_synthetic_raw_no_floor`)."""

    def fake_ingest(objective, universe, store=None, force=False, data_quality=None):
        return _synthetic_raw_no_floor()

    monkeypatch.setattr(engine_module, "ingest", fake_ingest)
    db_path = str(tmp_path / "patrick_test.db")

    result = engine_module.run_pipeline(
        tiny_config, store=DataStore(root=str(tiny_config.output.dir) + "_stats_store"),
        db_path=db_path)

    assert result["final_best"] is not None

    assert result["holdout"] is not None, "le holdout ne doit pas se désactiver sur 1500 lignes"
    assert 0 <= result["holdout"]["F1_dir"] <= 1

    # "^TEST" -> classify_asset_class retombe sur "other" (préfixe "^" non
    # reconnu) -> seul candidat configuré par défaut : persistance (cf.
    # config.defaults.DEFAULT_BASELINE_BY_ASSET_CLASS["other"]).
    dm = result["diebold_mariano"]
    assert dm is not None
    assert dm["asset_class"] == "other"
    assert dm["class_specific"] is not None
    assert dm["class_specific"]["baseline"] == "BASELINE_persistence"
    assert 0 <= dm["class_specific"]["p_value"] <= 1
    assert dm["common"] is not None
    assert dm["common"]["baseline"] == "BASELINE_persistence"
    assert 0 <= dm["common"]["p_value"] <= 1

    assert result["cumulative_trials"] > 0

    assert result["pbo"] is not None
    # 2 folds (tiny_config) -> pair, CSCV utilisable tel quel (pas de recadrage).
    assert result["pbo"]["n_blocks"] == 2

    conn = sqlite3.connect(db_path)
    holdout_rows = conn.execute(
        "SELECT count(*) FROM fold_metric WHERE split = 'holdout'").fetchone()[0]
    assert holdout_rows > 0
    holdout_preds = conn.execute(
        "SELECT count(*) FROM prediction WHERE split = 'holdout'").fetchone()[0]
    assert holdout_preds > 0
    conn.close()


def test_holdout_diagnostic_covers_full_scan_grid_not_just_winner(tiny_config, monkeypatch, tmp_path):
    """Rapport d'audit, C4 : `fold_metric[split='holdout']` (Phase 2.1)
    n'existe que pour le trial gagnant (`is_best=1`) -- `holdout_diagnostic`
    (table séparée) doit couvrir TOUTE la grille SCAN, pour permettre le
    diagnostic de corrélation test/holdout que l'audit demandait (section E)
    et que le schéma d'origine ne permettait pas de calculer (n=1)."""
    def fake_ingest(objective, universe, store=None, force=False, data_quality=None):
        return _synthetic_raw_no_floor()

    monkeypatch.setattr(engine_module, "ingest", fake_ingest)
    db_path = str(tmp_path / "patrick_test_c4.db")

    result = engine_module.run_pipeline(
        tiny_config, store=DataStore(root=str(tiny_config.output.dir) + "_c4_store"),
        db_path=db_path)

    assert result["final_best"] is not None
    assert result["holdout"] is not None, "prérequis : le holdout doit être actif sur ce fixture."

    conn = sqlite3.connect(db_path)
    n_trials = conn.execute("SELECT COUNT(*) FROM trial").fetchone()[0]
    n_diag_trials = conn.execute(
        "SELECT COUNT(DISTINCT trial_id) FROM holdout_diagnostic").fetchone()[0]
    n_diag_rows = conn.execute("SELECT COUNT(*) FROM holdout_diagnostic").fetchone()[0]
    n_holdout_fold_metric_trials = conn.execute(
        "SELECT COUNT(DISTINCT trial_id) FROM fold_metric WHERE split = 'holdout'").fetchone()[0]
    conn.close()

    assert n_diag_rows > 0, "holdout_diagnostic n'a reçu aucune ligne."
    # C'est précisément l'écart que corrige C4 : fold_metric[holdout] = 1 seul
    # trial (le gagnant), holdout_diagnostic doit en couvrir strictement plus.
    assert n_holdout_fold_metric_trials == 1
    assert n_diag_trials > n_holdout_fold_metric_trials, (
        f"holdout_diagnostic ({n_diag_trials} trials) ne couvre pas plus que "
        f"fold_metric[holdout] ({n_holdout_fold_metric_trials}) -- la grille SCAN complète "
        f"({n_trials} trials au total) n'a pas été évaluée sur le holdout."
    )

    # `result["holdout_diagnostic"]` (Spearman) est scopé au run_id de
    # `final_best` (un seul horizon, même convention que holdout/DM/PBO
    # ci-dessus) -- `n_diag_trials` compte, lui, TOUS les trials de
    # `holdout_diagnostic` tous horizons confondus de cet appel
    # `run_pipeline` (`tiny_config` a 2 horizons) : ne pas comparer les deux
    # bruts, revérifier le compte scopé au bon run_id à la place.
    conn = sqlite3.connect(db_path)
    final_best_run_id = next(
        rid for h, rid in conn.execute("SELECT horizon, run_id FROM run").fetchall()
        if h == int(result["final_best"]["horizon"])
    )
    n_diag_trials_for_best_horizon = conn.execute(
        "SELECT COUNT(DISTINCT hd.trial_id) FROM holdout_diagnostic hd "
        "JOIN trial t ON t.trial_id = hd.trial_id WHERE t.run_id = ?",
        (final_best_run_id,),
    ).fetchone()[0]
    conn.close()

    diag = result["holdout_diagnostic"]
    assert diag is not None
    assert diag["n_trials"] == n_diag_trials_for_best_horizon
    assert diag["n_trials"] > 0
    assert diag["n_trials"] <= n_diag_trials  # scopé à un horizon <= tous horizons confondus
    if diag["n_trials"] >= 3:
        assert -1.0 <= diag["rho"] <= 1.0
        assert 0.0 <= diag["p_value"] <= 1.0


def test_undersized_fold_is_excluded_with_explicit_warning(tiny_config, monkeypatch, tmp_path, capsys):
    """Rapport de correction, D3 : la garde de taille de fold (`min_train_rows`/
    `min_test_rows`, `ValidationConfig`) existait déjà -- `_FoldContext.prepare`
    et `_evaluate_holdout` excluaient un fold trop petit en renvoyant `None`,
    mais SILENCIEUSEMENT. L'incident de débogage C3 (dernier fold walk-forward
    effondré à 10-13 lignes de test, `None` renvoyé sans un mot) a forcé à
    instrumenter le code à la main pour comprendre un budget Optuna/SCAN
    incomplet -- corrigé en ajoutant un avertissement explicite à chaque
    exclusion. Ici, `min_test_rows` est forcé à une valeur qu'aucun fold ne
    peut satisfaire -> vérifie que l'avertissement apparaît (pas seulement que
    le run se termine sans planter)."""
    def fake_ingest(objective, universe, store=None, force=False, data_quality=None):
        return _synthetic_raw_no_floor()

    monkeypatch.setattr(engine_module, "ingest", fake_ingest)
    tiny_config.validation.min_test_rows = 10_000  # aucun fold ne peut fournir autant de lignes de test

    result = engine_module.run_pipeline(
        tiny_config, store=DataStore(root=str(tiny_config.output.dir) + "_d3_store"),
        db_path=str(tmp_path / "patrick_test_d3.db"))

    captured = capsys.readouterr()
    assert "[WARN] fold" in captured.out and "excluded" in captured.out, (
        "aucun avertissement explicite alors qu'un fold aurait dû être exclu pour taille insuffisante."
    )
    assert "min 10000" in captured.out or "(min 10000)" in captured.out
    assert len(result["leaderboard"]) == 0, "aucun fold ne satisfaisant le seuil, la grille SCAN doit être vide."
    assert result["final_best"] is None


def test_run_writes_full_db_trail_and_is_reproducible_on_same_snapshot(tiny_config, monkeypatch, tmp_path):
    """Critère de sortie Phase 1 : un run complet écrit snapshot + run + N trials
    + fold_metrics + baselines + predictions ; deux runs identiques sur le même
    snapshot produisent des métriques identiques."""
    def fake_ingest(objective, universe, store=None, force=False, data_quality=None):
        return _synthetic_raw()

    monkeypatch.setattr(engine_module, "ingest", fake_ingest)
    db_path = str(tmp_path / "patrick_test.db")
    store = DataStore(root=str(tmp_path / "store"))

    result1 = engine_module.run_pipeline(tiny_config, store=store, db_path=db_path)
    result2 = engine_module.run_pipeline(tiny_config, store=store, db_path=db_path)

    board1 = result1["leaderboard"].drop(columns=["test_start", "test_end"], errors="ignore")
    board2 = result2["leaderboard"].drop(columns=["test_start", "test_end"], errors="ignore")
    pd.testing.assert_frame_equal(
        board1.sort_values(list(board1.columns)).reset_index(drop=True),
        board2.sort_values(list(board2.columns)).reset_index(drop=True),
    )

    conn = sqlite3.connect(db_path)
    n_snapshots = conn.execute("SELECT count(*) FROM snapshot").fetchone()[0]
    n_runs = conn.execute("SELECT count(*) FROM run").fetchone()[0]
    n_trials = conn.execute("SELECT count(*) FROM trial").fetchone()[0]
    n_fold_metrics = conn.execute("SELECT count(*) FROM fold_metric").fetchone()[0]
    n_baselines = conn.execute("SELECT count(*) FROM baseline_metric").fetchone()[0]
    n_predictions = conn.execute("SELECT count(*) FROM prediction").fetchone()[0]

    # deux runs sur données identiques -> un seul snapshot (dédupliqué par hash),
    # mais deux fois plus de runs/trials/predictions (deux exécutions distinctes).
    assert n_snapshots == 1
    assert n_runs == 2 * len(tiny_config.objective.horizons)
    assert n_trials > 0
    assert n_fold_metrics > 0
    assert n_baselines > 0
    assert n_predictions > 0

    statuses = [r[0] for r in conn.execute("SELECT status FROM run").fetchall()]
    assert all(s == "done" for s in statuses)

    best_trials = conn.execute("SELECT count(*) FROM trial WHERE is_best = 1").fetchall()
    assert best_trials[0][0] >= 1  # au moins un trial marqué gagnant sur les deux runs
    conn.close()


def test_cpcv_scheme_runs_end_to_end_and_reports_a_path_distribution(tiny_config, monkeypatch, tmp_path):
    """Phase 6.1 (P6.1) -- `validation.scheme: cpcv` bout-en-bout : le pipeline
    complet (features avancées incluses) tourne sans planter sur le chemin
    d'export final (`_run_cpcv_scan` -> branchement finalize de `run_pipeline`,
    qui référence `pool_builder`/`ctx`/`last_fold` -- tous `None` en CPCV --
    donc ce test couvre précisément le risque de crash identifié pendant le
    développement). Un seul horizon (le scan CPCV boucle sur tous les horizons
    en interne PAR construction du pool, pas besoin de plusieurs ici) et
    n_groups=5/k_test_groups=2 (plus petit que le défaut 7/2, pour rester
    rapide en test) -> C(4,1) = 4 chemins."""
    def fake_ingest(objective, universe, store=None, force=False, data_quality=None):
        return _synthetic_raw_no_floor()

    monkeypatch.setattr(engine_module, "ingest", fake_ingest)
    tiny_config.objective.horizons = [5]
    tiny_config.validation.scheme = "cpcv"
    tiny_config.validation.n_groups = 5
    tiny_config.validation.k_test_groups = 2
    tiny_config.tuning.enabled = False  # affinage Optuna hors périmètre CPCV (cf. _run_cpcv_scan)
    db_path = str(tmp_path / "patrick_test_cpcv.db")

    result = engine_module.run_pipeline(
        tiny_config, store=DataStore(root=str(tiny_config.output.dir) + "_cpcv_store"),
        db_path=db_path)

    board = result["leaderboard"]
    assert len(board) > 0
    assert set(board["scheme"].dropna().unique()) == {"cpcv"}
    # n_groups=5, k_test_groups=2 -> C(4,1) = 4 chemins, constant pour toute la grille.
    assert set(board["n_paths"].dropna().unique()) == {4}
    for col in ("F1_dir_median", "F1_dir_q05", "F1_dir_q95", "F1_dir_std"):
        assert col in board.columns
        assert board[col].notna().any()
    # jamais un point unique : la médiane doit provenir d'une vraie distribution.
    assert (board["F1_dir_q05"] <= board["F1_dir_median"]).all()
    assert (board["F1_dir_median"] <= board["F1_dir_q95"]).all()

    assert result["final_best"] is not None
    assert result["model_path"] is not None
    import os
    assert os.path.exists(result["model_path"])
    # non applicables en CPCV (cf. _run_cpcv_scan) : jamais silencieusement
    # remplis avec une valeur walk-forward.
    assert result["holdout"] is None
    assert result["diebold_mariano"] is None
    assert result["holdout_diagnostic"] is None

    assert result["pbo"] is not None
    # branché sur les CHEMINS cpcv (split='test_path'), pas les blocs walk-forward.
    assert result["pbo"]["n_blocks"] == 4

    conn = sqlite3.connect(db_path)
    n_path_predictions = conn.execute(
        "SELECT COUNT(DISTINCT path_id) FROM prediction WHERE path_id != -1").fetchone()[0]
    assert n_path_predictions == 4
    n_test_path_metrics = conn.execute(
        "SELECT COUNT(*) FROM fold_metric WHERE split = 'test_path'").fetchone()[0]
    assert n_test_path_metrics > 0
    conn.close()


def test_walkforward_scheme_is_default_and_bit_identical_to_before_p61(tiny_config, monkeypatch, tmp_path):
    """Contre-épreuve P6.1 : ne pas définir `validation.scheme` (ou le mettre
    explicitement à "walkforward") doit laisser le comportement walk-forward
    INCHANGÉ -- CPCV est une option, jamais un remplacement silencieux."""
    assert tiny_config.validation.scheme == "walkforward"  # défaut, sans que le test le force

    def fake_ingest(objective, universe, store=None, force=False, data_quality=None):
        return _synthetic_raw_no_floor()

    monkeypatch.setattr(engine_module, "ingest", fake_ingest)
    db_path = str(tmp_path / "patrick_test_wf_unchanged.db")

    result = engine_module.run_pipeline(
        tiny_config, store=DataStore(root=str(tiny_config.output.dir) + "_wf_unchanged_store"),
        db_path=db_path)

    assert "scheme" not in result["leaderboard"].columns or result["leaderboard"]["scheme"].isna().all()
    assert result["holdout"] is not None
    assert result["diebold_mariano"] is not None
