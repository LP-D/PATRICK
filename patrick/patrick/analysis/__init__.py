"""Analyse détaillée des entraînements : moteur de lecture seule (aucune écriture en base, aucun effet sur un run en cours).

- `stats_core`  : briques statistiques pures (intervalles, ROC, calibration, bootstrap par blocs...), sans base ni réseau ;
- `frames`      : lecture d'un essai (prédictions, niveaux de la cible dans le snapshot du run, rendements futurs) ;
- `sections`    : une fonction par section de la page d'un run ML/DL, JSON prêt pour le navigateur ;
- `rl_sections` : idem pour un run de reinforcement learning ;
- `hub`         : vues inter-runs (liste de tous les entraînements, cartes de comparaison).

Voir `docs/superpowers/specs/2026-10-20-analyse-des-entrainements-design.md`.
"""
