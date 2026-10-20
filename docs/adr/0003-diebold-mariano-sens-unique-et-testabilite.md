# ADR 0003 — Diebold-Mariano : sens « meilleur » dans la famille BH, et refus sous 15 blocs

Date : 2026-10-19 · Statut : acceptée · Code : `validation/diebold_mariano.py`, `tracking/stats.py::fdr_across_targets` · Mesures : `KNOWN_ISSUES.md`

## Contexte

Le test de Diebold-Mariano (DM) compare un modèle à sa meilleure baseline sur le holdout. Deux défauts mesurés :
1. à l'horizon h > 1, les pertes de lignes voisines partagent h-1 barres : n lignes valent environ n/h observations indépendantes.
   Simulé sous H0 (holdout de 15 mois), la correction de Harvey-Leybourne-Newbold et la fenêtre d'autocovariance ne suffisaient pas :
   le test à 5 % rejetait ~7 % avec 15 blocs, ~22 % avec 2,6 blocs, plus de 80 % à h = 504 ;
2. une p-value bilatérale prise telle quelle faisait passer un modèle SIGNIFICATIVEMENT MOINS BON que sa baseline pour une découverte
   (corrigé le 2026-10-07). Sur 12 marches aléatoires, l'ancien calcul rejetterait 3 cibles ; le calcul actuel, aucune.

## Décision

- Sous 15 blocs indépendants (`n < 15 × h`, pour h > 1), le résultat est **non testable** : pas de p-value, raison
  `horizon_too_long` ; le moteur ne l'enregistre pas et la cible entre dans la famille BH avec p = 1.
- La famille BH ne lit que le sens « le modèle fait mieux » (p unilatérale).

## Conséquences

- Avec un holdout de 15 mois, le DM n'est plus calculé dès h ≈ 21 (donc pas à 252, ni aux horizons « descriptifs » 504 et 756).
- Le DM est peu puissant (aucune p-value « meilleur » < 5 % sur trois mondes à signal fort) : il protège, il ne démontre pas.
  Un score continu (Brier, log-loss) serait plus puissant ; non fait.
- Le seuil de 15 n'est pas une convention : il vient de la simulation, et `tests/test_diebold_mariano.py` en garde la frontière.
