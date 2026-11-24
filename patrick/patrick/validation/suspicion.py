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
NON_TARGET_SOURCES = ("fred",)          # `config/defaults.py::NON_TARGET_SOURCES` (copie : ce module reste sans dépendance)
MACRO_TARGET_REASON = ("cible macro (FRED) retirée : des séries dérivées du même taux recouvraient le label (fuite d'alignement), "
                       "score non crédible")
# Cible d'Asie-Pacifique entraînée avant l'alignement version 2 (ADR 0007, 2026-10-28), en mode FRED « du jour » : la valeur FRED
# quotidienne datée d (VIX de clôture, écarts de crédit) se fixe à New York vers 20 h UTC, douze heures APRÈS la clôture de Tokyo,
# Séoul ou Bombay, et annonçait leur séance suivante. Mesuré le 2026-11-21 sur les tables brutes : corrélation de rang du VIX FRED du
# jour avec le rendement du lendemain -0,195 (^N225), -0,146 (^KS11), -0,162 (^NSEI), environ 0 une fois retardé d'un jour ; AUC de
# direction médiane des runs ML d'Asie à 1 jour 0,650 avant la version 2, 0,529 après ; Sharpe brut des agents RL divisé par 3 à 20
# quand leurs positions sont décalées d'un jour. L'Europe (clôture 16 h 30 UTC) reste sous le seuil d'audit (-0,04 à -0,08) et
# n'est pas marquée.
FRED_DAY_LABEL = "séries FRED du jour"
FRED_DAY_MODES = ("alfred", "reference_date")       # modes où une valeur quotidienne est datée de son jour de référence
FRED_DAY_CLASSES = ("equities_asia_pacific",)
FRED_DAY_REASON = (f"{FRED_DAY_LABEL} : cible d'Asie entraînée avant l'alignement version 2 (28/10), le VIX et les écarts de crédit FRED "
                   "du jour, clos à New York après elle, annonçaient sa séance suivante ; score non crédible")


def fred_day_reason(symbol: str | None, config: dict | None) -> str | None:
    """`FRED_DAY_REASON` si `symbol` (sans suffixe de type) est une cible d'Asie-Pacifique entraînée avant l'alignement version 2 avec au
    moins une série FRED quotidienne datée de son jour de référence (voir le commentaire de `FRED_DAY_REASON`), sinon None."""
    from patrick.data.session_calendar import classify_asset_class

    if not isinstance(symbol, str) or not isinstance(config, dict):
        return None
    objective = config.get("objective") if isinstance(config.get("objective"), dict) else {}
    universe = config.get("universe") if isinstance(config.get("universe"), dict) else {}
    source = objective.get("target_source") or "yfinance"
    if source != "yfinance" or classify_asset_class(symbol, source) not in FRED_DAY_CLASSES:
        return None
    alignment = objective.get("alignment")
    version = alignment.get("version", 0) if isinstance(alignment, dict) else 0
    if isinstance(version, int) and not isinstance(version, bool) and version >= 2:
        return None
    if universe.get("fred_point_in_time") not in FRED_DAY_MODES:
        return None
    series = universe.get("fred_series")
    if not isinstance(series, dict) or not series:
        return None
    from patrick.data.freshness import fred_periodicity
    return FRED_DAY_REASON if any(fred_periodicity(code) == "daily" for code in series.values() if isinstance(code, str)) else None


def alignment_reason(target: str | None, config: dict | None) -> str | None:
    """Motif si ce run est une cible de change `=X` entraînée avant la règle d'alignement 2 (ADR 0007) : ses variables du jour
    (or, S&P 500...) recouvraient le label, donc son exactitude est un « nowcast » non négociable, quel que soit son score.
    Même sort pour un run dont la cible est une série macro (FRED) : retirées des cibles le 2026-10-31 (AUC 0,95 à 1,00 sur des taux et le
    S&P 500, fuite par des séries dérivées du même taux) ; et pour une cible d'Asie-Pacifique d'avant l'alignement version 2 qui voyait les
    séries FRED du jour (`fred_day_reason`). Le run reste lisible (rien n'est supprimé) mais n'est ni champion crédible ni candidat du
    fonds, et sort des moyennes."""
    from patrick.config.target_label import split_run_label
    from patrick.data.session_calendar import is_yahoo_fx_pair

    objective = (config or {}).get("objective") if isinstance(config, dict) else None
    if isinstance(objective, dict) and objective.get("target_source") in NON_TARGET_SOURCES:
        return MACRO_TARGET_REASON
    if not isinstance(target, str):
        return None
    symbol = split_run_label(target)[0]
    if not is_yahoo_fx_pair(symbol):
        return fred_day_reason(symbol, config)
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
    # L'AUC de direction est le critère de sélection depuis l'ADR 0013 : une fuite qui classe sans trancher la dépasse avant le F1.
    auc_dir = _finite(metrics.get("AUC_dir"))
    if auc_dir is not None and auc_dir >= SUSPECT_AUC:
        return f"AUC_dir {auc_dir:.2f} ≥ {SUSPECT_AUC:.2f}"
    return None
