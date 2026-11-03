"""Événements de résultats : de la newsletter collée à des événements datés, event study, bibliothèque d'études.

Principe : PATRICK est une plateforme d'exploration. Chaque étude est une brique activable et paramétrable ; seules les
contraintes techniques dures bloquent. Tout est calculé une fois puis lu depuis le cache (tables `earn_*`, créées par
`store.ensure_schema`, jamais par `db.migrate()`). Uniquement des données gratuites (Yahoo) : ce qui exige une donnée
payante ou un historique daté qu'on n'a pas est affiché comme indisponible, ou accumulé en instantané quotidien pour
devenir exploitable plus tard (`snapshots.py`).

Ordre des modules : `parse` (texte -> noms) -> `resolve` (noms -> lignes de cotation) -> `calendar` (date, BMO/AMC, jour de
réaction J0) -> `engine` (rendement anormal, CAR, BHAR, liquidité) -> `pipeline` (ingestion, panel) -> `studies/` (A à M)
-> `model` (amplitude, direction, score composite).
"""
