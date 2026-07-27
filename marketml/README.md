# patrick

Cadre ML/DL multi-actifs autonome — généralise la méthodologie du projet VIX
(`../notebooks/`) : walk-forward strict, features avancées (Heston/EGARCH/Kalman/
HMM/VRP/spike/interactions), sélection SHAP/RFE/LASSO, grille de samplers/algos,
tuning Optuna — configurable en YAML, exécutable sur n'importe quel actif/indice
via `yfinance`/FRED, pas seulement le VIX.

## Installation

```bash
cd marketml
pip install -e .
```

## Utilisation

```bash
patrick ingest --config configs/examples/vix_direction.yaml
patrick run --config configs/examples/vix_direction.yaml
patrick serve
```

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

## État de la vérification

Le moteur complet (ingestion -> features -> walk-forward -> sélection -> grille ->
Optuna -> export) est validé par un test de fumée bout-en-bout sur données
synthétiques (`tests/test_pipeline_smoke.py`) et 40 tests unitaires (`pytest
tests/`, 42 avec les paramétrisations), dont un test de fumée de l'interface web
(`test_webapp_smoke.py`) et les tests de fuite de la Phase 0
(`test_leakage.py`).
**La vérification avec de vraies données** a été faite sur une machine avec
accès réseau yfinance/FRED (`patrick run --config
configs/examples/vix_direction.yaml`) ; un bug sur les séries FRED traversant
zéro (T10Y2Y, EFFR) a été trouvé et corrigé à cette occasion (`safe_pct_change`,
cf. `features/_utils.py`), et un problème plus récent de fiabilité du scraping
FRED a mené à l'ajout du chemin API authentifié ci-dessus. **La Phase 0 n'a en
revanche pas encore été revérifiée avec de vraies données** — les corrections
(fold-dépendance des features paramétriques notamment) changeront probablement
la référence F1_dir≈0.610, à revalider sur une machine avec accès réseau.

## Feuille de route

- Phase 1+ (persistance SQLite, validité statistique, exécution robuste,
  simulation d'investissement, hygiène) — voir le plan en 5 phases fourni,
  Phase 0 seule traitée pour l'instant.
- Vintages FRED branchés par fold dans le moteur walk-forward (cf. limite
  documentée ci-dessus).
- Modèles DL (TFT, LSTM, etc.) — jamais gagné en walk-forward dans le projet VIX,
  resteront désactivés par défaut.
