# Benchmark de référence PATRICK — Sprint 1 (mesure, aucune optimisation)

Généré le 2026-09-30T22:50:09+02:00 — commit `9edf5953be` (working tree modifié).

> Sections 1-3 : **mesuré / observé**. Section 4 : **hypothèses / recommandations** (non mesurées).

## 1. Configuration utilisée

Profil `reference` — dataset **synthétique** (graine 20260930) : 2600 jours ouvrés, 30 tickers + 6 séries macro + cible, `data_hash` = `f3fd02ef7273`.

| Paramètre | Valeur |
|---|---|
| Horizons | [1, 5] |
| Folds walk-forward | 4 |
| Grille N features | [6, 10, 14] |
| Algos | ['XGBoost', 'LightGBM', 'RandomForest', 'CatBoost'] |
| Samplers | ['SMOTE'] |
| Modèles de vol (paramétriques) | ['egarch', 'kalman', 'hmm'] |
| shap_sample / pool_prefilter | 300 / 200 |
| Holdout (mois) | 12 |
| Optuna | top_k=2 par horizon, n_trials=20, cv_splits=3 |
| CPCV | n_groups=5, k_test_groups=2 |
| Seed pipeline | 42 |
| Répétitions instrumentées | 2 |
| Threads (OMP/OPENBLAS/MKL/NUMEXPR) | 4 |
| Départ | à froid : snapshot, base SQLite, cache de features et dossier Optuna neufs à chaque run |

Snapshot rejoué via `run_pipeline(snapshot_id=...)` (chemin `patrick resume`) : aucun réseau. `download_ohlc` (Yahoo) remplacé par un no-op déterministe, comme le golden master.

## 2. Environnement

| Élément | Valeur |
|---|---|
| Plateforme | Windows-11-10.0.26340-SP0 |
| CPU | Intel64 Family 6 Model 189 Stepping 1, GenuineIntel |
| Cœurs logiques | 8 |
| Python | 3.12.7 |
| Env threads | {'OMP_NUM_THREADS': '4', 'OPENBLAS_NUM_THREADS': '4', 'MKL_NUM_THREADS': '4', 'NUMEXPR_NUM_THREADS': '4', 'VECLIB_MAXIMUM_THREADS': None, 'PATRICK_FEATURE_CACHE': None} |
| Pools BLAS/OpenMP | ['openblas:Haswell:4', 'openmp:None:4'] |
| Paquets | numpy 2.5.3, pandas 3.0.5, scipy 1.18.1, scikit-learn 1.9.0, xgboost 3.4.1, lightgbm 4.7.0, catboost 1.2.10, shap 0.52.0, numba 0.67.0, optuna 4.9.0, imbalanced-learn 0.14.2, statsmodels 0.15.0, arch 8.0.0, pykalman 0.11.2, hmmlearn 0.3.3, joblib 1.5.3, pyarrow 25.0.1, duckdb 1.5.5 |

## 3. Mesures

### Scénario `walkforward`

| Indicateur | Valeur |
|---|---|
| Durée totale (instrumentée, run de référence) | 478.8 s |
| Temps CPU process (somme threads) | 631.9 s (CPU/mural = 1.32) |
| Pic mémoire RSS (process + enfants) | 1002 MB |
| Temps hors phases instrumentées | 0.2 s (0.0%) |
| Durées des répétitions instrumentées | 482.5 s, 478.8 s |
| Run non instrumenté | non exécuté |
| Run de référence des phases | rep2 |

**Durée par phase**

| Phase | Mural (s) | % total | CPU (s) | Pic RSS (MB) | Occurrences |
|---|---|---|---|---|---|
| scan_walkforward | 270.79 | 56.6% | 393.88 | 983 | 1 |
| holdout_diagnostic | 79.25 | 16.6% | 109.94 | 985 | 1 |
| tuning | 73.55 | 15.4% | 74.59 | 949 | 1 |
| export_models | 28.16 | 5.9% | 31.06 | 1002 | 1 |
| walkforward_prepare | 19.48 | 4.1% | 14.98 | 959 | 1 |
| base_feature_pool | 5.78 | 1.2% | 5.75 | 880 | 1 |
| final_holdout | 0.60 | 0.1% | 0.59 | 930 | 1 |
| champion_duel | 0.60 | 0.1% | 0.59 | 943 | 1 |
| final_diebold_mariano | 0.20 | 0.0% | 0.20 | 930 | 1 |
| export_tables | 0.06 | 0.0% | 0.05 | 917 | 1 |
| register_runs | 0.05 | 0.0% | 0.03 | 878 | 1 |
| select_finals | 0.02 | 0.0% | 0.03 | 916 | 1 |
| ingestion | 0.02 | 0.0% | 0.02 | 871 | 1 |
| final_stats | 0.02 | 0.0% | 0.05 | 917 | 3 |
| stability | 0.02 | 0.0% | 0.02 | 909 | 1 |
| finish_runs | 0.01 | 0.0% | 0.00 | 917 | 1 |

**Compteurs (totaux du run)**

| Compteur | Valeur |
|---|---|
| download_ohlc.calls | 1 |
| feature_pool_cache.base.miss | 1 |
| feature_pool_cache.parametric.miss | 6 |
| fit_eval_full.calls | 138 |
| fold_context.prepare | 29 |
| fold_pool_builder.get | 56 |
| interactions.apply | 6 |
| models.constructed | 138 |
| optuna.cv_fits | 166 |
| optuna.studies | 4 |
| optuna.trials.complete | 41 |
| optuna.trials.pruned | 39 |
| parametric_pool.builds | 6 |
| scaler.fit_transform | 57 |
| scaler.transform | 112 |
| select.calls | 70 |
| select_features.computed | 30 |
| selection_cache.hit | 40 |
| selection_cache.miss | 30 |
| sqlite.commit | 1150 |
| sqlite.execute | 1812 |
| sqlite.executemany | 268 |
| vol_model_cache.miss | 666 |

**Composants (temps exclusif cumulé, toutes phases)**

| Composant | Appels | Exclusif (s) | % total | Inclusif (s) |
|---|---|---|---|---|
| select_features.compute | 30 | 179.83 | 37.6% | 179.83 |
| fit_eval_full | 138 | 118.22 | 24.7% | 118.23 |
| feature_pool.compute[parametric] | 6 | 80.69 | 16.9% | 81.23 |
| optuna.tune_config | 4 | 63.48 | 13.3% | 63.52 |
| interactions.discover | 1 | 6.20 | 1.3% | 6.21 |
| feature_pool.compute[base] | 1 | 5.63 | 1.2% | 5.63 |
| scaler.fit_transform | 57 | 3.22 | 0.7% | 3.53 |
| fold_context.prepare | 29 | 1.46 | 0.3% | 44.36 |
| sqlite.commit | 1150 | 1.03 | 0.2% | 1.03 |
| compute_baselines | 35 | 0.92 | 0.2% | 0.92 |
| build_target | 56 | 0.67 | 0.1% | 0.67 |
| select.xy_data_hash | 70 | 0.40 | 0.1% | 0.40 |
| scaler.transform | 112 | 0.34 | 0.1% | 0.34 |
| parametric_pool.build | 6 | 0.22 | 0.0% | 81.45 |
| uniqueness.average | 29 | 0.18 | 0.0% | 0.18 |
| sqlite.executemany | 268 | 0.17 | 0.0% | 0.17 |
| sqlite.execute | 1812 | 0.10 | 0.0% | 0.10 |
| interactions.apply | 6 | 0.02 | 0.0% | 0.02 |

**Composants par phase (top 6 par phase, exclusif)**

- `scan_walkforward` (270.8 s): select_features.compute 141.4s (x24); fit_eval_full 86.6s (x96); feature_pool.compute[parametric] 40.2s (x3); fold_context.prepare 0.8s (x8); sqlite.commit 0.6s (x599); scaler.fit_transform 0.4s (x8)
- `holdout_diagnostic` (79.2 s): select_features.compute 38.4s (x6); fit_eval_full 23.0s (x24); feature_pool.compute[parametric] 13.9s (x1); scaler.fit_transform 1.5s (x24); compute_baselines 0.6s (x24); build_target 0.3s (x24)
- `tuning` (73.5 s): optuna.tune_config 63.5s (x4); fit_eval_full 7.7s (x16); scaler.fit_transform 1.0s (x20); fold_context.prepare 0.6s (x20); build_target 0.2s (x20); uniqueness.average 0.1s (x20)
- `export_models` (28.2 s): feature_pool.compute[parametric] 13.5s (x1); scaler.fit_transform 0.1s (x2); sqlite.commit 0.1s (x139); parametric_pool.build 0.0s (x1); scaler.transform 0.0s (x2); sqlite.execute 0.0s (x250)
- `walkforward_prepare` (19.5 s): feature_pool.compute[parametric] 13.1s (x1); interactions.discover 6.2s (x1); sqlite.commit 0.1s (x113); parametric_pool.build 0.0s (x1); build_target 0.0s (x1); sqlite.execute 0.0s (x224)

**Recalculs observés** (appels vs clés distinctes)

| Quantité | Appels | Clés distinctes | Redondance |
|---|---|---|---|
| fold_context.prepare | 29 | 8 | 21 appels répétés |
| selection_cache.lookup | 70 | 30 | 40 appels répétés |

**Résultats du run**

| Élément | Valeur |
|---|---|
| Lignes leaderboard | 160 |
| Lignes Optuna re-évaluées (tuned) | 16 |
| Trials SQLite (grille + configs tunées) | 28 |
| Lignes fold_metric | 1322 |
| Lignes prediction | 25680 |
| Features distinctes retenues (leaderboard) | 68 |
| Colonnes base pool | 653 |
| Colonnes pool du dernier fold (base+param+interactions) | 813 |
| Champion | {'horizon': 1, 'regime': 'GLOBAL', 'N': 10, 'sampler': 'SMOTE', 'algo': 'XGBoost', 'F1_dir': 0.628725, 'n_folds': 4} |

**Reproductibilité**

- même `data_hash`: True ; même config: True ; même seed: True
- digests des artefacts identiques entre répétitions: True
- compteurs (calls/hit/miss/trials) identiques entre répétitions: True
- résultats identiques avec/sans instrumentation: None

## 3b. Non-régression : artefacts sauvegardés

Répertoire `benchmarks/baseline/<schéma>/` (pleine précision, digests arrondis à 10 décimales dans `digests.json`) : `baseline_metrics.csv`, `dm_results.csv`, `exported_models.json`, `feature_stability.csv`, `fold_metrics.csv`, `holdout_diagnostic.csv`, `leaderboard.csv`, `optuna_trials.csv`, `predictions.csv`, `result_summary.json`, `run_rows.csv`, `trial_registry.csv`, `tuned.csv`.

**Absent / non disponible** (non reconstruit, le pipeline ne le persiste pas) :

- Probabilités complètes par classe : seuls `y_proba` (probabilité de la classe prédite) et `p_up` sont persistés.
- Prédictions des essais Optuna internes (CV interne) : seuls les scores/paramètres existent (`optuna_trials.csv`) ; les prédictions ne sont persistées que pour le ré-entraînement de la config tunée sur chaque fold.
- Modèle exporté : le fichier joblib n'est pas comparé octet à octet ; on compare ses features et ses `predict_proba` sur une matrice fixe (`exported_models.json`).
- Le champion « duel » (`champion_duel`) écrit dans la base/dossier de modèles du run isolé : sa décision est dans `result_summary.json`.

## 3c. Impossible à mesurer / limites

- `config_hash` du moteur inclut `output.dir` (chemin) : il varie d'un espace de travail à l'autre et est donc exclu des artefacts comparés (`config_digest` du benchmark l'exclut aussi). Noms d'études Optuna normalisés pour la même raison.
- Téléchargement (Yahoo/FRED) et ingestion réseau : NON mesurés (snapshot rejoué hors ligne). `ingestion` = lecture parquet du snapshot.
- Dataset synthétique, pas ^GSPC : les proportions entre phases dépendent de la taille de l'univers et de la grille ; à confirmer sur un run réel avant de fixer des seuils (le module accepte un autre profil).
- CPU = `time.process_time()` du process (somme des threads, hors processus enfants) ; les workers loky éventuels ne sont pas comptés en CPU (leur RSS l'est dans le pic mémoire).
- Pic mémoire = échantillonnage RSS à 20 Hz : un pic plus court que 50 ms peut être manqué.
- `models.constructed` compte les appels à `get_classifier` ; le RandomForest « bootstrap séquentiel » est instancié directement dans `_fit_eval_full` et n'y figure pas : `fit_eval_full.calls` est le décompte exact des entraînements de la grille/re-évaluation.
- Les fits internes à Optuna sont comptés par `optuna.cv_fits` (un par split de CV interne et par essai non élagué).
- Le temps SQLite mesure `execute`/`executemany`/`commit` de la connexion du pipeline ; le stockage propre d'Optuna (`optuna.db`) est inclus dans `optuna.tune_config`, non séparé.
- Le décompte de « features calculées » = colonnes du base pool + colonnes des pools paramétriques construits ; avec le cache disque les colonnes ne sont pas recalculées (voir hits/miss).

## 4. Hypothèses et recommandations (non mesuré)

_(aucune note fournie)_
