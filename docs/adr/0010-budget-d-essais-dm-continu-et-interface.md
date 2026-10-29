# ADR 0010 — Budget d'essais, test de Diebold-Mariano sur le Brier, runs sans évaluation, interface

Date : 2026-10-29 · Statut : acceptée · Code : `tracking/trial_budget.py` (+ `GET /api/trial-budget`, `patrick budget`), `pipeline/engine.py` (`dm_brier`, `_final_dm_brier`, `_finish_runs`), `tracking/db.py` (`save_dm_brier`, `get_dm_brier`), `fund/asset_classes.py`, `validation/placebo.py`, `webapp/` (`static/table_tools.js`, `_run_tabs.html`, bloc « À faire » de la synthèse, méthode/placebo/Brier sur la page d'un run, `nav_registry.py`), migration 0048 · Tests : `tests/test_trial_budget.py`, `tests/test_method_v2.py`, `tests/test_run_detail_method.py`, `tests/test_fund_asset_classes.py`

## Contexte

Suite de la critique du 28/10/2026 (ADR 0007 : alignement des devises, ADR 0008 : méthode d'évaluation 2, ADR 0009 : stockage) : restaient des compléments de
méthode et les points d'interface.

Mesure du 29/10 sur la vraie base : **113 runs « terminés » n'ont aucun essai gagnant**. 80 datent d'août (lancements multi-horizons d'avant l'export par horizon :
seul l'horizon gagnant avait un modèle exporté ; comportement d'alors, corrigé depuis). **33 datent d'octobre : zéro évaluation**, tous sur des séries FRED
mensuelles ou trimestrielles (PCEPILFE, CPILFESL, PAYEMS, CPIAUCSL, GDP, FEDFUNDS) à 1 jour d'horizon : la série est presque toujours inchangée, tous les plis sont
exclus faute de lignes, et le run se terminait « done » sans un mot.

## Décision

1. **Un run sans aucune évaluation est un échec, avec la raison** (`_finish_runs`) : statut `failed`, message « aucune configuration évaluable à h=… ». Il apparaît
   dans les échecs récents de la synthèse. Le résultat renvoyé par `run_pipeline` reste inchangé (grille vide, `final_best = None`).
2. **Budget d'essais avant lancement** (`tracking/trial_budget.py`) : pour chaque horizon, essais déjà comptés pour la cible (`trial_registry`), essais ajoutés par le run
   prévu (grille du scan + essais d'Optuna), et le seuil de Sharpe sous H0 (`expected_max_sharpe(N, 1)`, en écarts-types) avant / après. API `GET /api/trial-budget?target=&horizons=`
   et commande `patrick budget`. Pas encore branché au formulaire de lancement.
3. **Choisir des modèles pour une stratégie compte un essai** : `patrick fund autopilot-classes --create` (et la page) enregistre un essai par (cible, horizon) retenu
   (source `simulation`, détail `fund_selection:<stratégie>`), comme une simulation. Compté à la mise en place seulement, jamais à chaque réévaluation quotidienne du pilote.
   Limite : le choix de la meilleure *classe* sur son P&L fictif n'est toujours pas corrigé (aucun Sharpe déflaté au niveau d'une stratégie n'existe encore).
4. **Test de Diebold-Mariano sur un score continu** : erreur quadratique de P(hausse) du modèle (Brier) contre celle d'une baseline probabiliste constante, le taux de hausse de
   l'entraînement, sur le holdout (`dm_brier`, table `dm_brier_result`, migration 0048 : `dm_result.kind` est contraint à deux valeurs). Une perte 0/1 jette la confiance du
   modèle ; le Brier la garde. Calculé pour tout run walk-forward qui a des probabilités ; diagnostic, jamais dans la famille BH.
5. **Interface** : la page d'un run affiche sa méthode d'évaluation et sa règle d'alignement (une pastille « Méthode 2 · alignement 2 »), le placebo de décalage (AUC réel →
   retardé, verdict) et le DM sur le Brier ; un run de change d'avant la correction est signalé. Une barre d'onglets relie le détail, l'analyse et le comparateur d'un run.
   Tout tableau `data_table` de 8 lignes ou plus gagne le tri au clic, un filtre texte et l'export CSV (`table_tools.js`, amélioration progressive ; les tableaux repliables
   gardent leur repli). La synthèse affiche un bloc « À faire » (échecs récents, runs suspects, file d'attente, champions de change à remplacer) avec un lien par ligne.
   « Qualité des données » devient une page enfant du hub « Données » (une entrée de navigation en moins).

## Non fait

- **Variables de niveau brut** (`raw_level`, non stationnaires) : brancher `fracdiff` ou retirer la famille change les variables de tous les runs : à faire sous un numéro de version de méthode 3, avec mesure sur un panel de cibles.
- **Cible de volatilité** : un nouveau type de cible (`target_kind`) à brancher dans le moteur, les baselines (HAR-RV) et la simulation.
- **Calibration par défaut** pour les runs du fonds : change l'entraînement de tout run neuf (jeu d'ajustement scindé) ; même numéro de version de méthode 3.
- **Mondes à pertes égales** pour trancher le DM bilatéral, **survivants de mutation** (dsr 54 %, diebold_mariano 70 %).
- **Interface** : navigation à ~20 entrées (la barre est déjà en arborescence repliable ; huit pages de marchés restent des feuilles), page de run réellement fusionnée (les trois pages
  gardent leurs routes, reliées par des onglets), comparateur unique, annotations d'événements et réticule synchronisé sur les graphiques, petits multiples, diagramme de fiabilité
  à côté de chaque p_up, N_eff à côté de chaque métrique, 31 `style="…"` en ligne à ramener aux jetons, budget d'essais dans le formulaire de lancement.

## Conséquences

- 33 runs d'octobre restent « done » en base (rien n'est réécrit) ; les nouveaux de ce type sont en échec avec la raison.
- Les runs d'avant le 29/10/2026 n'ont ni placebo ni DM sur le Brier : la page l'indique.
