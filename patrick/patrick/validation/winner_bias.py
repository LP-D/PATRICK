"""Biais du gagnant : la performance holdout d'un champion est celle du MEILLEUR de plusieurs modèles lus sur le même holdout.

Le duel champion / challenger choisit sur le holdout (ADR 0005) : si k modèles de même talent l'ont lu, le meilleur affiche en moyenne
un score plus haut que son talent, de l'ordre de σ × E[max de k normales centrées réduites], σ étant l'erreur-type du score. Le registre
`holdout_access` dit combien de runs ont lu ce holdout ; ce module en déduit une AUC « corrigée du gain attendu du meilleur de k ».

Ce n'est pas une estimation sans biais du talent (les modèles ne sont ni indépendants ni de même talent), c'est un ordre de grandeur :
une AUC de 0,56 lue par 30 runs sur 60 observations indépendantes ne bat plus le hasard une fois le gain attendu retiré. L'affichage le
montre à côté de l'AUC brute, il ne remplace rien.
"""
from __future__ import annotations

import math

from scipy import stats


def expected_max_standard_normal(k: int) -> float:
    """E[max de k normales centrées réduites indépendantes] (approximation de Blom, erreur < 0,01 pour k <= 1000) ; 0 pour k <= 1."""
    if k <= 1:
        return 0.0
    return float(stats.norm.ppf((k - 0.375) / (k + 0.25)))


def auc_standard_error(auc: float, n_pos: float, n_neg: float) -> float | None:
    """Erreur-type de l'AUC (Hanley et McNeil, 1982) ; None si une classe est vide."""
    if n_pos <= 0 or n_neg <= 0:
        return None
    q1, q2 = auc / (2 - auc), 2 * auc * auc / (1 + auc)
    var = (auc * (1 - auc) + (n_pos - 1) * (q1 - auc * auc) + (n_neg - 1) * (q2 - auc * auc)) / (n_pos * n_neg)
    return math.sqrt(max(var, 0.0))


def deflated_auc(auc: float | None, n_rows: int, horizon: int, share_up: float, n_readers: int) -> dict | None:
    """AUC du holdout corrigée du gain attendu du meilleur de `n_readers` modèles. `n_rows` lignes au pas quotidien chevauchent leur
    horizon : effectif indépendant ≈ n_rows / horizon (blocs n/h, ADR 0003). None si l'AUC ou l'effectif manque."""
    if auc is None or not math.isfinite(auc) or n_rows <= 0 or not 0 < share_up < 1:
        return None
    n_eff = n_rows / max(int(horizon), 1)
    se = auc_standard_error(auc, n_eff * share_up, n_eff * (1 - share_up))
    if se is None:
        return None
    k = max(int(n_readers), 1)
    gain = se * expected_max_standard_normal(k)
    adjusted = auc - gain
    return {"auc": round(auc, 4), "n_eff": round(n_eff, 1), "se": round(se, 4), "n_readers": k, "expected_gain": round(gain, 4),
            "adjusted": round(adjusted, 4), "beats_chance": bool(adjusted - 1.645 * se > 0.5)}
