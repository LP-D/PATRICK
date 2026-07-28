# patrick

Cadre ML/DL multi-actifs autonome — généralise la méthodologie du projet VIX
(`../notebooks/`) : walk-forward strict, features avancées (Heston/EGARCH/Kalman/
HMM/VRP/spike/interactions), sélection SHAP/RFE/LASSO, grille de samplers/algos,
tuning Optuna — configurable en YAML, exécutable sur n'importe quel actif/indice
via `yfinance`/FRED, pas seulement le VIX.

Voir `METHODOLOGY.md` pour le détail des garanties anti-fuite/anti-surapprentissage
(walk-forward, purge/embargo, vintages point-in-time, correction multi-tests,
holdout, baselines) et leurs limites connues.

## Installation

```bash
cd patrick
pip install -e .
```

## Utilisation

```bash
patrick ingest --config configs/examples/vix_direction.yaml
patrick run --config configs/examples/vix_direction.yaml
patrick serve
```

**Windows, lancement rapide** : `PATRICK.bat` (à la racine de `patrick/`)
active le `.venv` et lance `patrick serve` en un double-clic — ou, en ajoutant
le dossier `patrick/` au `PATH` (une seule fois, Panneau de configuration ->
Variables d'environnement), en tapant simplement `PATRICK` (ou `start PATRICK`)
dans n'importe quel invite de commandes.

`ingest` télécharge et met en cache (Parquet local, `~/.patrick/store`) la cible
et l'univers de features. `run` construit les features, boucle le walk-forward
(horizon × fold × régime), sélectionne les features (SHAP par défaut), teste la
grille sampler × N(5-15) × algo, affine les meilleures configs par Optuna, et
exporte :
- `runs/<name>_leaderboard.csv` (+ `.xlsx`) : toutes les évaluations
- `runs/<name>_tuned.csv` : les configs affinées, ré-évaluées sur les 5 folds
- `runs/<name>_best_model.joblib` + `_best_model_meta.json` : le modèle gagnant,
  ré-entraîné sur 100% de l'historique (comme `VIX_PRODUCTION`)

## Config (YAML)

Voir `configs/examples/vix_direction.yaml` (reproduit le pipeline VIX établi) et
`configs/examples/aapl_direction.yaml` (second actif, preuve de généralité). Champs
principaux : `objective` (cible, horizons, régimes), `universe` (tickers/FRED du
pool de features), `features` (familles activées), `validation` (folds, purge),
`selection` (méthode, grille N), `sampler`, `models` (algos, calibration,
stacking), `tuning` (Optuna).

## Accès aux données

- **yfinance** : pas de clé requise, retry batch -> ticker-par-ticker déjà en place.
- **FRED** : par défaut, `pandas_datareader` scrape le CSV public
  `fredgraph.csv` — sans clé, mais fragile (peut se mettre à échouer sur
  toutes les séries en même temps si fred.stlouisfed.org change son
  HTML/bloque le scraping, sans lever d'erreur qui remonte : chaque série
  ratée devient juste un `[WARN]` dans les logs et le run continue sans elle,
  ce qui peut dégrader silencieusement le modèle). Pour un accès fiable,
  définir la variable d'environnement `FRED_API_KEY` (clé gratuite sur
  https://fred.stlouisfed.org/docs/api/api_key.html) : `patrick.data.sources.
  fred_source` bascule alors sur l'API officielle authentifiée. Ne jamais
  committer la clé — variable d'environnement uniquement (`.env` local,
  secret d'OS, etc., jamais dans le YAML de config).

## Défauts qui encodent les leçons du projet VIX

SHAP par défaut (bat RFE/LASSO), stacking désactivé par défaut (perd sur 93% des
cas testés en walk-forward), DL désactivé par défaut (jamais gagné), sampler par
défaut = SMOTE seul, purge désactivée par défaut (effet négligeable, mesuré dans
VIX_PURGED_CV), embargo **activé** par défaut (pas de mesure empirique équivalente
sur ce cadre généralisé, coût faible — cf. section Phase 0 ci-dessous), calibration
désactivée par défaut (gain conditionnel au régime). Tout reste activable/
désactivable dans le YAML — rien n'est retiré du code, seulement pas activé sans
le demander.

## Phase 0 — correctness (walk-forward sans fuite)

Trouvé et corrigé en écrivant le test de corruption du futur
(`tests/test_leakage.py`) : les features paramétriques (EGARCH/Kalman/HMM/AR/MA/
ARMA/ARIMA de `features/vol_models.py`, filtre particulaire de
`features/spike.py`) estimaient leurs paramètres une seule fois sur tout
l'historique avant ce fix — même si la sortie point-par-point était causale, les
PARAMÈTRES eux-mêmes étaient informés par le test. Réajustés par fold
(`fit_end_idx`, train uniquement) depuis. Une fuite plus fine a aussi été trouvée
et corrigée dans `features/target.py::build_target` (seuils de classification
fittés sur des fenêtres de label chevauchant la coupure) et dans le repli `.fix()`
d'EGARCH (backcast/bornes de variance internes à `arch`, calculés sur la série
entière même à paramètres figés — cf. docstring de `vol_models.py`).

Autres ajouts Phase 0 :
- **Embargo** (`validation/embargo.py`, distinct de la purge) : retire les
  premières barres de test après la coupure, contre les features à fenêtre
  glissante encore corrélées au train juste après la frontière.
- **Alignement temporel par classe d'actif** (`data/session_calendar.py`) :
  décale d'une barre les features yfinance dont la classe d'actif clôture après
  celle de la cible (ex. feature US utilisée "du jour" pour une cible qui a déjà
  clôturé plus tôt dans la même journée UTC) — approximation à la barre près,
  pas un vrai as-of join intrajournalier (barres yfinance quotidiennes, sans
  horodatage de clôture réel).
- **Vintages FRED / ALFRED** (`data/sources/fred_source.py::download_series`,
  paramètre `realtime_date`) : récupère une série FRED telle que connue à une
  date passée plutôt que telle que révisée aujourd'hui — capacité disponible et
  testée (mocks), **pas encore branchée par fold** dans le moteur walk-forward
  (ça demanderait la même généralisation "par fold" que les features
  paramétriques ci-dessus, pas faite dans cette phase — limite connue). Le repli
  scrape (sans `FRED_API_KEY`) émet un warning explicite : il ne peut renvoyer
  que la version actuelle de chaque série.
- **Baselines systématiques** (`validation/baselines.py`) : classe majoritaire,
  persistance, HAR-RV — calculées par fold et ajoutées au leaderboard (lignes
  `BASELINE_*`) à côté des modèles.
- **Métriques** (`validation/metrics.py`) : balanced accuracy, MCC et AUC (ovr)
  ajoutées à côté de F1_dir/Acc_dir — F1_dir reste la métrique de tri/tuning du
  pipeline (continuité avec la référence F1_dir≈0.610 du projet VIX d'origine),
  les nouvelles métriques ne la remplacent pas silencieusement.

## Phase 1 — persistance SQLite

`~/.patrick/patrick.db` (WAL, `foreign_keys=ON`, `busy_timeout=5000`), migré
automatiquement à la connexion (`tracking/db.py::connect`, scripts SQL numérotés
dans `tracking/migrations/`, table `schema_version` — pas d'Alembic, ce projet
ne passe pas par SQLAlchemy). Chaque `run_pipeline()` écrit :
- **`snapshot`** : un par contenu de données ingéré (hash déterministe, déduplique
  automatiquement deux ingestions identiques — cf. Parquet ci-dessous).
- **`run`** : un par (cible, horizon) de la config — une config à plusieurs
  horizons écrit plusieurs `run`, qui partagent le même `snapshot_id`,
  `config_hash`, `git_sha`. **Écart assumé par rapport au DDL fourni** : `run`
  n'a pas de colonne `regime` (le moteur boucle aussi dessus) — ajoutée à
  `trial` à la place (sinon deux trials de régimes différents partageant
  horizon/N/sampler/algo seraient indiscernables).
- **`trial`** : un par combinaison (régime, N, sampler, algo, params) réellement
  testée — pas seulement la gagnante (prérequis direct de la Phase 2 : PBO/DSR
  ont besoin de savoir combien de configurations ont été essayées).
- **`fold_metric`** : toutes les métriques (F1_dir, BalAcc, MCC, AUC...) par
  (trial, fold).
- **`baseline_metric`** : majorité/persistance/HAR-RV, agrégées (moyenne) par
  run — le DDL fourni n'a pas de colonne `fold_index` sur cette table, donc pas
  de granularité par fold ici (contrairement au CSV `_leaderboard.csv`, qui
  garde le détail par fold).
- **`prediction`** : une ligne par observation de test (`y_true`, `y_pred`,
  confiance de la classe prédite) — prérequis direct de la Phase 4 (simulateur
  d'investissement, qui ne doit jamais relancer un modèle).

Le data lake Parquet (`data/store.py`) est maintenant partitionné par snapshot
immuable (`~/.patrick/store/snapshot=<date>/<clé>__<hash>.parquet`) plutôt que
réécrit à chaque ingestion — deux ingestions identiques retombent sur le même
snapshot (déduplication par hash), deux ingestions différentes le même jour
coexistent sans s'écraser. `DataStore.query()` lit directement les Parquet par
SQL via DuckDB, sans les recharger un par un en pandas.

**Limite connue** : les vintages FRED (Phase 0.5) ne sont pas branchés par fold
dans `run_pipeline` — le `snapshot` enregistré est donc celui de l'ingestion
"aujourd'hui", pas un vintage par fold. Brancher ça demanderait la même
généralisation "par coupure de fold" déjà faite pour les features paramétriques.

## Phase 2 — validité statistique

Le leaderboard trie déjà sur une métrique optimisée (F1_dir, sur la grille
sampler×N×algo puis Optuna) : sans correction, il classe le maximum d'un
échantillon de bruit, pas des modèles. La Phase 2 ajoute cette correction —
calculée une seule fois pour la config gagnante d'un run, jamais pour
recalculer/trier le scan (cf. anti-pattern documenté ci-dessous).

- **Holdout terminal** (`config.validation.holdout_months`, 15 par défaut —
  milieu de l'intervalle 12-18 mois donné, aucun argument fort pour l'un ou
  l'autre bord) : les derniers mois d'historique sont exclus du domaine
  walk-forward (`pipeline/engine.py::_walk_forward_span`) — jamais vus par la
  construction des features paramétriques, la sélection ou le tuning. Une
  seule réévaluation de la config déjà choisie (`_evaluate_holdout`), jamais
  utilisée pour choisir entre plusieurs configs. Si l'historique est trop
  court pour à la fois entraîner et garder un holdout de cette durée, il est
  désactivé pour ce run avec un avertissement explicite plutôt que de
  planter. Résultat écrit en base (`fold_metric`/`prediction`, `split='holdout'`,
  `fold_index=0`) et renvoyé dans `result["holdout"]`.
- **Compteur d'essais cumulé** (`tracking/stats.py::count_cumulative_trials`) :
  nombre total de `trial` pour une (cible, horizon), sur **tout l'historique
  de runs**, pas seulement le run courant — c'est ce nombre qui doit corriger
  un Sharpe/PBO, pas celui d'un seul run isolé.
- **PBO** (`validation/pbo.py`, `tracking/stats.py::pbo_for_target`) :
  Probability of Backtest Overfitting par CSCV (Bailey/Borwein/López de
  Prado/Zhu 2017). Écart assumé par rapport au papier : les "blocs" CSCV sont
  directement les folds walk-forward déjà en base (`fold_metric`), pas un
  découpage temporel arbitraire séparé — respecte la structure temporelle par
  construction. `n_wf_folds` (5 par défaut, impair) est réduit au nombre pair
  inférieur pour la combinatoire CSCV (donc 4 blocs par défaut) ; un
  `n_wf_folds` plus élevé donne un PBO plus robuste.
- **Diebold-Mariano** (`validation/diebold_mariano.py`) : perte 0/1 (mal
  classé/bien classé) plutôt que quadratique (formulation originale pensée
  pour la régression), entre la config gagnante et la meilleure des baselines
  systématiques (Phase 0.6), sur le dernier fold walk-forward. p-value dans
  `result["diebold_mariano"]`, marquée visuellement comme non significative
  (p≥0.05) dans l'interface web.
- **Sharpe déflaté / DSR** (`validation/dsr.py`, Bailey & López de Prado
  2014) : implémenté et testé, **pas encore appelé depuis le pipeline** — le
  plan fourni le lie explicitement à la Phase 4 ("utilisé dès qu'une courbe
  de P&L existe") ; ce pipeline ne calcule que des métriques de
  classification pour l'instant, pas de série de rendements à déflater.
  Module autonome prêt à être branché une fois le simulateur d'investissement
  en place.

Tout ceci reste calculé pour la config gagnante uniquement, pas pour chaque
ligne du scan : réévaluer chaque trial sur le holdout en ferait une seconde
surface de sur-optimisation (le nombre de configurations comparées au
holdout doit rester minimal), et le coût de calcul serait prohibitif sur une
grille de centaines/milliers de trials.

**Bug de fuite/robustesse trouvé en écrivant les tests de cette phase** :
`safe_pct_change` (`features/_utils.py`, déjà en place depuis la Phase 0)
neutralisait `+/-inf` (dénominateur exactement nul) mais pas un dénominateur
**proche** de zéro, qui produit un rendement énorme mais fini — sur une série
qui traverse zéro (T10Y2Y typiquement), ça déborde ensuite en overflow ->
`inf` après mise à l'échelle (`RobustScaler`) plus loin dans le pipeline et
fait planter XGBoost (`Input data contains inf`). `safe_pct_change` clippe
maintenant à +/-1000% par période — au-delà, ce n'est de toute façon jamais
un signal exploitable, quel que soit l'actif/la série. Trouvé sur les proxys
Heston/VRP (`vol_models.py`) appliqués à T10Y2Y avec un historique
synthétique sans l'artefact de plancher de `_synthetic_raw` (cf.
`tests/test_pipeline_smoke.py::_synthetic_raw_no_floor`) — pas rencontré
dans les Phases 0/1 car les tests précédents n'exerçaient jamais ce chemin
précis (réévaluation sur une fenêtre de données différente du scan
walk-forward habituel).

*Critère de sortie Phase 2 (vérifié par
`test_phase2_holdout_dm_cumulative_trials_and_pbo_are_populated`) : pour la
config gagnante d'un run, holdout + p-value Diebold-Mariano vs meilleure
baseline + compteur d'essais cumulé + PBO sont calculés, persistés (holdout)
et exposés (`run_pipeline` -> `run_manager._summarize_result` -> interface
web, sous le "Best config").*

## État de la vérification

Le moteur complet (ingestion -> features -> walk-forward -> sélection -> grille ->
Optuna -> export -> persistance SQLite -> validité statistique -> file de jobs/
worker séparé -> simulation d'investissement) est validé par des tests de fumée
bout-en-bout sur données synthétiques (`tests/test_pipeline_smoke.py`,
`test_webapp_smoke.py`, `test_worker.py`, `test_simulate.py`,
`test_simulate_webapp.py`, `test_predict_live.py`) et des tests unitaires
(`pytest tests/`, 98 au total avec les paramétrisations), dont les tests de
fuite de la Phase 0 (`test_leakage.py`), les tests de persistance de la Phase 1
(`test_db.py`, `test_store_snapshot.py`), les tests de validité statistique de
la Phase 2 (`test_dsr.py`, `test_pbo.py`, `test_diebold_mariano.py`,
`test_stats.py`), les tests d'exécution robuste de la Phase 3 (`test_worker.py`,
`test_optuna_resume.py`, `test_report.py`) et les tests du simulateur de la
Phase 4 (`test_simulate.py`, `test_simulate_webapp.py`, `test_predict_live.py`).
Le critère de sortie Phase 1 (deux runs identiques sur le même snapshot
produisent des métriques identiques, et écrivent snapshot+run+trials+
fold_metrics+baselines+predictions) est vérifié explicitement par
`test_run_writes_full_db_trail_and_is_reproducible_on_same_snapshot` ; celui de
la Phase 2 par `test_phase2_holdout_dm_cumulative_trials_and_pbo_are_populated` ;
celui de la Phase 3 (tuer le process web pendant un run ne perd pas le run) par
`test_real_worker_subprocess_survives_without_web_server` ; celui de la Phase 4
(simulation -> courbe + comparaison buy-and-hold + coût de rentabilité +
compteur de configs testées) par `test_api_simulate_end_to_end`.

**La vérification avec de vraies données** a été faite sur une machine avec
accès réseau yfinance/FRED (`patrick run --config
configs/examples/vix_direction.yaml`) ; un bug sur les séries FRED traversant
zéro (T10Y2Y, EFFR) a été trouvé et corrigé à cette occasion (`safe_pct_change`,
cf. `features/_utils.py`), et un problème plus récent de fiabilité du scraping
FRED a mené à l'ajout du chemin API authentifié ci-dessus. Un renforcement de
`safe_pct_change` (dénominateur proche de zéro, pas seulement nul — cf. Phase 2
ci-dessus) a été trouvé et corrigé en sandbox, pas encore revérifié avec de
vraies données. **Les Phases 0 à 2 n'ont pas encore été revérifiées ensemble
avec de vraies données** — les corrections de fuite (fold-dépendance des
features paramétriques notamment) changeront probablement la référence
F1_dir≈0.610, à revalider sur une machine avec accès réseau.

## Feuille de route

Les 5 phases du plan sont terminées (correctness, persistance SQLite,
validité statistique, exécution robuste, simulation d'investissement,
hygiène — `METHODOLOGY.md`, A/B test SMOTE vs `class_weight` infrastructure,
note logo, renommage du dossier racine `marketml/` -> `patrick/`). Le
renommage du dépôt GitHub lui-même (`LP-D/claude`) reste hors de portée des
outils disponibles ici — nécessite une action côté réglages GitHub.

- Vintages FRED branchés par fold dans le moteur walk-forward (cf. limite
  documentée dans `METHODOLOGY.md`).
- Modèles DL (TFT, LSTM, etc.) — jamais gagné en walk-forward dans le projet VIX,
  resteront désactivés par défaut.
