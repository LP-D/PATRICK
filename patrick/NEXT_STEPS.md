# NEXT_STEPS — suite de l'optimisation des runs

Sprint 1 (mesure + non-régression) : fait, voir `benchmarks/benchmark_reference.md`.
Commande de comparaison avant/après : `python -m patrick.benchmark run` puis
`python -m patrick.benchmark compare benchmarks/baseline/walkforward <nouveau_dossier>`
(digests identiques attendus pour toute optimisation **exacte**).

## Sprint 2 — optimisations exactes

**Étape 1 faite** : pools paramétriques parallèles (`features/parametric_parallel.py`, activé par `PATRICK_PARAMETRIC_JOBS=N`, défaut 1 = code d'origine).
Mesuré (walk-forward, même machine, threads BLAS=4, jobs=2) : 559 s -> 479 s (-14 %), paramétriques 155 s -> 81 s (-48 %), CPU 853 s -> 632 s ;
digests des artefacts et compteurs **identiques** à la baseline (`benchmarks/sprint2_parametric_jobs2/`). Coût : pic RSS 525 Mo -> 1002 Mo.
Réglable depuis l'interface (page « Lancer » > Performance, `~/.patrick/settings.json`, relu à chaque run ; la variable d'environnement prime).
Non fait : défaut jobs>1, CPCV (un seul pool paramétrique : gain attendu faible), jobs=3/4 (nécessite de fixer les threads BLAS : comparer à part).

Proposition initiale des étapes (la 1 est faite) :

Critère commun : digests de `benchmarks/baseline/{walkforward,cpcv}` identiques, compteurs en baisse.
Ordre proposé (par gain attendu, hypothèses à confirmer) :

1. **Pools paramétriques par fold** (≈ 32 % WF, ≈ 7 % CPCV) : construction parallélisée de façon déterministe par (ticker, modèle, fold), avec `fit_end_idx`/`test_end_idx` inchangés, nombre de threads BLAS/OpenMP contrôlé, configuration résolue passée complète aux workers ; clé de cache = celle de `pool_cache` (aucun `id()`).
2. **Sélection SHAP** (≈ 28 % WF, ≈ 48 % CPCV) : le cache SQLite existant ne couvre que les répétitions exactes (40/70 en WF). Piste exacte : calculer le classement une fois par (données d'entraînement, graine) et en déduire les N de la grille (seulement si `select_features` est un préfixe du même classement : à vérifier par test, sinon méthodologique).
3. **`holdout_diagnostic` / `final_holdout` / tuning** : réutiliser les `FoldData` déjà préparés (PreparedFoldCache en mémoire, clé = (horizon, fold, régime, config)). Gain direct faible (≈ 2 s de temps propre pour `prepare`) mais évite de reconstruire/re-normaliser ; à faire APRÈS le point 1.
4. **Batching SQLite** : 1150 commits ≈ 3 s → gain négligeable à cette échelle, à reconsidérer sur un run réel.
5. **Cache de téléchargement** : non mesuré au Sprint 1 (données synthétiques hors ligne) ; à mesurer sur un vrai run avant toute décision.

## Idées hors Sprint 2 (méthodologiques, ne pas mélanger)

- Cheap screening / Top-K / budget Optuna réduit / profils FAST-STANDARD-FULL : changent le champion, à comparer à l'ancienne méthode.
- Élagage Optuna plus agressif : 39/80 essais déjà élagués.
- Réduction du nombre de sélections CPCV (60 distinctes) : méthodologique.

## Anomalies notées (à traiter séparément)

- `engine.run_pipeline` ne passe pas de `config_hash` indépendant du chemin : `config_hash` dépend de `output.dir`, donc les noms d'études Optuna changent avec le dossier de sortie (la reprise d'un run n'est possible que dans le même dossier).
- `SelectionCache` (SQLite) et `pool_cache` (disque) existent déjà : les « futurs caches » du brief doivent en tenir compte plutôt que les recréer.
