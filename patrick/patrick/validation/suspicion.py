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


ALIGNMENT_LABEL = "alignement des devises"


def alignment_reason(target: str | None, config: dict | None) -> str | None:
    """Motif si ce run est une cible de change `=X` entraînée avant la règle d'alignement 2 (ADR 0007) : ses variables du jour
    (or, S&P 500...) recouvraient le label, donc son exactitude est un « nowcast » non négociable, quel que soit son score.
    Le run reste lisible (rien n'est supprimé) mais n'est ni champion crédible ni candidat du fonds."""
    from patrick.config.target_label import split_run_label
    from patrick.data.session_calendar import is_yahoo_fx_pair

    if not isinstance(target, str) or not is_yahoo_fx_pair(split_run_label(target)[0]):
        return None
    objective = (config or {}).get("objective") if isinstance(config, dict) else None
    rule = objective.get("session_rule", 1) if isinstance(objective, dict) else 1
    if isinstance(rule, int) and rule >= 2:
        return None
    return f"{ALIGNMENT_LABEL} : barres de change du début de journée (règle 1)"


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
