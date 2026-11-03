"""Économétrie d'une série à la fois : calculs purs (pas de web, pas de base, pas de réseau).

Chaque fonction prend une `pd.Series` (ou des tableaux) et renvoie un dict de types JSON natifs (voir `exploration.studies.clean`).
La couche web (`webapp/econometrics_routes.py`) charge les séries, met en cache et affiche ; ici on ne fait que calculer.

Règle commune : un modèle ajusté sur tout l'échantillon est DESCRIPTIF. Les prévisions (`forecast_eval`) réestiment sur le passé
seulement et ne regardent jamais l'avenir. Un modèle qui ne converge pas est renvoyé avec `converged=False` et son message, jamais retiré.
Cadrage : `docs/superpowers/specs/2026-11-03-econometrie-serie-design.md`."""
