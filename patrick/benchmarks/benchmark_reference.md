# Benchmark de référence PATRICK — Sprint 1 (mesure, aucune optimisation)

Généré le 2026-09-30T22:31:53+02:00 — commit `96d772f76f` (working tree modifié).

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
| Répétitions instrumentées | 3 |
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

### Scénario `cpcv`

| Indicateur | Valeur |
|---|---|
| Durée totale (instrumentée, run de référence) | 1513.1 s |
| Temps CPU process (somme threads) | 2261.0 s (CPU/mural = 1.49) |
| Pic mémoire RSS (process + enfants) | 442 MB |
| Temps hors phases instrumentées | 0.5 s (0.0%) |
| Durées des répétitions instrumentées | 1513.1 s, 1402.5 s |
| Run non instrumenté | 1982.1 s -> surcoût instrumentation non mesurable (bruit >> surcoût, voir note) |
| Run de référence des phases | rep1 |

**Durée par phase**

| Phase | Mural (s) | % total | CPU (s) | Pic RSS (MB) | Occurrences |
|---|---|---|---|---|---|
| scan_cpcv | 1447.10 | 95.6% | 2167.36 | 442 | 1 |
| export_models | 38.34 | 2.5% | 69.03 | 436 | 1 |
| base_feature_pool | 26.39 | 1.7% | 23.61 | 319 | 1 |
| register_runs | 0.24 | 0.0% | 0.17 | 308 | 1 |
| export_tables | 0.13 | 0.0% | 0.08 | 330 | 1 |
| final_stats | 0.07 | 0.0% | 0.06 | 360 | 2 |
| ingestion | 0.07 | 0.0% | 0.05 | 300 | 1 |
| finish_runs | 0.06 | 0.0% | 0.05 | 360 | 1 |
| select_finals | 0.06 | 0.0% | 0.05 | 330 | 1 |
| final_diebold_mariano | 0.04 | 0.0% | 0.03 | 360 | 1 |
| holdout_diagnostic | 0.03 | 0.0% | 0.03 | 330 | 1 |
| champion_duel | 0.03 | 0.0% | 0.02 | 360 | 1 |
| stability | 0.02 | 0.0% | 0.02 | 330 | 1 |
| final_holdout | 0.02 | 0.0% | 0.02 | 360 | 1 |
| tuning | 0.02 | 0.0% | 0.02 | 330 | 1 |

**Compteurs (totaux du run)**

| Compteur | Valeur |
|---|---|
| download_ohlc.calls | 1 |
| feature_pool_cache.base.miss | 1 |
| feature_pool_cache.parametric.miss | 1 |
| fit_eval_full.calls | 240 |
| interactions.apply | 1 |
| models.constructed | 240 |
| parametric_pool.builds | 1 |
| scaler.fit_transform | 242 |
| scaler.transform | 482 |
| select.calls | 240 |
| select_features.computed | 60 |
| selection_cache.hit | 180 |
| selection_cache.miss | 60 |
| sqlite.commit | 689 |
| sqlite.execute | 796 |
| sqlite.executemany | 432 |
| vol_model_cache.miss | 111 |

**Composants (temps exclusif cumulé, toutes phases)**

| Composant | Appels | Exclusif (s) | % total | Inclusif (s) |
|---|---|---|---|---|
| select_features.compute | 60 | 703.66 | 46.5% | 703.66 |
| fit_eval_full | 240 | 557.34 | 36.8% | 557.35 |
| feature_pool.compute[parametric] | 1 | 108.59 | 7.2% | 109.79 |
| scaler.fit_transform | 242 | 38.18 | 2.5% | 40.14 |
| feature_pool.compute[base] | 1 | 25.89 | 1.7% | 25.89 |
| interactions.discover | 1 | 11.91 | 0.8% | 11.95 |
| sqlite.commit | 689 | 7.56 | 0.5% | 7.56 |
| sqlite.executemany | 432 | 4.14 | 0.3% | 4.14 |
| scaler.transform | 482 | 3.19 | 0.2% | 3.19 |
| select.xy_data_hash | 240 | 1.99 | 0.1% | 1.99 |
| sqlite.execute | 796 | 0.34 | 0.0% | 0.34 |
| parametric_pool.build | 1 | 0.13 | 0.0% | 109.92 |
| build_target | 3 | 0.12 | 0.0% | 0.12 |
| select (cache lookup + compute) | 240 | 0.04 | 0.0% | 706.17 |
| interactions.apply | 1 | 0.01 | 0.0% | 0.01 |
| selection_cache.lookup | 240 | 0.01 | 0.0% | 0.06 |
| get_classifier.engine | 240 | 0.01 | 0.0% | 0.01 |
| vol_model_cache.lookup | 111 | 0.00 | 0.0% | 0.02 |

**Composants par phase (top 6 par phase, exclusif)**

- `scan_cpcv` (1447.1 s): select_features.compute 703.7s (x60); fit_eval_full 557.3s (x240); feature_pool.compute[parametric] 108.6s (x1); scaler.fit_transform 37.8s (x240); interactions.discover 11.9s (x1); sqlite.commit 7.5s (x653)
- `export_models` (38.3 s): scaler.fit_transform 0.4s (x2); sqlite.commit 0.0s (x24); sqlite.execute 0.0s (x24); scaler.transform 0.0s (x2)

**Recalculs observés** (appels vs clés distinctes)

| Quantité | Appels | Clés distinctes | Redondance |
|---|---|---|---|
| selection_cache.lookup | 240 | 60 | 180 appels répétés |

**Résultats du run**

| Élément | Valeur |
|---|---|
| Lignes leaderboard | 24 |
| Lignes Optuna re-évaluées (tuned) | 0 |
| Trials SQLite (grille + configs tunées) | 24 |
| Lignes fold_metric | 3072 |
| Lignes prediction | 195504 |
| Features distinctes retenues (leaderboard) | 0 |
| Colonnes base pool | 653 |
| Colonnes pool du dernier fold (base+param+interactions) | n/a |
| Champion | {'F1_dir': 0.6009500000000001, 'N': 6, 'algo': 'RandomForest', 'horizon': 1, 'n_folds': 1, 'regime': 'GLOBAL', 'sampler': 'SMOTE'} |

**Reproductibilité**

- même `data_hash`: True ; même config: True ; même seed: True
- digests des artefacts identiques entre répétitions: True
- compteurs (calls/hit/miss/trials) identiques entre répétitions: True
- résultats identiques avec/sans instrumentation: True

**Run « cache de features tiède »** (même snapshot, cache disque des pools conservé, base SQLite neuve): 1335.6 s (vs 1513.1 s à froid). Cache de pools : feature_pool_cache.base.hit=1, feature_pool_cache.parametric.hit=1

### Scénario `walkforward`

| Indicateur | Valeur |
|---|---|
| Durée totale (instrumentée, run de référence) | 559.1 s |
| Temps CPU process (somme threads) | 853.5 s (CPU/mural = 1.53) |
| Pic mémoire RSS (process + enfants) | 525 MB |
| Temps hors phases instrumentées | 0.2 s (0.0%) |
| Durées des répétitions instrumentées | 570.2 s, 559.1 s, 565.8 s |
| Run non instrumenté | 514.1 s -> surcoût instrumentation +8.7% |
| Run de référence des phases | rep2 |

**Durée par phase**

| Phase | Mural (s) | % total | CPU (s) | Pic RSS (MB) | Occurrences |
|---|---|---|---|---|---|
| scan_walkforward | 309.53 | 55.4% | 504.95 | 520 | 1 |
| holdout_diagnostic | 94.95 | 17.0% | 148.69 | 518 | 1 |
| tuning | 74.80 | 13.4% | 75.55 | 496 | 1 |
| export_models | 40.80 | 7.3% | 66.75 | 525 | 1 |
| walkforward_prepare | 31.41 | 5.6% | 50.08 | 487 | 1 |
| base_feature_pool | 5.80 | 1.0% | 5.75 | 412 | 1 |
| final_holdout | 0.60 | 0.1% | 0.61 | 475 | 1 |
| champion_duel | 0.58 | 0.1% | 0.58 | 468 | 1 |
| final_diebold_mariano | 0.19 | 0.0% | 0.17 | 464 | 1 |
| export_tables | 0.06 | 0.0% | 0.05 | 450 | 1 |
| register_runs | 0.06 | 0.0% | 0.05 | 402 | 1 |
| final_stats | 0.02 | 0.0% | 0.03 | 450 | 3 |
| ingestion | 0.02 | 0.0% | 0.02 | 401 | 1 |
| stability | 0.02 | 0.0% | 0.02 | 442 | 1 |
| select_finals | 0.02 | 0.0% | 0.02 | 449 | 1 |
| finish_runs | 0.01 | 0.0% | 0.00 | 450 | 1 |

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
| select_features.compute | 30 | 183.65 | 32.9% | 183.65 |
| feature_pool.compute[parametric] | 6 | 155.36 | 27.8% | 156.82 |
| fit_eval_full | 138 | 118.31 | 21.2% | 118.31 |
| optuna.tune_config | 4 | 64.49 | 11.5% | 64.54 |
| interactions.discover | 1 | 6.07 | 1.1% | 6.08 |
| feature_pool.compute[base] | 1 | 5.64 | 1.0% | 5.64 |
| scaler.fit_transform | 57 | 3.31 | 0.6% | 3.61 |
| sqlite.commit | 1150 | 1.84 | 0.3% | 1.84 |
| fold_context.prepare | 29 | 1.30 | 0.2% | 81.13 |
| compute_baselines | 35 | 0.95 | 0.2% | 0.95 |
| build_target | 56 | 0.69 | 0.1% | 0.69 |
| select.xy_data_hash | 70 | 0.40 | 0.1% | 0.40 |
| scaler.transform | 112 | 0.34 | 0.1% | 0.34 |
| parametric_pool.build | 6 | 0.31 | 0.1% | 157.13 |
| sqlite.execute | 1812 | 0.24 | 0.0% | 0.24 |
| uniqueness.average | 29 | 0.17 | 0.0% | 0.17 |
| sqlite.executemany | 268 | 0.15 | 0.0% | 0.15 |
| interactions.apply | 6 | 0.04 | 0.0% | 0.04 |

**Composants par phase (top 6 par phase, exclusif)**

- `scan_walkforward` (309.5 s): select_features.compute 144.0s (x24); fit_eval_full 86.0s (x96); feature_pool.compute[parametric] 76.5s (x3); sqlite.commit 1.0s (x599); fold_context.prepare 0.6s (x8); scaler.fit_transform 0.4s (x8)
- `holdout_diagnostic` (95.0 s): select_features.compute 39.7s (x6); feature_pool.compute[parametric] 27.5s (x1); fit_eval_full 23.4s (x24); scaler.fit_transform 1.6s (x24); compute_baselines 0.7s (x24); build_target 0.3s (x24)
- `tuning` (74.8 s): optuna.tune_config 64.5s (x4); fit_eval_full 8.0s (x16); scaler.fit_transform 1.0s (x20); fold_context.prepare 0.6s (x20); build_target 0.2s (x20); uniqueness.average 0.1s (x20)
- `export_models` (40.8 s): feature_pool.compute[parametric] 26.3s (x1); sqlite.commit 0.2s (x139); scaler.fit_transform 0.1s (x2); parametric_pool.build 0.0s (x1); sqlite.execute 0.0s (x250); scaler.transform 0.0s (x2)
- `walkforward_prepare` (31.4 s): feature_pool.compute[parametric] 25.0s (x1); interactions.discover 6.1s (x1); sqlite.commit 0.2s (x113); parametric_pool.build 0.0s (x1); sqlite.execute 0.0s (x224); build_target 0.0s (x1)

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
- résultats identiques avec/sans instrumentation: True

## 3b. Non-régression : artefacts sauvegardés

Répertoire `benchmarks/baseline/<schéma>/` (pleine précision, digests arrondis à 10 décimales dans `digests.json`) : `baseline_metrics.csv`, `dm_results.csv`, `exported_models.json`, `feature_stability.csv`, `fold_metrics.csv`, `holdout_diagnostic.csv`, `leaderboard.csv`, `predictions.csv`, `result_summary.json`, `run_rows.csv`, `trial_registry.csv`, `tuned.csv`.

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

Tout ce qui suit est **hypothèse ou recommandation**, à valider par comparaison avant/après ; rien n'a été implémenté au Sprint 1.

**Constats chiffrés sur lesquels s'appuient les hypothèses** (run walk-forward de référence, 838,9 s ; CPCV 1513 s) :

- Walk-forward : features paramétriques (`feature_pool.compute[parametric]`, 6 constructions) ≈ 272 s (≈ 32 %) ; sélection SHAP calculée 30 fois ≈ 235 s (≈ 28 %) ; `_fit_eval_full` 138 fois ≈ 182 s (≈ 22 %) ; Optuna ≈ 91 s (≈ 11 %, 41 essais complets + 39 élagués, 166 fits de CV) ; SQLite (1150 commits) ≈ 3 s (< 1 %).
- CPCV : sélection SHAP calculée 60 fois ≈ 704 s (≈ 48 %) ; 240 fits ≈ 557 s (≈ 38 %) ; features paramétriques ≈ 109 s (1 construction).
- `_FoldContext.prepare` : 29 appels pour 8 clés (horizon, fold, régime) distinctes ; `_select` : 70 appels pour 30 sélections distinctes (40 déjà servies par le cache SQLite existant, 180/240 en CPCV).
- Le cache disque des pools existe déjà (`pool_cache`) : tous les accès sont des *miss* à froid, tous des *hit* au second run (6/6 paramétriques, 1/1 base).
- `vol_model_cache` : 666 *miss* à froid (le cache SQLite n'aide qu'un second run sur le même snapshot).
- Mémoire faible (pic ≈ 530 Mo) : la mise en cache en mémoire des folds préparés ne devrait pas poser de problème de RAM à cette taille.

**Hypothèses (non mesurées)**

1. `holdout_diagnostic` (133 s, 16 % du walk-forward) ré-exécute préparation, sélection et fits sur des données déjà vues par le scan : une partie est vraisemblablement récupérable sans changer un résultat (préparation de fold déjà faite, sélections en cache). À vérifier par digest identique.
2. Les 21 appels `prepare` redondants ne pèsent que ≈ 2 s en temps propre (le coût de `prepare` est dominé par la construction paresseuse du pool paramétrique, déjà attribuée à `feature_pool.compute[parametric]`). Un `PreparedFoldCache` seul rapportera donc peu ; le gain est dans les pools paramétriques et la sélection.
3. Le coût paramétrique (egarch/kalman/hmm par fold) se prête à la parallélisation déterministe par (ticker, modèle, fold) ; pas de gain attendu sur SQLite ni sur le scaler.
4. En CPCV, la sélection SHAP domine : 60 calculs pour 240 lookups. Toute réduction du nombre de sélections distinctes est méthodologique (hors Sprint 2 exact).
5. Le temps mural est extrêmement bruité sur cette machine (515 s à 5095 s pour le même run) : les comparaisons de sprints doivent se faire sur les **compteurs** et le **temps CPU**, avec plusieurs répétitions et la médiane ou le minimum, jamais sur un seul temps mural.

**Recommandations pour le Sprint 2 (optimisations exactes uniquement)** : voir `NEXT_STEPS.md`.
