"""Petit échantillon : score de fiabilité affiché sur chaque statistique, et rétrécissement bayésien empirique (partial pooling).

Un titre a 12 à 40 annonces : aucune statistique titre par titre n'est fiable seule. Deux réponses :
- un SCORE DE FIABILITÉ (0-100) visible partout : combine le nombre d'événements, la dispersion (erreur-type relative) et
  l'ancienneté. Sous `min_events`, le niveau est « insuffisant » quoi qu'en dise le reste ;
- le SHRINKAGE : la moyenne d'un titre est ramenée vers celle de son secteur, d'autant plus fort que le titre a peu d'événements
  (poids w = tau² / (tau² + sigma²/n), tau² = variance inter-titres, sigma² = variance intra-titre, estimées par la méthode des
  moments). Un titre à 4 événements vaut presque son secteur ; un titre à 40 vaut presque lui-même.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

LEVELS = ((75, "bon"), (55, "moyen"), (35, "faible"), (-1, "insuffisant"))


def level_of(score: float) -> str:
    return next(label for floor, label in LEVELS if score >= floor)


def reliability(values=None, n: int | None = None, day0=None, min_events: int = 8, now=None) -> dict:
    """`values` : observations de la statistique (écart-type relatif) ; `day0` : dates des événements (ancienneté médiane)."""
    x = np.asarray(values, dtype=float) if values is not None else np.array([])
    x = x[np.isfinite(x)]
    n = len(x) if n is None else int(n)
    s_n = 1 - math.exp(-n / 25.0)
    se_rel = 1.0
    if len(x) >= 3 and np.mean(np.abs(x)) > 0:
        se_rel = float(np.std(x, ddof=1) / math.sqrt(len(x)) / abs(np.mean(x)) if abs(np.mean(x)) > 1e-12 else 1.0)
    s_disp = math.exp(-min(se_rel, 5.0))
    age = np.nan
    if day0 is not None and len(day0):
        ref = pd.Timestamp(now) if now is not None else pd.Timestamp.today()
        age = float(np.median((ref - pd.to_datetime(pd.Series(day0))).dt.days) / 365.25)
    s_age = math.exp(-age / 8.0) if np.isfinite(age) else 0.7
    score = 100 * (0.5 * s_n + 0.3 * s_disp + 0.2 * s_age)
    level = "insuffisant" if n < min_events else level_of(score)
    return {"score": round(score, 1), "level": level, "n": n, "se_rel": round(se_rel, 3),
            "age_years": None if not np.isfinite(age) else round(age, 1)}


def partial_pooling(values_by_group: dict[str, np.ndarray], prior_of: dict[str, str]) -> dict[str, dict]:
    """Moyenne de chaque groupe (titre) ramenée vers la moyenne de son groupe parent (secteur).

    `prior_of[g]` = clé du parent ; un groupe sans parent connu est ramené vers la moyenne générale. Renvoie, par groupe :
    brut, n, rétréci, poids du titre, moyenne du parent."""
    clean = {g: np.asarray(v, dtype=float)[np.isfinite(np.asarray(v, dtype=float))] for g, v in values_by_group.items()}
    clean = {g: v for g, v in clean.items() if len(v) >= 1}
    if not clean:
        return {}
    all_vals = np.concatenate(list(clean.values()))
    grand = float(all_vals.mean())
    within = [np.var(v, ddof=1) for v in clean.values() if len(v) >= 2]
    sigma2 = float(np.mean(within)) if within else float(np.var(all_vals))
    means = np.array([v.mean() for v in clean.values()])
    ns = np.array([len(v) for v in clean.values()])
    tau2 = max(float(np.var(means, ddof=1) - np.mean(sigma2 / ns)), 0.0) if len(means) >= 2 else 0.0
    parent_vals: dict[str, list[float]] = {}
    for g, v in clean.items():
        parent_vals.setdefault(prior_of.get(g, ""), []).extend(v.tolist())
    out = {}
    for g, v in clean.items():
        parent = prior_of.get(g, "")
        pv = np.array(parent_vals.get(parent, []))
        mu0 = float(pv.mean()) if len(pv) >= 5 else grand
        w = tau2 / (tau2 + sigma2 / len(v)) if (tau2 + sigma2 / len(v)) > 0 else 0.0
        out[g] = {"raw": float(v.mean()), "n": len(v), "weight": round(w, 3), "shrunk": float(w * v.mean() + (1 - w) * mu0),
                  "prior": mu0, "parent": parent}
    return out
