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
