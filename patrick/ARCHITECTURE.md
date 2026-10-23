# Architecture PATRICK

Vue d'ensemble technique du pipeline et du produit. La rédaction initiale date du 2026-09-05 (HEAD `main` = `fbd354b`) ;
les modules apparus depuis sont listés en §3 bis. Objectif : permettre à une future session de comprendre
l'organisation du code sans refaire un audit complet depuis zéro.
Pour le contexte produit/décisions, voir `PRODUCT.md`, `METHODOLOGY.md`, `design-system/patrick/MASTER.md` (design) et
`docs/index.md` (toute la documentation) — ce document est structurel, pas narratif.

## Table des matières

1. [Layout du dépôt](#1-layout-du-dépôt)
2. [Flux de données de bout en bout](#2-flux-de-données-de-bout-en-bout)
3. [Organisation du code](#3-organisation-du-code) (et 3 bis : modules ajoutés depuis)
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

`pyproject.toml` fixe `addopts = "-m 'not slow and not validity'"` : un `pytest -q` nu exclut
les tests lents (CPCV/holdout/Diebold-Mariano/PBO). Utiliser `-m ""` pour la
suite complète (y compris `validity`, ~15 min), `-m "slow"` pour les tests lents seuls, `-m "validity"` pour le pipeline sur des marches aléatoires seul.

La base de tracking SQLite est **partagée entre tous les worktrees**,
`~/.patrick/patrick.db` (pas un fichier par checkout) — attention en testant
plusieurs branches en parallèle : toujours utiliser
`monkeypatch.setenv("PATRICK_DB_PATH", ...)` dans les tests pour ne jamais
toucher la vraie base.

Deux dossiers, deux rôles : le **dossier maison** (`~/.patrick`) garde la base
active, les journaux et l'état de la machine ; la **racine de données** (réglage
`data_root` ou `PATRICK_DATA_ROOT`, par défaut le dossier maison) porte le
magasin, les modèles, les caches, les sauvegardes, les archives et les rapports.
Tous les emplacements se résolvent par `patrick/paths.py` (un test interdit d'écrire
`.patrick` en dur ailleurs) ; `patrick data status` les affiche et
`patrick data move` déplace la racine sur un autre disque.

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
    J --> K[Webapp FastAPI\nCockpit Pro v3]
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
| `fund/` | Stratégies, ordres et valorisation de positions fictives (action/ETF, future, CFD) : `engine.py` (rejeu des ordres jour par jour), `service.py` (aperçu et passage d'ordres), `prices.py` (cotations persistantes), `rules.py` (PEA/CTO), `fees.py`, `instruments.py`, `kpis.py`, `store.py` — pages `/simulate` et `/fonds`. |
| `simulate/` | Moteur de simulation P&L théorique à partir des prédictions persistées (jamais de ré-entraînement). Plus de page depuis la refonte Simulation/Fonds : réutilisé par le mode ML du chantier 3. |
| `cli.py` | Tous les sous-commandes (`patrick run/resume/predict/report/ingest/audit degradation/worker/serve`) — voir §8. |
| `predict.py` | `predict_live()` : scoring en production sans ré-entraînement, écrit `prediction.split='live'`, backfille aussi les issues réelles des prédictions live passées dont l'horizon est désormais écoulé. |
| `audit.py` | Audits ponctuels de validation (ex. `run_degradation_audit` : impact mesuré des correctifs anti-fuite Phase 0, PAS un moniteur de dérive continue). |
| `worker.py` | Boucle de traitement de la file de jobs (runs soumis depuis le web). |

## 3 bis. Modules ajoutés depuis la première rédaction

| Module (sous `patrick/patrick/`) | Rôle |
|---|---|
| `desktop/` | Application de bureau : lanceur (`python -m patrick.desktop`), mise à jour depuis GitHub, assistant du dossier partagé, raccourcis — voir `docs/ops/application-bureau.md`. |
| `sync.py`, `sync_merge.py` | Partage de la base, des modèles et du magasin entre PC (fusion par union des runs, PC de référence du patrimoine) — voir `docs/ops/partage-entre-pc.md`. |
| `settings.py` | Réglages de la machine (`~/.patrick/settings.json`), relus à chaque appel. |
| `paths.py`, `data_move.py` | Emplacements des données (dossier maison, racine de données, composants) et commande `patrick data` (état, création, déplacement vérifié avec retour arrière). |
| `wealth/` | Patrimoine : comptes réels et fictifs, mouvements, import CSV, valorisation et risque ex ante (pages `/patrimoine`, `/mouvements`). |
| `rl/`, `exploration/`, `research/` | Reinforcement learning (page `/rl`), études statistiques entre actifs (page `/exploration`), études d'événements et campagne alpha. |
| `benchmark/` | Mesure et non-régression des performances (`python -m patrick.benchmark`). |
| `live_refresh.py`, `keep_awake.py`, `resource_budget.py` | Actualisation des prédictions live, veille Windows pendant un run, plafond CPU/RAM des étapes parallèles. |
| `text/` | Analyse textuelle des news : magasin point-in-time (`store.py`, migration 0036), sources RSS/GDELT/Yahoo (`sources.py`), lexique, ton des banques centrales, entités, nouveauté, événements, thèmes (`lexicon.py`…`topics.py`), agrégation par actif et horizon, garde-fou LLM (`aggregate.py`, `llm_guard.py`), orchestration (`service.py`) ; page `/news`, commande `patrick news`. Aucune variable textuelle n'entre encore dans l'entraînement. |
| `tracking/black_litterman.py` | Black-Litterman v2 sur P(hausse) calibrées (`prediction.p_up_calibrated`, migration 0037) ; section de `/portfolio`. |
| `webapp/security.py` | Garde globale des requêtes : hôte local obligatoire, requêtes venues d'un autre site refusées (CSRF, DNS rebinding). |

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

FastAPI + Jinja2, design system **v3 « Cockpit Pro »**
(`design-system/patrick/MASTER.md`, section v3) :
- Templates étendent `webapp/templates/base_v2.html` (nom conservé : shell
  v3 — sidebar repliable, topbar, palette Ctrl K, thèmes clair/sombre),
  CSS = `webapp/static/patrick.css`, comportements du shell =
  `webapp/static/shell.js`, icônes Lucide inline = `webapp/icons.py`
  (globals Jinja `icon()` / `nav_icon()`).
- Les graphiques passent tous par `static/chart_kit.js` (`PatrickPlot`, canvas HiDPI, zoom / déplacement / échelle recalculée /
  infobulle / légende ; `charts.js` en est l'enveloppe pour Exploration et RL). Ils lisent leurs couleurs dans les jetons CSS au moment
  du tracé et se redessinent sur l'événement `patrick:themechange`. Détail et contrat : `design-system/patrick/MASTER.md`, section Graphiques.
- Traductions : `i18n*.py` (clés FR/EN), `i18n_server.py` (messages du domaine traduits à l'affichage, filtre `tx`), `ui_t()` pour les
  macros, `LangMiddleware` pour la langue de la requête.
- Fil de localisation : barre du haut seulement (`crumb_trail` pour les pages enfants) ; pas de fil d'Ariane dans le corps des pages.
- Macros partagées `webapp/templates/_components.html` :
  `status_badge(label, state)` (états `ok`/`warning`/`neutral`/`disabled`),
  `data_table(...)`, `empty_state(...)`, `metric(...)`.
- i18n dans `webapp/i18n.py` (`t()` dans les templates), français par défaut,
  anglais en second.
- Pages principales : `/` (synthèse), `/ml`, `/dl` et `/rl` (cadrage et
  lancement : machine learning, deep learning, reinforcement learning ;
  `/launch` redirige vers `/ml`), `/exploration` (études statistiques entre
  actifs), `/runs`, `/runs/{id}`, `/targets/{ticker}`, `/universe`,
  `/news` (flux de nouvelles point-in-time, sentiment par actif), `/commodities`, `/macro` (stats par actif, calcul côté client via
  `asset_stats.js`/`/api/asset-stats/{symbol}`), `/predictions` (vue
  d'ensemble cible×horizon), `/simulate` (ticket d'ordres) et `/fonds`. Le journal et les snapshots
  Phase 9 restent accessibles via API, sans page de navigation dédiée.
- La file de jobs web (`tracking/jobs.py` + `worker.py`, lancé
  automatiquement par `run_manager.ensure_worker_running`) exécute les runs
  soumis depuis `/ml`, `/dl` et `/rl` de façon asynchrone.
- **Texte minimal** : `static/help.js` replie derrière un « ? » tout texte
  d'aide statique (`.hint`, sous-titres, notes, explications entre
  parenthèses d'un libellé). Un message d'état dynamique reste visible s'il a
  un `id`, un `aria-live`, un `role` ou `data-keep` (opt-in inverse :
  `data-help="fold"`).

### 6 bis. Pages Modèles et Exploration (spec : `docs/superpowers/specs/2026-10-10-pages-ml-dl-rl-exploration-design.md`)

- `/ml` et `/dl` partagent `templates/launch_base.html` (blocs
  `sec_sampler`, `sec_models`, `sec_tuning`, `sec_optuna_bounds`) et
  `static/app.js` : le deep learning n'est PAS un second pipeline mais des
  algos de plus (`models/deep.py`, `get_classifier`) : MLP, GRU, LSTM, CNN1D,
  Transformer, avec walk-forward, purge, embargo, sélection, Optuna, duel de
  champions du ML. Réglages communs dans `ModelsConfig.deep` (`None` pour un
  run ML : hors du hachage de configuration, `pipeline/engine.py::
  _config_hash`) ; modèles à fenêtre incompatibles avec SMOTE et CPCV
  (`RunConfig._check_deep_models`). PyTorch est optionnel (`pip install -e
  ".[deep]"`), importé à l'usage ; la page et le lancement le signalent.
- `/rl` : moteur à part, `patrick/rl/` (`config.py` `RLRunConfig`,
  `core.py` mécanique NumPy de l'environnement, `env.py` Gymnasium, `agents.py`
  PPO/A2C/DQN/SAC via Stable-Baselines3, `data.py` états causaux, `walkforward.py`,
  `metrics.py`, `run.py`). Même file de jobs (`config_json` avec `"kind": "rl"`,
  `worker._run_one_rl_job`), résultat dans `job.result_json` et
  `<sortie>/rl_result.json`. Extras optionnels : `pip install -e ".[rl]"`.
- `/exploration` : `patrick/exploration/` (`panel.py` alignement des niveaux AVANT
  les rendements, `studies.py` fonctions pures ; une série plus lente que la fréquence demandée fait passer tout le panneau à sa
  fréquence, jamais de recopie) servi par
  `webapp/exploration_routes.py` (`/api/exploration/<étude>`) ; graphiques SVG
  communs dans `static/charts.js`.
- **Une seule machine, une seule file** : `/ml`, `/dl` et `/rl` incluent la même carte « en cours et file d'attente »
  (`templates/_machine_card.html` + `static/machine.js`, alimentée par `/api/run-state` ; `_job_view` y ajoute `kind` ml/dl/rl et
  `target`). `app.js` (ML, DL) et `rl.js` s'y abonnent (`PatrickMachine.subscribe` / `onAction`) pour suivre le détail du run actif.
  Un « Arrêter » efface le pouls du worker tué (`jobs.clear_heartbeat`) avant de relancer un worker : sans cela la file restait à
  l'arrêt jusqu'à 30 s après l'arrêt (le pouls du mort passait pour vivant).
- **Bandeau des plus fortes variations** : `templates/base_v2.html` (au-dessus de la barre du haut, toutes les pages) +
  `static/ticker.js`, données de `alerts.get_cached()` / `/api/movers`. Sens du défilement : variable CSS `--ticker-dir` (`reverse` =
  gauche → droite, `normal` = droite → gauche) ; arrêt au survol et sous `prefers-reduced-motion`.

## 7. Conventions clés

- **Walk-forward strict** : purge désactivée par défaut (effet négligeable
  mesuré), embargo activé par défaut (précaution, coût faible).
- **TDD strict** sur toute nouvelle logique de calcul/validation/route : test
  rouge d'abord, implémentation, test vert.
- **SHAP > RFE/LASSO** pour la sélection de features (mesuré, pas un choix
  arbitraire).
- **Stacking et DL : plus d'exclusion a priori** (`docs/ways-of-working.md`).
  Le stacking est une catégorie comparée explicitement (global / par régime
  / stacking) ; le toggle historique `DEFAULT_STACKING_ENABLED` reste
  désactivé par défaut (perd sur 93% des paires horizon/fold en
  walk-forward, résultat mesuré, pas un interdit).
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
