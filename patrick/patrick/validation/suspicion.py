"""Résultats « trop beaux pour être vrais ».

Sur 4 085 essais évalués sur holdout, le meilleur score honnête observé en direction est un F1_dir de 0,54 ; douze
essais dépassaient 0,85 (jusqu'à 1,00) et tous venaient d'une fuite temporelle (cibles FRED SP500, VIXCLS, DGS2..DGS30,
EURUSD=X : `data/alignment.py`). Aucun marché liquide ne se prédit à ce niveau : un score au-delà de ces seuils est
traité comme une anomalie de données, jamais comme une performance.

Effets (le correctif de fond est `data/alignment.py` ; ceci est le filet) :
- le champion d'une cible ne peut pas être un modèle suspect, et un champion suspect est remplacé par tout challenger
  sain (`pipeline/champion_duel.py`) ;
- l'interface affiche un bandeau « résultat suspect » sur ces runs et ces prédictions (`tracking/history.py`).
"""
from __future__ import annotations

import math

SUSPECT_F1_DIR = 0.80
SUSPECT_AUC = 0.85

LABEL = "suspect"


def _finite(value) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def f1_suspect(f1_dir) -> bool:
    v = _finite(f1_dir)
    return v is not None and v >= SUSPECT_F1_DIR


def suspect_reason(metrics: dict | None) -> str | None:
    """Motif lisible si `metrics` (F1_dir, AUC_ovr_4cls, Acc_dir...) dépasse un seuil de plausibilité, sinon None."""
    if not metrics:
        return None
    f1 = _finite(metrics.get("F1_dir"))
    if f1 is not None and f1 >= SUSPECT_F1_DIR:
        return f"F1_dir {f1:.2f} ≥ {SUSPECT_F1_DIR:.2f}"
    auc = _finite(metrics.get("AUC_ovr_4cls"))
    if auc is not None and auc >= SUSPECT_AUC:
        return f"AUC {auc:.2f} ≥ {SUSPECT_AUC:.2f}"
    return None
