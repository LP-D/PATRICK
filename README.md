# claude

Workspace de recherche VIX (prédiction directionnelle/amplitude via ML + Deep Learning),
sous forme de notebooks Colab indépendants et résumables.

## Structure

```
notebooks/
  VIX_ML3.ipynb                 — pipeline de stacking massif (historique, en pause)
  validation/                   — notebooks de validation walk-forward (une question chacun)
  final_campaign/               — campagne finale exhaustive (4 notebooks liés entre eux)
  production/                   — déploiement + recherche appliquée (portefeuille simulé)
  research/                     — analyse structurelle (économétrie), hors pipeline ML
  archive/                      — itérations précédentes, conservées pour référence
```

Chaque notebook :
- pousse ses résultats (CSV/xlsx de progression + rapport final) sur **sa propre branche
  `results/<nom>`**, jamais sur `main` (voir avertissement plus bas) ;
- est **résumable** : il récupère automatiquement toute progression déjà poussée au
  démarrage, et repousse des checkpoints pendant l'exécution (une déconnexion Colab ne fait
  perdre que le travail depuis le dernier checkpoint) ;
- nécessite un secret Colab `GITHUB_TOKEN` pour le push (voir ci-dessous) — sans lui, la
  cellule de push est ignorée proprement, aucun impact sur le reste du notebook.

## Référence établie (walk-forward, à battre)

**GLOBAL RandomForest, horizon 5 jours, N=8 features SHAP, SMOTE** :
F1_dir≈0.610±0.025, F1_UP_FORT≈0.359, F1_DOWN_FORT≈0.627.

Constat central de ce projet, vérifié à plusieurs reprises : un bon résultat en split
statique (80/20) ne garantit rien en walk-forward — le stacking, les features "spike"
(Hurst, semivariance, SKEW), le filtre particulaire, le regime router et le TFT ont tous
été testés rigoureusement et n'ont **pas** dépassé cette référence en walk-forward, malgré
des résultats parfois prometteurs en split statique.

## `notebooks/validation/` — une question méthodologique ou une famille de features à la fois

| Notebook | Question posée |
|---|---|
| [`VIX_CHAMPION_WF`](https://colab.research.google.com/github/LP-D/claude/blob/main/notebooks/validation/VIX_CHAMPION_WF.ipynb) | Le modèle "champion" du rapport (STRESS h=5j GradientBoosting) tient-il en walk-forward ? *(non — infirmé)* |
| [`VIX_SPIKE_SCAN`](https://colab.research.google.com/github/LP-D/claude/blob/main/notebooks/validation/VIX_SPIKE_SCAN.ipynb) | Les features de spike (Hurst, semivariance, SKEW, filtre particulaire) ajoutent-elles du signal ? *(marginal)* |
| [`VIX_REGIME_ROUTER`](https://colab.research.google.com/github/LP-D/claude/blob/main/notebooks/validation/VIX_REGIME_ROUTER.ipynb) | Router entre deux modèles selon le régime VIX bat-il le modèle GLOBAL seul ? *(non)* |
| [`VIX_TFT_WF`](https://colab.research.google.com/github/LP-D/claude/blob/main/notebooks/validation/VIX_TFT_WF.ipynb) | Le Temporal Fusion Transformer bat-il le RandomForest à h=5j ? *(non — infirmé)* |
| [`VIX_PURGED_CV`](https://colab.research.google.com/github/LP-D/claude/blob/main/notebooks/validation/VIX_PURGED_CV.ipynb) | Le walk-forward a-t-il un look-ahead subtil aux frontières de fold (purging) ? |
| [`VIX_OHLC_VOL`](https://colab.research.google.com/github/LP-D/claude/blob/main/notebooks/validation/VIX_OHLC_VOL.ipynb) | Les estimateurs de volatilité réalisée OHLC (Parkinson/GK/RS/Yang-Zhang) ajoutent-ils du signal ? |
| [`VIX_CALIBRATED_THRESHOLD`](https://colab.research.google.com/github/LP-D/claude/blob/main/notebooks/validation/VIX_CALIBRATED_THRESHOLD.ipynb) | La calibration + un seuil de décision causal améliorent-ils F1_UP_FORT/F1_DOWN_FORT ? *(oui, hors régime STRESS)* |
| [`VIX_FEATURE_SELECTION`](https://colab.research.google.com/github/LP-D/claude/blob/main/notebooks/validation/VIX_FEATURE_SELECTION.ipynb) | SHAP (méthode actuelle) vs RFE (wrapper) vs LASSO (embedded) pour la sélection de features, à isométrie stricte sur la config GLOBAL RF h=5j N=8 SMOTE — la méthode de sélection est-elle un facteur limitant ? |
| [`VIX_STACKING_WF`](https://colab.research.google.com/github/LP-D/claude/blob/main/notebooks/validation/VIX_STACKING_WF.ipynb) | Le stacking Stage 2 de `VIX_ML3` (panel 5 algos + méta-modèle, gain de +0.0105 F1_dir sur son propre split statique) tient-il en walk-forward face au GLOBAL RandomForest (recalculé dans le même run) ? |

## `notebooks/final_campaign/` — campagne exhaustive "par acquis de confiance"

Quatre notebooks **liés entre eux**, à lancer dans cet ordre (les 2 du milieu peuvent tourner
en parallèle) :

1. [`VIX_FINAL_FEATURES`](https://colab.research.google.com/github/LP-D/claude/blob/main/notebooks/final_campaign/VIX_FINAL_FEATURES.ipynb) — dataset partagé (features causales + interactions inter-tickers découvertes par SHAP). **Doit tourner en premier.**
2. [`VIX_FINAL_ML_SCAN`](https://colab.research.google.com/github/LP-D/claude/blob/main/notebooks/final_campaign/VIX_FINAL_ML_SCAN.ipynb) — grille ML complète (~66 000 configs : 6 horizons × 4 régimes × 11 N × 5 samplers × 5 algos).
3. [`VIX_FINAL_TFT`](https://colab.research.google.com/github/LP-D/claude/blob/main/notebooks/final_campaign/VIX_FINAL_TFT.ipynb) — TFT sur tous les horizons × régimes (120 configs).
4. [`VIX_FINAL_OPTUNA`](https://colab.research.google.com/github/LP-D/claude/blob/main/notebooks/final_campaign/VIX_FINAL_OPTUNA.ipynb) — affine les meilleures configs du scan ML via Optuna. **Nécessite que `VIX_FINAL_ML_SCAN` ait déjà produit des résultats.**

## `notebooks/production/` — déploiement et recherche appliquée

| Notebook | Rôle |
|---|---|
| [`VIX_PRODUCTION`](https://colab.research.google.com/github/LP-D/claude/blob/main/notebooks/production/VIX_PRODUCTION.ipynb) | Gèle la config gagnante, entraîne sur 100% de l'historique, prédit la ligne la plus récente. À relancer régulièrement. |
| [`VIX_PORTFOLIO_SIM`](https://colab.research.google.com/github/LP-D/claude/blob/main/notebooks/production/VIX_PORTFOLIO_SIM.ipynb) | Portefeuille simulé (carry VXX/contango, trend S&P500, congestion contrarian) utilisant la prédiction VIX comme overlay de risque, avec ablation avec/sans overlay ML. |

Les deux dépendent du dataset poussé par `VIX_FINAL_FEATURES`.

## `notebooks/research/` — analyse structurelle (hors pipeline ML)

| Notebook | Rôle |
|---|---|
| [`VIX_VAR_MACRO`](https://colab.research.google.com/github/LP-D/claude/blob/main/notebooks/research/VIX_VAR_MACRO.ipynb) | VAR structurel VIX ↔ macro (pente des taux, breakeven inflation, conditions financières, taux Fed) : stationnarité (ADF), cointégration (Johansen), causalité de Granger, IRF orthogonalisées (Cholesky), FEVD. Identifie des pistes de features candidates pour le pipeline ML — non validées, à confirmer séparément via SHAP + walk-forward. |
| [`VIX_VECM`](https://colab.research.google.com/github/LP-D/claude/blob/main/notebooks/research/VIX_VECM.ipynb) | Sur les folds où Johansen détecte une cointégration, un VECM (via sa représentation VAR en niveaux) bat-il la référence ML en walk-forward strict (prévision glissante, paramètres figés par fold) ? |
| [`VIX_VAR_BENCHMARK`](https://colab.research.google.com/github/LP-D/claude/blob/main/notebooks/research/VIX_VAR_BENCHMARK.ipynb) | Benchmark inconditionnel : un VAR classique estimé en niveaux (sans traitement de la non-stationnarité) contient-il, à lui seul, un signal directionnel comparable au ML ? |

## `notebooks/VIX_ML3.ipynb` — pipeline de stacking (historique, en pause)

Pipeline de stacking massif (9465+ modèles), corrigé (fuites, RAM) mais mis en pause : le
stacking a systématiquement sous-performé le meilleur modèle individuel. Conservé exécutable
pour référence. Pipeline en deux étapes : (1) panel complet de modèles ML + DL sur 6 horizons
× 4 régimes, construit une base de prédictions OOF/test ; (2) méta-modèles entraînés sur
cette base.

## `notebooks/archive/`

Historique des itérations précédentes (stacking, DL, EGARCH, walk-forward, exploration de
régimes, etc.), conservé pour référence — pas de maintenance active dessus.

## Secret GITHUB_TOKEN (requis pour la reprise/le partage de résultats)

1. Créer un [Personal Access Token GitHub](https://github.com/settings/personal-access-tokens/new)
   *fine-grained*, limité à ce repo (`LP-D/claude`), avec la permission **Contents: Read and write**.
2. Dans Colab : icône clé 🔑 (barre latérale gauche) → *Ajouter un secret* → nom `GITHUB_TOKEN`,
   valeur = le token → activer l'accès pour le notebook en cours.
3. Lancer le notebook normalement ("Exécuter tout"). Sans ce secret, les cellules de push/pull
   sont simplement ignorées.

## ⚠️ Branches `results/*` — ne jamais les merger dans `main`

Chaque notebook pousse ses résultats sur une branche dédiée `results/<nom>` (ex.
`results/vix-final-ml-scan`). **Ces branches ne doivent jamais être mergées dans `main`** —
elles ne contiennent que des artefacts générés (CSV/xlsx volumineux, jetables, régénérables
en relançant le notebook), pas du code. `main` doit rester limité à `notebooks/`, ce
`README.md` et `requirements.txt`. GitHub propose automatiquement un lien "Create a pull
request" après chaque `git push` d'une branche `results/*` — **ne pas cliquer dessus / ne
pas merger cette PR**.

**Autre piège** : Colab peut re-committer un notebook directement sur `main` à son ancien
chemin (ex. `notebooks/VIX_OHLC_VOL.ipynb`) si on l'ouvre depuis un lien/onglet resté sur
l'ancienne arborescence (avant un déplacement dans un sous-dossier) et qu'on utilise
*Fichier → Enregistrer une copie dans GitHub* — cela recrée un doublon obsolète. Toujours
ouvrir les notebooks depuis les liens de ce README (ou `notebooks/<sous-dossier>/...` à
jour) pour éviter ça.

## Versioning

Chaque notebook porte un numéro de version (`NOTEBOOK_VERSION`, affiché en tout début
d'exécution) incrémenté uniquement lors d'une évolution fonctionnelle — jamais pour un
simple correctif de bug.
