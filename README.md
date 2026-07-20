# claude

Workspace de recherche VIX (prédiction directionnelle/amplitude via ML + Deep Learning).

## Notebook courant

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/LP-D/claude/blob/main/notebooks/VIX_ML3.ipynb)

**`notebooks/VIX_ML3.ipynb`** — version corrigée et à jour. Un clic sur le badge ouvre directement la dernière version sur GitHub dans Colab (pas d'upload/download manuel).

Pipeline en deux étapes :
1. Entraîne le panel complet de modèles ML (~9465 configs) + 7 architectures DL sur 6 horizons × 4 régimes de VIX, et construit une **base de prédictions** (OOF pour le train, direct pour le test) sauvegardée en `.parquet`.
2. Entraîne plusieurs méta-modèles (XGBoost, LightGBM, régression logistique, vote pondéré, MLP) sur cette base et exporte le meilleur, avec un rapport `.xlsx` (SHAP inclus).

### Récupérer les résultats sans repasser par Claude Code

La dernière cellule du notebook pousse automatiquement `vix_predictions_{train,test}.parquet`, `vix_models_metadata.parquet` et `VIX_ML3_stacking_report.xlsx` vers la branche `results/vix-ml3-latest` de ce repo (dossier `results/`), à condition d'avoir configuré un secret Colab :

1. Créer un [Personal Access Token GitHub](https://github.com/settings/personal-access-tokens/new) *fine-grained*, limité à ce repo (`LP-D/claude`), avec la permission **Contents: Read and write**.
2. Dans Colab : icône clé 🔑 (barre latérale gauche) → *Ajouter un secret* → nom `GITHUB_TOKEN`, valeur = le token → activer l'accès pour ce notebook.
3. Lancer le notebook normalement ("Exécuter tout"). Sans ce secret, la cellule est simplement ignorée (aucun impact sur le reste).

Les résultats sont ensuite visibles directement sur GitHub, branche `results/vix-ml3-latest`, sans avoir à télécharger quoi que ce soit depuis Colab.

## `notebooks/archive/`

Historique des itérations précédentes (stacking, DL, EGARCH, walk-forward, exploration de régimes, etc.), conservé pour référence — pas de maintenance active dessus.
