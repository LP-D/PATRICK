# ADR 0005 — Registre d'accès au holdout terminal

Date : 2026-10-19 · Statut : acceptée · Code : `tracking/migrations/0038_holdout_access.sql`, `pipeline/engine.py::_evaluate_holdout`

## Contexte

Le holdout n'était protégé que par discipline : « une seule lecture, jamais pour choisir ». En fait il est lu à plusieurs endroits —
l'évaluation finale d'un run, le diagnostic qui note tous les essais de la grille, et le duel champion / challenger, qui **choisit**
un modèle dessus — et rien ne disait combien de fois, ni pour quel run.

## Décision

Toute lecture passe par `_evaluate_holdout`, qui l'inscrit dans `holdout_access` (cible, horizon, run, fenêtre lue, lignes, finalité :
`final_eval`, `diagnostic`, `champion_duel_challenger`, `champion_duel_champion`). Table en ajout seul, sans clé étrangère (un run
supprimé garde ses lectures), fusionnée entre PC par union.

## Conséquences

- On peut dire « ce holdout a été lu N fois, dont K pour choisir un modèle » (page d'un run, `trackstats.holdout_reads`).
- Le registre démarre à sa création ; les lectures antérieures sont inconnues et le disent.
- Le duel reste une sélection sur le holdout : la performance holdout d'un champion est celle d'un gagnant. Le registre le rend
  visible ; il ne le supprime pas. Le simulateur, qui relit des prédictions holdout déjà stockées, n'est pas encore compté.
