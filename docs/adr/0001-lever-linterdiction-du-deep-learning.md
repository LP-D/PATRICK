# ADR 0001 — Lever l'interdiction du deep learning et du stacking

Date : 2026-09-25 · Statut : acceptée · Détail : [`../modelisation/cadrage-dl.md`](../modelisation/cadrage-dl.md), [`../ways-of-working.md`](../ways-of-working.md)

## Contexte

Le projet d'origine (VIX) avait conclu, sur ses propres mesures, que « le DL n'a jamais battu le ML classique » et que « le stacking
perd sur 93 % des configurations ». Ces conclusions s'étaient figées en règle : ni deep learning ni stacking, par principe.
Une règle sans date ni mesure derrière elle empêche de revenir dessus quand le protocole de validation a changé.

## Décision

Le deep learning et le stacking ne sont plus exclus par principe. Ils entrent **sous le même protocole que le reste**
(walk-forward ou CPCV, purge et embargo, holdout jamais utilisé pour choisir, registre d'essais, DSR, PBO, famille BH), plus cinq
règles propres au DL (arrêt sur un bloc interne purgé, embargo ≥ max(horizon, fenêtre), plusieurs graines comptées dans le registre,
budget d'essais déclaré, capacité plafonnée par la taille d'échantillon effective). Le stacking est l'une des trois catégories
comparées explicitement (global / par régime / stacking).

## Conséquences

- Le DL séquentiel est câblé (`models/deep.py`, page `/dl`) ; SMOTE et CPCV y sont refusés. Les modèles de diffusion ne le sont pas.
- Un modèle qui ne bat pas la baseline ou la prédiction conforme n'entre pas, quelle que soit sa famille : la preuve est la même.
- Le coût d'un réseau (CPU seul) est assumé et affiché dans les profils de `/dl`.
