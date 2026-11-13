"""Tableau de bord du résultat réel des champions (page `/reel`).

Tout part des prédictions quotidiennes (`split='live'`) des champions en titre :
- jugées (horizon écoulé) : part de bonnes directions par semaine, classe d'actifs, horizon et algorithme, toujours à côté de la
  stratégie naïve « toujours hausse » (la part de hausses réalisées) : un modèle qui fait 52 % quand 59 % des mouvements montent
  n'apporte rien ;
- biais de direction : part de hausses annoncées contre part de hausses réalisées, et ce qu'aurait donné un seuil de décision recalé
  sur le passé (MESURE SEULE : aucun signal n'est modifié) ;
- avis d'ensemble : le dernier signal de chaque horizon d'une même cible, réunis en un avis.

Rappel : sur une ligne `live`, `y_true` est binaire (1 = hausse) ; `y_pred` est l'indice de classe (2 et 3 = hausse).
Lecture seule.
"""
from __future__ import annotations

import datetime as dt
import math
import sqlite3
from collections import defaultdict

from patrick.clock import utc_today
from patrick.config import defaults as D
from patrick.config.target_label import split_run_label
from patrick.data.session_calendar import classify_asset_class

_CHUNK = 500
MIN_GROUP = 30               # jugements en dessous desquels une ligne de tableau n'est pas affichée
MIN_PAST = 200               # jugements passés d'une classe avant de recaler son seuil
CONSENSUS_DAYS = 10          # un signal plus vieux n'entre pas dans l'avis d'ensemble
Z95 = 1.96


def wilson(hits: int, n: int) -> tuple[float, float] | None:
    """Intervalle de Wilson à 95 % d'une proportion (les horizons qui se recouvrent le rendent optimiste : à lire comme un minimum)."""
    if n <= 0:
        return None
    p, z2 = hits / n, Z95 * Z95
    centre = (p + z2 / (2 * n)) / (1 + z2 / n)
    half = Z95 * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / (1 + z2 / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def _asset_class(symbol: str) -> str:
    """Classe d'actifs d'une cible ; une série FRED (PIB, taux directeur…) est « macro », jamais une action américaine par défaut."""
    fred = {sym for sym, _, src in D.DEFAULT_TARGET_CHOICES if src == "fred"}
    return classify_asset_class(symbol, "fred" if symbol in fred else "yfinance")


def _champions(conn: sqlite3.Connection) -> dict[int, dict]:
    out = {}
    for target, horizon, trial_id, algo in conn.execute(
            "SELECT champion.target, champion.horizon, champion.trial_id, trial.algo FROM champion "
            "LEFT JOIN trial ON trial.trial_id = champion.trial_id"):
        symbol = split_run_label(target)[0]
        out[int(trial_id)] = {"target": target, "symbol": symbol, "horizon": int(horizon), "algo": algo or "?",
                              "asset_class": _asset_class(symbol)}
    return out


def _rows(conn: sqlite3.Connection, trial_ids: list[int], where: str, params: tuple = ()) -> list[tuple]:
    out: list[tuple] = []
    ids = sorted(trial_ids)
    for start in range(0, len(ids), _CHUNK):
        chunk = ids[start:start + _CHUNK]
        # INDEXED BY : sans lui SQLite part de l'index sur `split` et parcourt toutes les lignes `live` de la base
        out += conn.execute(
            "SELECT trial_id, ts, y_pred, y_true, p_up FROM prediction INDEXED BY sqlite_autoindex_prediction_1 "
            f"WHERE trial_id IN ({','.join('?' for _ in chunk)}) AND split = 'live' AND {where}", (*chunk, *params)).fetchall()
    return out


def _stat(n: int, hits: int, ups: int, pred_ups: int) -> dict:
    ci = wilson(hits, n)
    return {"n": n, "hits": hits, "rate": hits / n if n else None, "ci_low": ci[0] if ci else None, "ci_high": ci[1] if ci else None,
            "up_rate": ups / n if n else None, "pred_up_rate": pred_ups / n if n else None,
            # ce que le modèle ajoute à « toujours hausse » ou « toujours baisse », la meilleure des deux
            "edge": (hits / n - max(ups / n, 1 - ups / n)) if n else None}


def _group(judged: list[dict], key) -> list[dict]:
    acc: dict = defaultdict(lambda: [0, 0, 0, 0])
    for row in judged:
        a = acc[key(row)]
        a[0] += 1
        a[1] += row["hit"]
        a[2] += row["up"]
        a[3] += row["pred_up"]
    return [{"key": k, **_stat(*v)} for k, v in acc.items()]


def _week(ts: str) -> str:
    day = dt.date.fromisoformat(str(ts)[:10])
    return (day - dt.timedelta(days=day.weekday())).isoformat()          # lundi de la semaine


def _bias_shadow(judged: list[dict]) -> dict | None:
    """Seuil de décision recalé, par classe d'actifs et de façon causale : chaque semaine, le seuil sur P(hausse) est celui qui, sur les
    semaines PASSÉES de la classe, aurait annoncé autant de hausses qu'il s'en est produit. Compare les bonnes directions avec ce seuil et
    avec le seuil d'origine, sur les mêmes lignes. Mesure seule."""
    rows = [r for r in judged if r["p_up"] is not None]
    by_class: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        by_class[row["asset_class"]][row["week"]].append(row)
    n = base_hits = shadow_hits = 0
    for weeks in by_class.values():
        past: list[dict] = []
        for week in sorted(weeks):
            current = weeks[week]
            if len(past) >= MIN_PAST:
                share = sum(r["up"] for r in past) / len(past)
                scores = sorted(r["p_up"] for r in past)
                threshold = scores[min(len(scores) - 1, max(0, round((1 - share) * len(scores))))]
                for row in current:
                    n += 1
                    base_hits += row["hit"]
                    shadow_hits += int((row["p_up"] >= threshold) == bool(row["up"]))
            past += current
    if not n:
        return None
    return {"n": n, "rate": base_hits / n, "shadow_rate": shadow_hits / n, "gain": (shadow_hits - base_hits) / n}


def _consensus(conn: sqlite3.Connection, champions: dict[int, dict], today: dt.date) -> list[dict]:
    """Un avis par cible : moyenne de la P(hausse) du dernier signal de chaque horizon (à défaut, la part d'horizons haussiers)."""
    cutoff = (today - dt.timedelta(days=CONSENSUS_DAYS)).isoformat()
    latest: dict[int, tuple] = {}
    for trial_id, ts, y_pred, _y_true, p_up in _rows(conn, list(champions), "ts >= ?", (cutoff,)):
        if trial_id not in latest or str(ts) > str(latest[trial_id][0]):
            latest[trial_id] = (ts, y_pred, p_up)
    by_target: dict[str, list[tuple]] = defaultdict(list)
    for trial_id, (ts, y_pred, p_up) in latest.items():
        by_target[champions[trial_id]["target"]].append((champions[trial_id]["horizon"], ts, y_pred, p_up))
    out = []
    for target, signals in by_target.items():
        if len(signals) < 2:
            continue                                         # un seul horizon : pas un avis d'ensemble
        ups = sum(1 for _, _, y_pred, _ in signals if round(y_pred) >= 2)
        scores = [p for *_, p in signals if p is not None]
        score = sum(scores) / len(scores) if scores else ups / len(signals)
        asset_class = _asset_class(split_run_label(target)[0])
        if asset_class == "macro":
            continue                                         # une série macro ne se négocie pas : pas d'avis
        out.append({"target": target, "asset_class": asset_class, "n_horizons": len(signals), "n_up": ups,
                    "score": score, "direction": "UP" if score >= 0.5 else "DOWN",
                    "agreement": max(ups, len(signals) - ups) / len(signals),
                    "horizons": sorted(h for h, *_ in signals), "last": max(str(ts)[:10] for _, ts, *_ in signals)})
    out.sort(key=lambda c: (-abs(c["score"] - 0.5), c["target"]))
    return out


def board(conn: sqlite3.Connection, today: dt.date | None = None) -> dict:
    """Tout ce que la page `/reel` affiche. `judged` : effectif total ; chaque tableau ne garde que les lignes d'au moins `MIN_GROUP`
    jugements (les semaines sont toutes gardées)."""
    today = today or utc_today()
    champions = _champions(conn)
    judged = []
    for trial_id, ts, y_pred, y_true, p_up in _rows(conn, list(champions), "y_true IS NOT NULL"):
        meta = champions[trial_id]
        up, pred_up = int(float(y_true) >= 0.5), int(round(y_pred) >= 2)
        judged.append({**meta, "week": _week(ts), "up": up, "pred_up": pred_up, "hit": int(up == pred_up), "p_up": p_up})

    def table(key, keep_all: bool = False) -> list[dict]:
        rows = [r for r in _group(judged, key) if keep_all or r["n"] >= MIN_GROUP]
        return sorted(rows, key=lambda r: str(r["key"]) if keep_all else -r["n"])

    total = _group(judged, lambda r: "all")
    return {"n_champions": len(champions), "n_models_judged": len({(r["target"], r["horizon"]) for r in judged}),
            "total": total[0] if total else _stat(0, 0, 0, 0),
            "by_week": table(lambda r: r["week"], keep_all=True), "by_class": table(lambda r: r["asset_class"]),
            "by_horizon": sorted(table(lambda r: r["horizon"]), key=lambda r: r["key"]), "by_algo": table(lambda r: r["algo"]),
            "bias": _bias_shadow(judged), "consensus": _consensus(conn, champions, today)}
