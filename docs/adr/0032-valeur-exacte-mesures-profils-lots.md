# ADR 0032 — Valeur exacte : mesures propres, profils (dont « max ») et lots prêts à lancer par objectif

Date : 2026-11-27. Statut : acceptée. Code : `models/value.py` (`value_metrics` : `Cov80`, `MAE_skill`, `MZ_slope`, `Gain_sign`),
`pipeline/engine.py` (erreurs hors échantillon passées aux mesures), `validation/metric_panel.py` (`VALUE_PANEL`, `VALUE_EXTRA`, `R2_TOLERANCE`,
règle `IC+R2_oos`, `keys_for`, `value_rank_key`, mesures « à cible »), `tracking/kpi_summary.py`, `tracking/run_queries.py`, `tracking/history.py`,
`webapp/asset_view.py`, gabarits (`run_detail`, `_run_panel`, `runs`, `target`, `compare_runs`, `_asset_signals`, `_components`),
`config/training_profiles.py` / `dl_profiles.py` / `rl_profiles.py` (profils `value_*`, `dl_value_*`, `max`, `value_max`, `dl_max`,
`dl_value_max`, `rl_max`, champ `task`, coût `max`), `webapp/launch_batches.py` (lots par objectif), `_launch_batches.html`,
`static/launch_batches.js`, `webapp/todo_actions.py`, `tracking/launch_advice.py`.
Tests : `tests/validation/test_value_panel.py`, `tests/webapp/test_value_launch.py`.

## Contexte

Demande de Léon (27/11) : « on a ajouté les modèles qui prédisent une valeur ; observe ce qui a été fait, améliore le pipeline de lancement
(lots prêts à lancer, profils d'entraînement) pour qu'il soit adapté ; ajoute un profil max pour tous ; réinterprète les mesures pour ce
nouveau type ».

Ce qui existait (ADR 0029) : l'objectif `task: value`, l'étiquette `symbole__val`, les régresseurs, les mesures `IC`, `R2_oos`, `MAE`, `RMSE`,
`Hit_sign`, un duel sur l'IC seule. Mais le panneau affiché partout restait celui de la direction (AUC, Brier, MCC, bonne direction, calculés sur
les probabilités tirées des erreurs), les lots comptaient un job de valeur comme la direction de sa cible, aucun profil ne préparait la valeur
exacte, et le profil « robust » était refusé par le formulaire (CPCV + présélection progressive cochée par défaut).

Ce qui a été fait (base de PC_de_LPD, 27/11) : 90 runs de valeur, tous des MLP sans réglage à 8 variables, 14 cibles européennes, 6 horizons.
IC médiane du holdout : -0,005 à 1 jour, +0,036 à 2, +0,069 à 3, **+0,124 à 5, +0,129 à 7**, +0,107 à 10 jours. R² hors échantillon moyen
-0,025 (de -0,95 à +0,09), bon signe 52,9 %. Aucun modèle d'arbres en valeur exacte.

## Décisions

1. **Un panneau propre à la valeur exacte**, même logique que celui de la direction, quatre mesures dans cet ordre :
   `IC` (ordre des rendements, équivalent de l'AUC), `R2_oos` (amplitude contre « rendement nul »), `Hit_sign` (bon signe), `Cov80`
   (couverture réelle de l'intervalle de prévision à 80 % : la fiabilité de l'incertitude, équivalent du Brier, puisque les probabilités de
   classe que lisent les fonds viennent de ces mêmes erreurs). Mesures secondaires sur la fiche d'un run : `MAE_skill` (1 − MAE / MAE de
   zéro, le R² sur l'erreur absolue), `MZ_slope` (pente réalisé / prévu : 1 = amplitudes justes), `Gain_sign` (rendement moyen capté en suivant
   le signe, avant frais), `MAE`, `RMSE`. Une mesure peut avoir une cible (`Cov80` : 0,80, `MZ_slope` : 1) : le « meilleur » est le plus proche.
2. **Le panneau suit le genre du run** : fiche d'un run (en-tête, contrôle final, classements par algorithme / nombre de variables / horizon),
   panneau latéral de l'Historique, onglet « Valeur exacte » de l'Historique, page d'une cible `…__val`, comparaison de runs, champion de valeur
   sur la fiche d'un actif. Le panneau de direction reste calculé et affiché ailleurs (l'onglet « Tous » mélange les genres sous ses colonnes).
   La synthèse d'un lancement classe les candidats d'un run de valeur sur l'IC puis le R² (`value_rank_key`), plus sur l'AUC.
3. **Règle du duel de la catégorie** : le challenger gagne s'il ordonne mieux (IC strictement plus haute) **sans** dégrader ses amplitudes
   (R² hors échantillon au plus `R2_TOLERANCE = 0,01` sous celui du champion) ; sans R² d'un côté, l'IC seule (comme avant).
4. **Profils** : un profil porte un objectif (`task`). ML : `value_quick`, `value_standard`, `value_swing` (horizons 5-20 jours, là où l'IC
   est positive), `value_r2` (choisi sur le R²), `value_deep`, `value_max`. DL : `dl_value_quick` (le cadre des 90 premiers runs),
   `dl_value_sequence`, `dl_value_swing`, `dl_value_max`. La galerie se groupe par objectif ; un profil de valeur pré-sélectionne l'objectif
   et affiche ce qu'il implique (walk-forward, sans rééchantillonnage ni empilement, champions à part). `identify` ne donne jamais un profil de
   direction à un run de valeur.
5. **Profil « max » partout** (coût `max`, « très long », avertissement « une cible, peu d'horizons, la nuit ») : la recherche la plus large
   que le formulaire accepte sans changer ce qui juge le modèle (holdout, historique minimum, régime GLOBAL). ML : 5 algorithmes, criblage
   exhaustif de 5 à 30 variables, 4 options de rééchantillonnage, 8 plis purgés avec embargo, 300 essais Optuna sur 3 finalistes (5 plis),
   interactions et pré-filtre élargis, empilement de 40 modèles, calibration. DL : 5 architectures, 60 essais sur 3 finalistes, 7 plis,
   6 à 20 variables, réseaux 3 × 128 sur 60 barres, 100 époques, 5 graines. RL : toutes les familles, 40 variables, mémoire de 20 jours,
   3 × 128, 200 000 pas, 5 agents, 8 plis, 5 000 tirages ; les garde-fous du moteur 2 restent. Valeur exacte : la recherche ML / DL « max »
   sans ce que l'objectif refuse. Le conseil de profil par durée (`launch_advice`) ne propose que l'échelle de direction (max compris).
6. **Lots comptés par objectif** : un run `X__val` ou un job de valeur ne « fait » plus la direction de X, et inversement (`executed_pairs`,
   `pending_targets`, `pending_pairs` dont la clé dit l'objectif pour « À faire », `only_missing` lit l'objectif soumis). Les pages ML et DL
   ajoutent sous les lots de direction une section « Valeur exacte » : là où la direction a un signal (signal regroupé, sans modèle de valeur),
   déjà essayées dans l'autre famille (réseaux sans arbres, ou l'inverse), horizons jamais lancés, une carte par classe. Chaque carte bascule
   l'objectif du formulaire (`data-task`).
7. **Corrections** : le profil « robust » décoche la présélection progressive (la CPCV la refuse). Le résumé de l'accueil
   (`tracking/home.home_summary`) levait `KeyError('value')` dès le premier run de valeur terminé : l'instantané « home-summary » de la vraie
   base ne s'était plus rafraîchi depuis le 27/11 à 11 h 48 ; il compte maintenant la valeur exacte à part (ligne « Valeur exacte » du
   tableau des genres). La synthèse par actif (`class_overview.model_stats_by_asset`) rangeait les runs de valeur avec la direction et les
   classait sur l'AUC : ils ont leur colonne, classée sur l'IC.

## Conséquences

- Les nouvelles mesures n'existent que pour les runs lancés après ce changement : les 90 runs du 27/11 affichent « — » pour `Cov80`,
  `MAE_skill`, `MZ_slope` et `Gain_sign` (leurs prédictions de holdout ne gardent pas le rendement réalisé : pas de rattrapage possible).
- Un challenger de valeur meilleur en IC mais dont le R² chute de plus d'un point ne prend plus le titre.
- Le conseiller de réentraînement (`retrain_advisor`) reste calibré sur la direction : le lot « runs conseillés » ne contient pas de run de
  valeur exacte (leurs étiquettes ne sont pas dans l'univers des cibles), ce qui évite des suggestions refusées (SMOTE, empilement, CPCV).
- Un profil « max » est volontairement hors de portée d'un lot entier : 13 configurations de variables × 5 algorithmes × 4 options de
  rééchantillonnage en criblage exhaustif, puis Optuna, par horizon.
