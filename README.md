# claude

Workspace de recherche VIX (prédiction directionnelle/amplitude via ML + Deep Learning).

## Notebook courant

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/LP-D/claude/blob/main/notebooks/VIX_ML3.ipynb)

**`notebooks/VIX_ML3.ipynb`** — version corrigée et à jour. Un clic sur le badge ouvre directement la dernière version sur GitHub dans Colab (pas d'upload/download manuel).

Pipeline en deux étapes :
1. Entraîne le panel complet de modèles ML (~9465 configs) + 7 architectures DL sur 6 horizons × 4 régimes de VIX, et construit une **base de prédictions** (OOF pour le train, direct pour le test) sauvegardée en `.parquet`.
2. Entraîne plusieurs méta-modèles (XGBoost, LightGBM, régression logistique, vote pondéré, MLP) sur cette base et exporte le meilleur, avec un rapport `.xlsx` (SHAP inclus).

### Récupérer les résultats sans repasser par Claude Code

La dernière cellule du notebook archive automatiquement `vix_predictions_{train,test}.parquet`, `vix_models_metadata.parquet` et `VIX_ML3_stacking_report.xlsx` sur la branche `results/vix-ml3` de ce repo, dans un dossier horodaté `results/{version}/{date}_{heure}/` — **jamais écrasé** : chaque run Colab garde sa propre trace. Condition : avoir configuré un secret Colab :

1. Créer un [Personal Access Token GitHub](https://github.com/settings/personal-access-tokens/new) *fine-grained*, limité à ce repo (`LP-D/claude`), avec la permission **Contents: Read and write**.
2. Dans Colab : icône clé 🔑 (barre latérale gauche) → *Ajouter un secret* → nom `GITHUB_TOKEN`, valeur = le token → activer l'accès pour ce notebook.
3. Lancer le notebook normalement ("Exécuter tout"). Sans ce secret, la cellule est simplement ignorée (aucun impact sur le reste).

Les résultats sont ensuite visibles directement sur GitHub, branche `results/vix-ml3`, sans avoir à télécharger quoi que ce soit depuis Colab.

## Versioning

Le notebook porte un numéro de version (`NOTEBOOK_VERSION`, visible au tout début de l'exécution) incrémenté uniquement lors d'une évolution fonctionnelle du pipeline — pas pour un simple correctif de bug. Ce numéro tague les dossiers de résultats archivés (`results/{version}/...`), pour savoir de quelle version du code provient chaque run.

## `notebooks/archive/`

Historique des itérations précédentes (stacking, DL, EGARCH, walk-forward, exploration de régimes, etc.), conservé pour référence — pas de maintenance active dessus.
