"""Résultat réel d'un modèle : ses prédictions quotidiennes (`split='live'`) dont l'horizon est écoulé, jugées sur la direction.

Le duel des champions, la sélection des fonds et le conseiller de relances ne lisaient que le holdout. Mesuré le 2026-11-13 sur les
3 375 champions : 20 075 prédictions réelles jugées, 49,5 % de bonne direction alors que 58,8 % des mouvements étaient des hausses
(les modèles n'en annonçaient que 48,8 %), et une corrélation de +0,07 entre la précision du holdout et la précision réelle d'une
cellule. `failing` repère un modèle dont le réel est nettement sous le hasard ; il sert de garde-fou, pas de classement : avec une
vingtaine de jugements par cellule, seul un écart franc se distingue du bruit.

Rappel : pour une ligne `live`, `y_true` est BINAIRE (1,0 = hausse réalisée), pas l'indice de classe 0-3 des splits `test` et
`holdout` (`predict.py`) ; `y_pred` reste l'indice de classe (2 et 3 = hausse).
"""
from __future__ import annotations

import math
import sqlite3

MIN_JUDGED = 20          # jugements réels minimaux avant de conclure
Z_FAIL = -1.645          # seuil unilatéral à 5 % : nettement sous une chance sur deux
_CHUNK = 500


def records(conn: sqlite3.Connection, trial_ids: list[int]) -> dict[int, tuple[int, int]]:
    """`{essai: (jugements, bonnes directions)}` des essais qui ont au moins une prédiction réelle jugée."""
    out: dict[int, tuple[int, int]] = {}
    ids = sorted(set(trial_ids))
    for start in range(0, len(ids), _CHUNK):
        chunk = ids[start:start + _CHUNK]
        # INDEXED BY : sans lui SQLite part de l'index sur `split` et parcourt toutes les lignes `live` de la base
        for trial_id, n, hits in conn.execute(
                "SELECT trial_id, COUNT(*), SUM((y_pred >= 2) = (y_true >= 0.5)) FROM prediction INDEXED BY sqlite_autoindex_prediction_1 "
                f"WHERE trial_id IN ({','.join('?' for _ in chunk)}) AND split = 'live' AND y_true IS NOT NULL GROUP BY trial_id", chunk):
            out[int(trial_id)] = (int(n), int(hits or 0))
    return out


def z_score(n: int, hits: int, horizon: int) -> float | None:
    """Écart au hasard, en écarts-types. Des prédictions quotidiennes à `horizon` jours se recouvrent : leurs jugements ne sont pas
    indépendants, la variance est donc gonflée d'un facteur `horizon` (n jugements valent environ n / horizon jugements indépendants)."""
    if n <= 0:
        return None
    return (hits - n / 2) / math.sqrt(n * max(1, int(horizon)) / 4)


def failing(n: int, hits: int, horizon: int) -> bool:
    """Assez de jugements réels, et une part de bonnes directions nettement sous une chance sur deux."""
    z = z_score(n, hits, horizon)
    return n >= MIN_JUDGED and z is not None and z < Z_FAIL
