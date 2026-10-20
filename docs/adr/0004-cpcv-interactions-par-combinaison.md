# ADR 0004 — CPCV : formules d'interaction découvertes par combinaison

Date : 2026-10-19 · Statut : acceptée · Code : `pipeline/engine.py::_cpcv_interaction_formulas`

## Contexte

En CPCV (validation croisée purgée combinatoire), l'historique est coupé en groupes et chaque combinaison en teste quelques-uns. Les
formules d'interaction (quelles paires de variables, quelle opération) étaient découvertes **une fois**, avec les étiquettes du
groupe 0. Or le groupe 0 est un groupe de test dans 6 combinaisons sur 21 (7 groupes, k = 2) : le choix des variables de ces
combinaisons était informé par les étiquettes qu'on prétendait prédire.

## Décision

Chaque combinaison découvre ses formules sur ses seules barres d'entraînement, purgées sur l'horizon le plus long du run et mises sous
embargo. Le modèle exporté a les siennes, découvertes sur tout l'historique (rien n'est évalué dessus). Le walk-forward est inchangé
(sa découverte porte déjà sur le premier pli d'entraînement, antérieur à tout test).

## Conséquences

- Coût : une découverte par combinaison au lieu d'une (21 au lieu de 1 avec les valeurs par défaut).
- Le golden master CPCV a changé ; régénéré par la CI (`golden-regen/*`).
- Reste approximé et documenté : les seuils de classes et régimes de `run_target` sont ajustés sur le seul groupe 0 (effet d'échelle,
  pas de choix de variables) ; les variables paramétriques (EGARCH, Kalman, HMM) sont ajustées une fois sur tout l'historique.
