# Architecture PATRICK

Vue d'ensemble technique du pipeline et du produit, à jour au 2026-09-05
(HEAD `main` = `fbd354b`). Objectif : permettre à une future session de
comprendre l'organisation du code sans refaire un audit complet depuis zéro.
Pour le contexte produit/décisions historiques, voir `PRODUCT.md`,
`METHODOLOGY.md`, `DESIGN.md` — ce document est structurel, pas narratif.

> Note : `README.md` décrit un état ancien du projet (univers VIX/AAPL
> uniquement, pas de webapp) et n'est plus à jour. Se fier à ce document et au
> code pour l'état courant.

## Table des matières

1. [Layout du dépôt](#1-layout-du-dépôt)
2. [Flux de données de bout en bout](#2-flux-de-données-de-bout-en-bout)
3. [Organisation du code](#3-organisation-du-code)
4. [Le pipeline walk-forward en détail](#4-le-pipeline-walk-forward-en-détail)
5. [Persistance (SQLite `patrick.db`)](#5-persistance-sqlite-patrickdb)
6. [Application web](#6-application-web)
7. [Conventions clés](#7-conventions-clés)
8. [Points d'entrée CLI](#8-points-dentrée-cli)

## 1. Layout du dépôt

Dépôt **imbriqué** — ne pas confondre les deux racines :

```
C:\Users\leonp\PATRICK\              <- racine git (outer)
└── patrick\                         <- racine du package Python (inner)
    ├── patrick\                     <- code source (import patrick...)
    ├── tests\                       <- suite pytest
    ├── configs\                     <- YAML d'exemple + configs instrumentées
    ├── pyproject.toml
    └── .venv\                       <- venv LOCAL à ce checkout
```

**Piège d'environnement critique** : un `python`/`pip` global installé en
mode éditable peut pointer vers un checkout différent (un autre worktree/
branche). Toujours utiliser `patrick/.venv/Scripts/python.exe` (Windows) du
checkout courant, avec le répertoire de travail sur `patrick/` (là où se
trouve `pyproject.toml`) — sinon `import patrick` résout silencieusement le
mauvais code.

`pyproject.toml` fixe `addopts = "-m 'not slow'"` : un `pytest -q` nu exclut
les tests lents (CPCV/holdout/Diebold-Mariano/PBO). Utiliser `-m ""` pour la
suite complète, `-m "slow"` pour les tests lents seuls.

La base de tracking SQLite est **partagée entre tous les worktrees**,
`~/.patrick/patrick.db` (pas un fichier par checkout) — attention en testant
plusieurs branches en parallèle : toujours utiliser
`monkeypatch.setenv("PATRICK_DB_PATH", ...)` dans les tests pour ne jamais
toucher la vraie base.

## 2. Flux de données de bout en bout

```mermaid
flowchart LR
    A[Sources externes\nyfinance / FRED] -->|ingest| B[Data lake local\nParquet, ~/.patrick/store]
    B --> C[Feature engineering\npatrick/features/*]
    C --> D[Pool de features\nbase + paramétrique par fold]
    D --> E[Sélection SHAP\npatrick/selection/*]
    E --> F[Grid search\nsampler × n_features × algo]
    F --> G[Tuning Optuna\npatrick/tuning/*]
    G --> H[Validation\nwalk-forward / CPCV\npurge, embargo, DM, PBO, FDR]
    H --> I[Export du meilleur modèle\npar (cible, horizon)]
    I --> J[Tracking SQLite\npatrick.db]
    J --> K[Webapp FastAPI\nCockpit v2]
    I --> L[patrick predict --live\nprédiction quotidienne]
    L --> J
```

Chaque run traite **une cible, potentiellement plusieurs horizons** en un
seul appel (`patrick run --config ...`). L'univers de features est
« tout sauf la cible » (`webapp/forms.py::universe_excluding`) — pas de
sélection manuelle de tickers en entrée.

## 3. Organisation du code

Sous `patrick/patrick/` :

| Répertoire | Rôle |
|---|---|
| `config/` | `schema.py` (modèle pydantic `RunConfig`, sans bornes/validateurs — la validation vit dans `webapp/forms.py`), `defaults.py` (constantes : univers `DEFAULT_TARGET_GROUPS` par catégorie, `DEFAULT_HORIZONS`, `DEFAULT_FEATURE_FAMILIES`, grilles de modèles/samplers, seuils qualité). C'est la première source de vérité pour "quelle est la valeur par défaut de X". |
| `data/` | `sources/yfinance_source.py` + `sources/fred_source.py` (ingestion, un échec par série n'en bloque pas d'autres), `store.py` (data lake Parquet local, partitionné par snapshot de date d'ingestion — jamais réécrit, hash de contenu pour dédupliquer), `quality.py` (portes de qualité à l'ingestion, seuils mesurés par simulation), `ingest.py` (orchestration), `session_calendar.py` (jours ouvrés, classification par classe d'actif). |
| `features/` | Une fonction par famille : `technical.py` (returns/zscore/ma_ratio/rolling_vol/estimateurs de vol réalisée OHLC), `macro.py`, `spike.py`, `vol_models.py` (EGARCH/Kalman/HMM/Heston proxy/VRP proxy + AR/MA/ARMA/ARIMA), `interactions.py` (paires découvertes sur le pool de base). `target.py` construit la variable cible (4 classes : DOWN fort/faible, UP faible/fort, cf. `_CLASS_DIRECTION` dans `tracking/history.py`). Fenêtres actuellement **fixées en dur** par défaut de fonction (pas encore paramétrables par une liste de lookbacks arbitraire — cf. audit Phase 13 "features Guida" pour le détail). |
| `selection/` | Sélection de features : `shap_select.py` (méthode par défaut, bat RFE/LASSO en test direct — cf. `README`/`DESIGN`), `rfe_select.py`, `lasso_select.py`, `stability.py` (suivi de stabilité de la sélection dans le temps), `registry.py` (dispatch par nom de méthode). |
| `models/` | `registry.py` (grid d'algos : XGBoost/LightGBM/RandomForest/CatBoost + GradientBoosting en option ; **`MODEL_N_JOBS = 1`** — constante critique, évite l'oversubscription CPU quand plusieurs modèles tournent en parallèle sur les folds), `samplers.py` (SMOTE et variantes), `calibration.py`, `uniqueness.py` (pondération par unicité, Phase 6.2), `sequential_forest.py`. |
| `tuning/` | `optuna_runner.py` — recherche d'hyperparamètres après le grid scan, budget (`n_trials`/`top_k`) alloué **par horizon** depuis le fix C3 (avant : concentré sur un seul horizon dominant). |
| `validation/` | `walkforward.py`, `cpcv.py` (alternative combinatoire, `n_groups`/`k_test_groups`), `purge.py` (effet mesuré négligeable, désactivé par défaut), `embargo.py` (activé par défaut par précaution), `diebold_mariano.py` (test DM vs baseline, kind `class_specific` par défaut — c'est ce qui est affiché partout dans le produit), `pbo.py`/`pbo_reliability.py` (probability of backtest overfitting), `fdr.py` (correction Benjamini-Hochberg à travers les cibles), `baselines.py`, `dsr.py`, `metrics.py`. |
| `pipeline/engine.py` | Orchestrateur central, `run_pipeline()` — voir §4. |
| `tracking/` | `db.py` (schéma SQLite + toutes les fonctions d'écriture), `history.py` (fonctions de lecture optimisées pour la webapp — voir §5), `export.py` (export du meilleur modèle par cible/horizon), `report.py` (rapport HTML autonome), `jobs.py` (file d'attente pour les runs lancés depuis le web), `stats.py`, `holdout_diagnostic.py`, `migrations/*.sql` (numérotées, auto-découvertes par `MIGRATIONS_DIR.glob("*.sql")`). |
| `webapp/` | FastAPI + Jinja2 — voir §6. |
| `simulate/` | Moteur de simulation P&L théorique à partir des prédictions persistées (jamais de ré-entraînement), utilisé par `/simulate`. |
| `cli.py` | Tous les sous-commandes (`patrick run/resume/predict/report/ingest/audit degradation/worker/serve`) — voir §8. |
| `predict.py` | `predict_live()` : scoring en production sans ré-entraînement, écrit `prediction.split='live'`, backfille aussi les issues réelles des prédictions live passées dont l'horizon est désormais écoulé. |
| `audit.py` | Audits ponctuels de validation (ex. `run_degradation_audit` : impact mesuré des correctifs anti-fuite Phase 0, PAS un moniteur de dérive continue). |
| `worker.py` | Boucle de traitement de la file de jobs (runs soumis depuis le web). |

## 4. Le pipeline walk-forward en détail

`pipeline/engine.py::run_pipeline()` — sous-phases instrumentées
(`trackdb.record_phase_timing`, migration 0017), dans l'ordre :

1. **`ingestion`** — récupération/cache des données brutes (une fois par run, avant tout `run_id`).
2. **`scan`** — grid search (sampler × n_features × algo) sur repli walk-forward ou CPCV ; `build_base_feature_pool()` (calculé une fois, partagé) puis `build_parametric_pool()` (refait par fold — modèles de vol paramétriques, spike paramétrique).
3. **`pool_construction`** — construction du pool de features par fold (CPCV uniquement, sous-phase séparée du scan).
4. **`stability`** — suivi de la stabilité de sélection de features, **par horizon** (Phase 6.3).
5. **`holdout_diagnostic`** — diagnostic sur le holdout terminal, séparé du holdout final lui-même.
6. **`tuning`** — Optuna sur le top-k configs issues du scan, budget par horizon (Phase C3).
7. **`export`** — export du/des meilleur(s) modèle(s) (une occurrence par horizon depuis le refactor "best-model-per-horizon" — avant ce fix, `patrick predict --live` ne fonctionnait que pour l'horizon "gagnant" global, bug corrigé).

Puis, hors boucle horizon :
- **Holdout terminal** (Phase 2.1) — 15 mois réservés par défaut (`DEFAULT_HOLDOUT_MONTHS`), jamais vus par la sélection/tuning/leaderboard.
- **Diebold-Mariano** (Phase 2.5) vs. meilleure baseline par classe d'actif (`DEFAULT_BASELINE_BY_ASSET_CLASS`), deux variantes persistées (`class_specific` et `common`) — le produit affiche partout `class_specific`.

## 5. Persistance (SQLite `patrick.db`)

Tables principales : `run` (une ligne par cible×horizon), `trial`, `fold_metric`,
`prediction` (**~12M lignes en production** — table la plus volumineuse),
`dm_result` (clé `(run_id, kind)`), `run_phase_timing`, `job` (file d'attente
web), `snapshot`.

**Discipline de performance non négociable** pour toute requête webapp sur
`prediction` : sous-requête corrélée **par clé de partition** (cible, ou
(cible, horizon)) — PAS de fenêtre analytique `ROW_NUMBER() OVER (PARTITION
BY ...)`, mesurée 50s+ contre 3,3s sur la vraie base pour ce pattern.
Référence canonique : `tracking/history.py::latest_predictions_by_target()`
et sa variante `latest_predictions_by_target_and_horizon()` (docstrings
détaillés). Toute nouvelle fonction de lecture doit suivre ce pattern et
mesurer sur la vraie base avant de considérer la tâche terminée.

## 6. Application web

FastAPI + Jinja2, design system **Cockpit v2** :
- Templates étendent `webapp/templates/base_v2.html`, CSS =
  `webapp/static/patrick-v2.css`.
- Macros partagées `webapp/templates/_components.html` :
  `status_badge(label, state)` (états `ok`/`warning`/`neutral`/`disabled`),
  `data_table(...)`, `empty_state(...)`, `metric(...)`.
- i18n dans `webapp/i18n.py` (`t()` dans les templates), français par défaut,
  anglais en second.
- Pages principales : `/` (synthèse), `/launch` (config + lancement d'un
  run), `/runs`, `/runs/{id}`, `/targets/{ticker}`, `/universe`,
  `/commodities`, `/macro` (stats par actif, calcul côté client via
  `asset_stats.js`/`/api/asset-stats/{symbol}`), `/predictions` (vue
  d'ensemble cible×horizon), `/simulate`, `/phase9` (journal + snapshots).
- La file de jobs web (`tracking/jobs.py` + `worker.py`, lancé
  automatiquement par `run_manager.ensure_worker_running`) exécute les runs
  soumis depuis `/launch` de façon asynchrone.

## 7. Conventions clés

- **Walk-forward strict** : purge désactivée par défaut (effet négligeable
  mesuré), embargo activé par défaut (précaution, coût faible).
- **TDD strict** sur toute nouvelle logique de calcul/validation/route : test
  rouge d'abord, implémentation, test vert.
- **SHAP > RFE/LASSO** pour la sélection de features (mesuré, pas un choix
  arbitraire).
- **Stacking désactivé par défaut** (perd sur 93% des paires horizon/fold
  testées en walk-forward).
- **`MODEL_N_JOBS = 1`** (`models/registry.py`) — ne jamais repasser à `-1`
  sans revalider : cause avérée d'oversubscription CPU massive (variance de
  temps de tuning ×20+ mesurée avant fix).
- **Un branch par chantier**, jamais de merge/push sans confirmation
  explicite fraîche de l'utilisateur, `git merge --no-ff`, abandon immédiat
  (`git merge --abort`) sur tout conflit plutôt que résolution unilatérale.

## 8. Points d'entrée CLI

Voir `cli.py` pour la liste exhaustive et `patrick <commande> --help`. Les
plus utilisés en production :

```
patrick run --config <yaml>              # pipeline complet, une cible, 1+ horizons
patrick resume --run-id <id>             # reprend un run interrompu (Optuna study persistée)
patrick predict --run-id <id> --live     # scoring quotidien, sans ré-entraînement
patrick report --run-id <id>             # rapport HTML autonome depuis patrick.db
patrick audit degradation                # audit ponctuel de validation anti-fuite (PAS un monitoring continu)
patrick worker                           # boucle de traitement de la file de jobs web
patrick serve                            # lance l'interface web (uvicorn)
```
