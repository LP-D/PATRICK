# ADR 0002 — Les PC suivent une branche `stable`, validée par la CI

Date : 2026-10-20 · Statut : acceptée, **à fusionner** (voir plus bas) · Code : `patrick/desktop/update.py`, `.github/workflows/tests.yml` (job `promote`)

## Contexte

L'application de bureau se mettait à jour par avance rapide sur `origin/main`, sans étiquette ni version. Un `main` cassé cassait donc
l'application des deux PC au prochain démarrage ; seul un échec d'installation des dépendances provoquait un retour en arrière.
La CI de `main` est restée rouge de nombreux jours en octobre 2026 sans que rien n'arrête personne.

## Décision

Une branche `stable` avance, par avance rapide, sur le commit de `main` qui vient de passer **toutes** les vérifications (suite rapide
sous deux versions de Python, suite lente). Les PC ne suivent que `stable`. Tant que `stable` n'existe pas, rien n'est installé et le
message le dit. Une installation neuve part de `stable` si elle existe.

## Conséquences

- Un `main` rouge ne se propage plus ; le prix est un délai d'environ une demi-heure (la suite lente) entre un push et sa disponibilité.
- Si la CI reste rouge, `stable` ne bouge pas : c'est voulu, et visible (la dernière version installée ne change pas).
- À la première fusion, `stable` est créée par la première exécution verte ; d'ici là, les PC déjà installés restent sur leur version.
- Les PC doivent tourner sous Python ≥ 3.11 (la version 3.10 est retirée en même temps, fin de support en octobre 2026).
