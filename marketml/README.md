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
défaut = SMOTE seul, purge désactivée par défaut (effet négligeable), calibration
désactivée par défaut (gain conditionnel au régime). Tout reste activable dans le
YAML — rien n'est retiré du code, seulement pas activé sans le demander.

## État de la vérification

Le moteur complet (ingestion -> features -> walk-forward -> sélection -> grille ->
Optuna -> export) est validé par un test de fumée bout-en-bout sur données
synthétiques (`tests/test_pipeline_smoke.py`) et 28 tests unitaires (`pytest
tests/`), dont un test de fumée de l'interface web (`test_webapp_smoke.py`).
**La vérification avec de vraies données** a été faite sur une machine avec
accès réseau yfinance/FRED (`patrick run --config
configs/examples/vix_direction.yaml`) ; un bug sur les séries FRED traversant
zéro (T10Y2Y, EFFR) a été trouvé et corrigé à cette occasion (`safe_pct_change`,
cf. `features/_utils.py`), et un problème plus récent de fiabilité du scraping
FRED a mené à l'ajout du chemin API authentifié ci-dessus.

## Feuille de route

- Suivi SQLite complet des runs + `patrick report`/`resume`
- Modèles DL (TFT, LSTM, etc.) — jamais gagné en walk-forward dans le projet VIX,
  resteront désactivés par défaut
- Simulation de portefeuille, commande de mise en production / inférence sur la
  dernière ligne non labellisée
