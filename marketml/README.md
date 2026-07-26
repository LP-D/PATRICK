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

## Défauts qui encodent les leçons du projet VIX

SHAP par défaut (bat RFE/LASSO), stacking désactivé par défaut (perd sur 93% des
cas testés en walk-forward), DL désactivé par défaut (jamais gagné), sampler par
défaut = SMOTE seul, purge désactivée par défaut (effet négligeable), calibration
désactivée par défaut (gain conditionnel au régime). Tout reste activable dans le
YAML — rien n'est retiré du code, seulement pas activé sans le demander.

## État de la vérification

Le moteur complet (ingestion -> features -> walk-forward -> sélection -> grille ->
Optuna -> export) est validé par un test de fumée bout-en-bout sur données
synthétiques (`tests/test_pipeline_smoke.py`) et 17 tests unitaires (`pytest
tests/`). **La vérification avec de vraies données** (`patrick run --config
configs/examples/vix_direction.yaml` doit retrouver F1_dir≈0.610±0.025) reste à
faire sur une machine avec accès réseau à yfinance/FRED — l'environnement de
développement de cette session n'a pas cet accès.

## Feuille de route (pas construit dans cette session)

- Suivi SQLite complet des runs + `patrick report`/`resume`
- Modèles DL (TFT, LSTM, etc.) — jamais gagné en walk-forward dans le projet VIX,
  resteront désactivés par défaut
- Simulation de portefeuille, commande de mise en production / inférence sur la
  dernière ligne non labellisée
