"""Test de Diebold-Mariano (1995) : la précision prédictive de deux modèles
diffère-t-elle significativement, ou l'écart observé est-il compatible avec
du bruit d'échantillonnage ? Formulation originale sur une perte quadratique
(régression) — généralisée ici à une perte 0/1 (mal classé = 1, bien classé
= 0), adaptée à la cible de classification 4-classes du projet. H0 : les deux
modèles ont la même précision prédictive.
"""
from __future__ import annotations

import numpy as np
from scipy import stats


def diebold_mariano(loss_a: np.ndarray, loss_b: np.ndarray, h: int = 1) -> dict:
    """`loss_a` : perte du modèle candidat, `loss_b` : perte de la baseline de
    comparaison, alignées observation par observation (même ordre, même
    longueur). `h` : horizon de prévision — la série de différences de perte
    peut être autocorrélée jusqu'au lag h-1 (chevauchement des fenêtres de
    label), la variance du test l'intègre plutôt que de supposer
    l'indépendance.

    `dm_stat` < 0 : le candidat a une perte moyenne plus faible (meilleur) que
    la baseline. `p_value` : bilatéral, H0 = précisions égales."""
    d = np.asarray(loss_a, dtype=float) - np.asarray(loss_b, dtype=float)
    n = len(d)
    if n < 10:
        return {"dm_stat": np.nan, "p_value": np.nan, "n_obs": n, "mean_loss_diff": np.nan}

    d_mean = float(np.mean(d))

    var_d = float(np.var(d, ddof=0))
    for lag in range(1, max(h - 1, 0) + 1):
        if lag >= n:
            break
        cov = float(np.cov(d[:-lag], d[lag:], ddof=0)[0, 1])
        var_d += 2 * cov
    var_d = max(var_d, 1e-12)

    dm_stat = d_mean / np.sqrt(var_d / n)
    if not np.isfinite(dm_stat):
        dm_stat = 0.0
    p_value = float(2 * (1 - stats.norm.cdf(abs(dm_stat))))
    return {
        "dm_stat": round(float(dm_stat), 4),
        "p_value": round(p_value, 4),
        "n_obs": n,
        "mean_loss_diff": round(d_mean, 6),
    }
