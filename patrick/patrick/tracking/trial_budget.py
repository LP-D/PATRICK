"""Budget d'essais d'un lancement (ADR 0010) : avant de lancer, ce que le run prévu ajoute au nombre d'essais déjà comptés pour la cible
(`trial_registry`) et ce que cela fait au Sharpe déflaté.

Le Sharpe déflaté corrige un Sharpe observé du nombre de configurations parmi lesquelles il a été choisi. Sous H0 (aucune compétence), le meilleur
de N Sharpe est en moyenne `sigma x E[max]` ; `E[max]` est calculé ici avec `validation.dsr.expected_max_sharpe(N, 1)` : le seuil, exprimé en
écarts-types d'un Sharpe, que le meilleur essai doit dépasser pour ne pas s'expliquer par le seul fait d'avoir essayé N configurations.
"""
from __future__ import annotations

import sqlite3

from patrick.config.schema import RunConfig
from patrick.tracking import stats as trackstats
from patrick.validation.dsr import expected_max_sharpe


def planned_trials_per_horizon(config: RunConfig) -> dict[str, int]:
    """Configurations qu'un run ajoutera au registre, PAR horizon : la grille du scan (régimes x nombre de variables x échantillonneur x
    algorithme, « Stacking » compris) et, si le réglage est actif, les essais d'Optuna (`n_trials` pour chacun des `top_k` meilleurs)."""
    algos = len(config.models.algos) + (1 if config.models.stacking else 0)
    scan = (len(config.objective.regimes) * len(config.selection.n_features_grid)
            * len(config.sampler.candidates) * algos)
    optuna = config.tuning.n_trials * config.tuning.top_k if config.tuning.enabled else 0
    return {"scan": scan, "optuna": optuna, "total": scan + optuna}


def threshold(n_trials: int) -> float:
    """Seuil de Sharpe (en écarts-types) sous H0 pour le meilleur de `n_trials` essais."""
    return round(expected_max_sharpe(max(int(n_trials), 0), 1.0), 3)


def trial_budget(conn: sqlite3.Connection, config: RunConfig) -> dict:
    """Pour chaque horizon du lancement : essais déjà comptés pour la cible, essais ajoutés, essais après le run, et le seuil de Sharpe
    sous H0 avant / après. `delta_threshold` > 0 : le même Sharpe observé vaudra moins après ce run."""
    label = config.objective.run_label()
    planned = planned_trials_per_horizon(config)
    horizons = []
    for horizon in config.objective.horizons:
        existing = trackstats.count_registered_trials(conn, label, horizon)
        after = existing + planned["total"]
        before_thr, after_thr = threshold(existing), threshold(after)
        horizons.append({"horizon": horizon, "existing": existing, "added": planned["total"], "after": after,
                         "threshold_before": before_thr, "threshold_after": after_thr,
                         "delta_threshold": round(after_thr - before_thr, 3),
                         "growth": round(planned["total"] / existing, 2) if existing else None})
    return {"target": label, "planned": planned, "horizons": horizons,
            "total_existing": trackstats.count_registered_trials(conn, label)}


def describe(budget: dict) -> list[str]:
    """Lignes lisibles du budget (terminal, journal)."""
    p = budget["planned"]
    head = (f"{budget['target']} : {p['total']} essais ajoutés par horizon ({p['scan']} de grille + {p['optuna']} d'Optuna) ; "
            f"{budget['total_existing']} déjà comptés pour la cible, tous horizons confondus.")
    lines = [head]
    for h in budget["horizons"]:
        lines.append(f"  h={h['horizon']}j : {h['existing']} -> {h['after']} essais ; seuil de Sharpe sous H0 "
                     f"{h['threshold_before']:.2f} -> {h['threshold_after']:.2f} écarts-types (+{h['delta_threshold']:.2f})")
    return lines
