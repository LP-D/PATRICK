"""Avantage prédictif réel des signaux live, par horizon puis par classe d'actifs (page `/predictions`, vue « Par horizon »).

Question posée : « les prédictions live battent-elles le hasard, et si oui pour quelle classe d'actifs à quel horizon ? ».
Un taux de réussite brut ne répond pas, pour quatre raisons que ce module traite :

1. **Seules les vraies prédictions live comptent.** Les barres reconstituées (`prediction.live_backfill = 1`) sont recalculées
   après coup avec un modèle qui connaît déjà ces jours : les compter reviendrait à juger le modèle sur ce qu'il a vu.
2. **Un même jour, les actifs d'une classe bougent ensemble** (toutes les actions US chutent le même jour) : 40 actions qui se
   trompent le même jour ne sont pas 40 erreurs indépendantes. Les réussites sont donc d'abord moyennées *par date*, et la
   précision est testée sur ces moyennes quotidiennes.
3. **Les horizons se recouvrent.** Deux signaux à 10 séances d'écart partagent 9 séances de marché : le nombre d'observations
   indépendantes vaut environ `jours distincts / horizon`, pas le nombre de lignes (`n_eff`).
4. **Battre 50 % ne suffit pas** quand le marché monte : « toujours hausse » gagne alors plus d'une fois sur deux sans rien prédire.
   L'avantage doit aussi dépasser la meilleure règle naïve, `max(part de hausses, part de baisses)` réalisée sur les mêmes lignes.

Le test est un t de Student unilatéral sur les moyennes quotidiennes, avec `n_eff` degrés de liberté (conservateur). Les
cellules classe × horizon mesurables sont corrigées ensemble par Benjamini-Hochberg (`validation/fdr.py`), comme les cibles du
reste du produit : on teste plusieurs dizaines de cellules, quelques-unes passeraient seules au hasard.
"""
from __future__ import annotations

import math
import sqlite3
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from patrick.validation.fdr import benjamini_hochberg

MIN_EFFECTIVE = 12.0         # en dessous : trop peu d'observations indépendantes pour conclure (≈ 2,5 semaines de signaux quotidiens)
FDR_ALPHA = 0.10             # seuil Benjamini-Hochberg sur les cellules classe x horizon (celui des cibles, ADR 0006)
RAW_ALPHA = 0.05             # seuil brut du verdict « à confirmer »
SD_FLOOR = 0.05              # plancher de l'écart-type des moyennes quotidiennes (évite un t infini quand tout est juste)
ALL_KEY = "all"

# Verdicts d'une cellule (clés i18n `edge_v_<verdict>`).
EDGE, LEAN, NONE, BELOW, EARLY = "edge", "lean", "none", "below", "early"


def fetch_judged(conn: sqlite3.Connection, targets: list[str], horizons: list[int],
                 include_backfill: bool = False) -> tuple[list[tuple], int]:
    """Les signaux live déjà jugés des modèles gagnants : `([(cible, horizon, jour, hausse_prédite, hausse_réelle)], n_reconstituées_écartées)`.

    Même résolution run -> trial gagnant et même lecture à plat que `history.live_hit_rate_by_target_and_horizon` (aucune fenêtre SQL
    sur la table `prediction`, 24 millions de lignes). Une ligne par (cible, horizon, jour) : si deux modèles ont écrit le même jour,
    le plus récent (plus grand `trial_id`) gagne, pour ne pas compter deux fois le même signal. Une ligne dont la classe réalisée
    contredit le sens réalisé (rendement nul) est écartée, comme dans `history.live_class_tally_by_target_and_horizon`."""
    if not targets or not horizons:
        return [], 0
    tp = ",".join("?" for _ in targets)
    hp = ",".join("?" for _ in horizons)
    resolved = conn.execute(
        "SELECT DISTINCT run.target, run.horizon, trial.trial_id "
        "FROM run JOIN trial ON trial.run_id = run.run_id AND trial.is_best = 1 "
        f"WHERE run.target IN ({tp}) AND run.horizon IN ({hp})", tuple(targets) + tuple(horizons)).fetchall()
    if not resolved:
        return [], 0
    key_of_trial = {trial_id: (target, horizon) for target, horizon, trial_id in resolved}
    placeholders = ",".join("?" for _ in key_of_trial)
    rows = conn.execute(
        "SELECT trial_id, ts, y_true, y_pred, y_class, COALESCE(live_backfill, 0) FROM prediction "
        "INDEXED BY sqlite_autoindex_prediction_1 "
        f"WHERE trial_id IN ({placeholders}) AND split = 'live' AND y_true IS NOT NULL", tuple(key_of_trial)).fetchall()
    latest: dict[tuple, tuple] = {}
    excluded = 0
    for trial_id, ts, y_true, y_pred, y_class, backfill in rows:
        if backfill and not include_backfill:
            excluded += 1
            continue
        if y_class is not None and (int(y_class) >= 2) != bool(y_true):
            continue
        target, horizon = key_of_trial[trial_id]
        key = (target, horizon, str(ts)[:10])
        if key not in latest or trial_id > latest[key][0]:
            latest[key] = (trial_id, round(y_pred) >= 2, bool(y_true))
    return [(t, h, d, pu, ru) for (t, h, d), (_tid, pu, ru) in latest.items()], excluded


def _wilson(hits: float, n: float, z: float = 1.96) -> tuple[float, float]:
    """Intervalle de Wilson à 95 % d'une proportion (`n` effectif, éventuellement non entier)."""
    if n <= 0:
        return 0.0, 1.0
    p = hits / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def _t_sf(t_stat: float, df: float) -> float:
    from scipy import (
        stats,  # chargé à la demande : scipy coûte à l'import (démarrage de l'application)
    )
    return float(stats.t.sf(t_stat, df))


def edge_stats(obs: Iterable[tuple[str, bool, bool]], horizon: int) -> dict[str, Any]:
    """Précision directionnelle d'un ensemble de signaux jugés. `obs` : `(jour, hausse_prédite, hausse_réelle)` ; plusieurs actifs
    le même jour sont permis (ils sont moyennés par jour avant le test).

    Retourne `n` (lignes), `days`, `n_eff` (`jours / horizon`), `hit_rate`, `ci` (Wilson sur `n_eff`), `up_share` (part de hausses
    réalisées), `naive` (précision de la meilleure règle constante), `edge` (précision - 50 %), `edge_naive` (précision - naïf),
    `p_value` (unilatérale « mieux que le hasard ») et `p_below` (unilatérale « pire que le hasard »), ces deux-là `None` si
    `n_eff` < 2. Un ensemble vide donne `n = 0`."""
    per_day: dict[str, list[int]] = defaultdict(list)
    ups = n = 0
    for day, predicted_up, real_up in obs:
        per_day[day].append(int(predicted_up == real_up))
        ups += int(real_up)
        n += 1
    if n == 0:
        return {"n": 0, "days": 0, "n_eff": 0.0, "hit_rate": None, "ci": None, "up_share": None, "naive": None,
                "edge": None, "edge_naive": None, "p_value": None, "p_below": None, "horizon": horizon}
    daily = [sum(v) / len(v) for v in per_day.values()]
    days = len(daily)
    hit_rate = sum(sum(v) for v in per_day.values()) / n
    up_share = ups / n
    naive = max(up_share, 1 - up_share)
    n_eff = max(1.0, days / max(1, horizon))
    p_value = p_below = None
    if n_eff >= 2 and days >= 2:
        mean = sum(daily) / days
        sd = math.sqrt(sum((d - mean) ** 2 for d in daily) / (days - 1))
        t_stat = (mean - 0.5) / (max(sd, SD_FLOOR) / math.sqrt(n_eff))
        df = max(1.0, n_eff - 1)
        p_value = _t_sf(t_stat, df)
        p_below = _t_sf(-t_stat, df)
    ci = _wilson(hit_rate * n_eff, n_eff)
    return {"n": n, "days": days, "n_eff": round(n_eff, 1), "hit_rate": hit_rate, "ci": ci, "up_share": up_share,
            "naive": naive, "edge": hit_rate - 0.5, "edge_naive": hit_rate - naive, "p_value": p_value, "p_below": p_below,
            "horizon": horizon}


def verdicts(cells: dict[Any, dict]) -> dict[Any, str]:
    """Le verdict de chaque cellule (`{clé: edge_stats}`), la correction de Benjamini-Hochberg s'appliquant à l'ensemble des
    cellules mesurables (`n_eff >= MIN_EFFECTIVE`) passées ensemble.

    - `early` : moins de `MIN_EFFECTIVE` observations indépendantes, aucune conclusion possible ;
    - `edge` : mieux que le hasard (q <= 10 %), au-dessus de 50 % ET de la meilleure règle naïve ;
    - `lean` : p brute <= 5 % mais la correction ou la règle naïve ne confirme pas : à confirmer avec plus de données ;
    - `below` : significativement PIRE que le hasard (p brute <= 5 %) ;
    - `none` : aucun écart distinguable du hasard."""
    measurable = {k: s["p_value"] for k, s in cells.items()
                  if s["n"] and s["p_value"] is not None and s["n_eff"] >= MIN_EFFECTIVE}
    q = {k: v["adjusted_p_value"] for k, v in benjamini_hochberg({str(k): p for k, p in measurable.items()},
                                                                  alpha=FDR_ALPHA)["results"].items()}
    out: dict[Any, str] = {}
    for key, s in cells.items():
        if not s["n"] or s["p_value"] is None or s["n_eff"] < MIN_EFFECTIVE:
            out[key] = EARLY
        elif s["p_below"] is not None and s["p_below"] <= RAW_ALPHA:
            out[key] = BELOW
        elif q.get(str(key), 1.0) <= FDR_ALPHA and s["hit_rate"] > 0.5 and s["edge_naive"] > 0:
            out[key] = EDGE
        elif s["p_value"] <= RAW_ALPHA:
            out[key] = LEAN
        else:
            out[key] = NONE
    return out


def build(judged: list[tuple], class_of: dict[str, str], horizons: list[int]) -> dict[str, Any]:
    """Statistiques par classe x horizon (avec une ligne « toutes classes ») et par actif x horizon.

    `judged` : sortie de `fetch_judged` ; `class_of` : `{cible: clé de classe}` (une cible absente va dans `other`).
    Retourne `{"matrix": {classe: {horizon: stats + verdict}}, "assets": {(cible, horizon): stats}, "classes": [clés présentes],
    "n_judged": ..., "first_day": ..., "last_day": ...}`."""
    by_class: dict[tuple[str, int], list] = defaultdict(list)
    by_asset: dict[tuple[str, int], list] = defaultdict(list)
    days: list[str] = []
    for target, horizon, day, predicted_up, real_up in judged:
        obs = (day, predicted_up, real_up)
        by_class[(class_of.get(target, "other"), horizon)].append(obs)
        by_class[(ALL_KEY, horizon)].append(obs)
        by_asset[(target, horizon)].append(obs)
        days.append(day)
    cells = {key: edge_stats(obs, key[1]) for key, obs in by_class.items()}
    verdict = verdicts(cells)
    matrix: dict[str, dict[int, dict]] = {}
    for (cls, horizon), stats in cells.items():
        matrix.setdefault(cls, {})[horizon] = {**stats, "verdict": verdict[(cls, horizon)]}
    assets = {key: edge_stats(obs, key[1]) for key, obs in by_asset.items()}
    classes = [c for c in matrix if c != ALL_KEY]
    return {"matrix": matrix, "assets": assets, "classes": classes, "horizons": list(horizons), "n_judged": len(judged),
            "first_day": min(days) if days else None, "last_day": max(days) if days else None}
