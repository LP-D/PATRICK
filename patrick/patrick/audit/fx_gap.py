"""Écart holdout / réel des cibles de change, par règle d'alignement des séances (ADR 0007).

Le 28/10, les runs de change à 1 jour visaient 68,8 % de bonnes directions au holdout et 57,6 % en réel : la règle 1 (barres du
début de journée) laissait les variables du jour recouvrir le label. La règle 2 la remplace pour tout run neuf. Ce module mesure,
pour chaque règle, l'exactitude directionnelle du meilleur essai de chaque run terminé au holdout et en réel : si la règle 2 a réglé
le problème, son écart doit être du même ordre que celui des autres classes d'actifs, pas de 15 points.

Mesure seulement (lecture). Le réel ne juge un signal qu'une fois son horizon écoulé : il faut du temps avant qu'un run de la règle 2
ait assez de jugements (`min_live`). `patrick audit fx-gap` l'affiche ; à relancer de temps en temps.
"""
from __future__ import annotations

import json
import sqlite3

from patrick.data.session_calendar import is_yahoo_fx_pair


def _rule(config_json: str | None) -> int | None:
    try:
        objective = json.loads(config_json or "{}").get("objective") or {}
    except ValueError:
        return None
    rule = objective.get("session_rule", 1)
    return rule if isinstance(rule, int) and not isinstance(rule, bool) else None


def fx_gap(conn: sqlite3.Connection, horizon: int = 1, min_live: int = 20) -> dict:
    """Par règle (1, 2) : nombre de runs retenus (au moins `min_live` jugements réels), exactitude directionnelle pondérée au holdout et
    en réel, effectifs, écart en points, et nombre de runs encore trop jeunes."""
    rows = conn.execute(
        "SELECT r.run_id, r.target, r.config_json, t.trial_id FROM run r JOIN trial t ON t.run_id = r.run_id AND t.is_best = 1 "
        "WHERE r.status = 'done' AND r.horizon = ?", (horizon,)).fetchall()
    rules: dict[int, dict] = {}
    for _run_id, target, config_json, trial_id in rows:
        symbol = str(target).split("__", 1)[0]
        if not is_yahoo_fx_pair(symbol):
            continue
        rule = _rule(config_json)
        if rule is None:
            continue
        acc = rules.setdefault(rule, {"runs": 0, "too_young": 0, "holdout_hits": 0.0, "holdout_n": 0, "live_hits": 0.0, "live_n": 0})
        h_hits, h_n = conn.execute(
            "SELECT COALESCE(SUM(CASE WHEN (y_pred >= 2) = (y_true >= 2) THEN 1 ELSE 0 END), 0), COUNT(*) FROM prediction "
            "WHERE trial_id = ? AND split = 'holdout' AND y_true IS NOT NULL AND y_pred IS NOT NULL", (trial_id,)).fetchone()
        l_hits, l_n = conn.execute(
            "SELECT COALESCE(SUM(CASE WHEN (y_pred >= 2) = (y_true > 0.5) THEN 1 ELSE 0 END), 0), COUNT(*) FROM prediction "
            "WHERE trial_id = ? AND split = 'live' AND y_true IS NOT NULL AND y_pred IS NOT NULL", (trial_id,)).fetchone()
        if not h_n:
            continue
        if l_n < min_live:
            acc["too_young"] += 1
            continue
        acc["runs"] += 1
        acc["holdout_hits"] += h_hits
        acc["holdout_n"] += h_n
        acc["live_hits"] += l_hits
        acc["live_n"] += l_n
    out = {}
    for rule, acc in sorted(rules.items()):
        holdout = acc["holdout_hits"] / acc["holdout_n"] if acc["holdout_n"] else None
        live = acc["live_hits"] / acc["live_n"] if acc["live_n"] else None
        out[rule] = {"runs": acc["runs"], "too_young": acc["too_young"], "holdout_acc": holdout, "live_acc": live,
                     "holdout_n": acc["holdout_n"], "live_n": acc["live_n"],
                     "gap_points": (holdout - live) * 100 if holdout is not None and live is not None else None}
    return {"horizon": horizon, "min_live": min_live, "rules": out}
