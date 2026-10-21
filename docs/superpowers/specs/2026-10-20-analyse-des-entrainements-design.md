# Analyse détaillée de tous les entraînements (et suite de la feuille de route)

Date : 2026-10-20. Demande de Léon : « pour tous les entraînements, voir les analyses faites — walk-forward, graphiques de ce qu'on
prédit contre la réalité, tout hyper détaillé ; ajouter des pages si besoin ; ne pas s'arrêter tant que tout n'est pas fait ; on verra
les erreurs possibles à la fin ». Une feuille de route de 8 blocs a été collée avec la demande : elle fait partie du périmètre, traitée
après le cœur.

## 1. Constat

La base garde déjà tout ce qu'il faut pour un run ML/DL : `prediction` (date, pli, échantillon test/holdout/live, classe réelle, classe
prédite, confiance, P(hausse) brute et calibrée), `fold_metric` (métriques par pli et par échantillon), `baseline_metric`, `dm_result`,
`feature_stability`, `trial` (tous les essais), `screening_decision`, et le snapshot exact des données (`run.snapshot_id` → lac de données).
Un run RL garde dans son résultat les courbes d'équité hors échantillon, les plis, les statistiques, l'usage des variables.
La page `/runs/{id}/detail` n'affiche que des **tableaux** : aucun graphique, aucun « prédit contre réel ».

## 2. Décisions

- **Moteur d'analyse sans effet de bord** (`patrick/analysis/` : `stats_core.py`, `frames.py`, `sec_*.py`, `rl_sections.py`, `registry.py`) : fonctions pures sur des tableaux
  numpy/pandas lus dans la base **en lecture seule**, testables sans base. Toute lecture de `prediction` passe par la clé primaire
  (`trial_id = ?`), jamais par `idx_pred_split` (180 s sur la vraie base, voir `launch-batches-run-page`).
- **Vérité terrain en rendement** : la classe réelle ne dit pas de combien le marché a bougé. Le niveau de la cible est relu dans le
  snapshot **du run** (`DataStore`, colonne de la cible seule) et le rendement futur à l'horizon `h` est recalculé comme le pipeline
  (`s.shift(-h)/s - 1`, cible alpha : `alpha_labels`). Sans niveau disponible, les sections qui exigent un rendement le disent et
  restent vides ; le reste s'affiche.
- **Une page par run, sections chargées après coup** (`/runs/{id}/analyse`, `lazy` + JSON `/api/runs/{id}/analysis/{section}`), cadre
  affiché tout de suite. Graphiques en SVG sans dépendance (`static/charts.js` étendu), couleurs par variables CSS.
- **Une page pour tous les entraînements** (`/analyses`) : liste filtrable ML/DL/RL, cartes de comparaison inter-runs (carte
  cible × horizon, distribution par algorithme, budget d'exploration).
- **Aucun changement du pipeline d'entraînement** dans cette partie : hachage de configuration, golden master et worker inchangés.
  La suite de la feuille de route qui touche l'entraînement (cibles alternatives, différenciation fractionnaire) est livrée
  **désactivée par défaut**, hors du hachage tant qu'elle n'est pas choisie.
- **Textes** : tout par `t('clé')` (FR/EN), phrases courtes (règles des « ? » de `help.js`), cellules de tableau avec liens en blocs
  `{% set %}` (piège Jinja `~` + Markup).

## 3. Contenu de la page d'un run ML/DL

1. **Protocole** : frise des plis (entraînement, validation, purge, test, holdout) à partir des dates réellement prédites ; effectifs.
2. **Prédit contre réel** : prix de la cible avec les appels justes/faux ; rubans de classes réelles et prédites ; P(hausse) contre la
   direction réalisée ; taux de réussite glissant avec bande binomiale ; nuage P(hausse) × rendement réalisé (corrélation de rang).
3. **Matrices de confusion** 4 classes et haut/bas, par échantillon et par pli ; précision/rappel/F1 par classe ; ROC et PR.
4. **Calibration** : diagramme de fiabilité (brute et calibrée), histogramme des probabilités, Brier décomposé, ECE par pli.
5. **Plis** : métriques pli par pli contre les baselines, dispersion, tests binomiaux.
6. **Stratégie simulée** : équité long/court, long/à plat, achat-garde ; drawdown ; Sharpe glissant ; coûts réglables dans la page.
7. **Erreurs** : par régime de volatilité, de tendance, par année, mois, jour de semaine, niveau de confiance, classe ; plus longues séries d'erreurs.
8. **Variables** : importance native du modèle retenu, fréquence de sélection par pli, stabilité (Jaccard).
9. **Essais** : tous les essais (nuage N variables × score, par algorithme), dépenses d'exploration, déclassés au criblage.
10. **Robustesse** : permutation par blocs, bootstrap par blocs, décalage temporel (dégradation de l'accuracy en décalant les prédictions),
    stabilité par sous-échantillons ; DM, FDR, DSR, PBO déjà calculés rappelés.
11. **Holdout et live** : écart test → holdout, lectures du holdout, prédictions live contre réalisé.
12. **Lecture guidée** : texte pédagogique produit à partir des métriques (jamais de conseil d'achat/vente).

Run CPCV : mêmes sections sur les chemins (`test_path`) avec distribution des chemins à la place de la frise des plis.
Run RL : plis, équité agent contre acheter-garder/momentum/à plat, drawdowns, expositions, rendements, Sharpe glissant, graines, variables.

## 4. Feuille de route collée (après le cœur)

Livrée par lots, chacun testé et fusionné : B1 garde-fous (budget d'exploration, registre du holdout) · B2 lancement sans coder · B3 données ·
B4 explorer et comprendre · B5 prédiction, suivi, modèles · B6 portefeuille et risque · B7 cibles et modèles étendus · B8 confort
et plateforme. L'état exact (fait / déjà présent / reporté et pourquoi) est tenu dans `docs/ops/feuille-de-route-etat.md`.

## 5. Limites assumées

- Le niveau de prix vient du snapshot du run ; un run antérieur à la conservation des snapshots n'a pas de section « rendements ».
- Les rendements à horizon `h` > 1 se chevauchent : l'équité les moyenne par `1/h` (documenté dans la page), la significativité
  se mesure par blocs de longueur `h`.
- Importance SHAP globale et ablation par famille exigent de ré-entraîner ou de reconstruire les variables : proposées comme tâches à
  lancer (file de jobs), jamais calculées à l'ouverture d'une page.
