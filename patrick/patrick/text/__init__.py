"""Analyse textuelle des news (roadmap, bloc « news »).

Tout ce qui est daté passe par `patrick.features.event_features` (garde d'horodatage de publication) avant d'atteindre
une variable : une news n'est visible qu'à partir de `max(heure de publication, première observation)`.
"""
