# Notebooks

Recherche d'origine sur le VIX (Colab / local). Le pipeline actuel vit dans le package `patrick/` ; ces notebooks sont
conservés comme historique de la démarche et ne sont pas exécutés par l'application.

| Dossier | Contenu |
|---|---|
| `VIX_ML3.ipynb` | notebook de machine learning principal d'origine (version corrigée) |
| `archive/` | versions antérieures et variantes d'exploration (amplitude, stacking, deep learning, EGARCH, régimes…), dont `VIX_ML3_original_uncorrected.ipynb` (avant correctifs) et `RAPPORT_VIX.pdf` ; les copies identiques ont été fusionnées |
| `final_campaign/` | campagne finale : variables, scan ML, Optuna, TFT |
| `production/` | notebook de production et simulation de portefeuille |
| `research/` | benchmarks VAR / VECM |
| `validation/` | validations : seuil calibré, champion walk-forward, sélection de variables, volatilité OHLC, CV purgée, routage de régime, détection de pics, stacking, TFT |
