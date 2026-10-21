"""Garde-fous transversaux : budget d'exploration consommé et significativité déflatée, registre des lectures du holdout.

Deux registres append-only existent déjà : `trial_registry` (chaque configuration évaluée, scan comme Optuna, runs supprimés compris) et
`holdout_access` (chaque lecture du holdout). Ce module les rassemble, sans rien écrire, et ajoute ce qu'ils ne disent pas seuls :

- **significativité déflatée** : le meilleur de N essais ressemble à un signal même sur du hasard pur. Pour chaque couple cible × horizon, la
  meilleure exactitude holdout observée est comparée à ce que N essais indépendants sans aucun signal donneraient de mieux (p déflatée de
  Šidák, `1 - (1 - p)^N`, effectif divisé par l'horizon car les fenêtres d'étiquettes se chevauchent). C'est une approximation volontairement
  sévère : elle ne sait pas que les essais sont corrélés, donc elle surestime le hasard ; un résultat qui y survit est solide, un résultat qui
  n'y survit pas n'est pas pour autant faux ;
- **lectures du holdout déduites** : le registre d'accès n'existe que depuis sa création ; avant, chaque run terminé avec un holdout l'a lu au
  moins une fois, et chaque duel de champions l'a lu pour choisir. Ces lectures déduites sont affichées à part, jamais mélangées aux lectures
  enregistrées.
"""
from __future__ import annotations

import math
import sqlite3
from datetime import UTC, datetime

from scipy import stats as sps

from patrick.analysis import stats_core as sc

DEFAULT_HOLDOUT_ROWS = 280
TOO_GOOD = 0.70            # exactitude holdout au-delà de laquelle on soupçonne d'abord une fuite (comme la lecture guidée)
SELECTING_PURPOSES = ("champion_duel_challenger", "champion_duel_champion")
LOG_LIMIT = 300


def deflated(acc: float | None, n_rows: int, horizon: int, n_trials: int) -> dict:
    """Exactitude observée contre ce qu'un tirage sans signal donnerait de mieux parmi `n_trials` essais.

    Renvoie l'effectif efficace, la p-value contre pile ou face, la p déflatée (Šidák), le meilleur résultat attendu sur du hasard pur et la
    marge (observé - attendu)."""
    n_eff = max(1, round(n_rows / max(1, horizon)))
    out = {"n_eff": n_eff, "p": None, "p_deflated": None, "null_best": None, "margin": None}
    if acc is None or n_trials < 1:
        return out
    k = round(acc * n_eff)
    p = sc.binom_p_greater(k, n_eff, 0.5)
    if p is None:
        return out
    out["p"] = p
    out["p_deflated"] = 1.0 if n_trials > 5000 and p > 1e-12 else float(1.0 - (1.0 - p) ** n_trials)
    z = float(sps.norm.ppf(1.0 - 1.0 / max(2, n_trials)))
    out["null_best"] = 0.5 + z * 0.5 / math.sqrt(n_eff)
    out["margin"] = acc - out["null_best"]
    return out


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[tuple]:
    return conn.execute(sql, params).fetchall()


def summary(conn: sqlite3.Connection) -> dict:
    """Tout ce que montre la page `/garde-fous` en un seul appel (une quinzaine de requêtes groupées, aucune par run)."""
    reg_src = {s: (int(n_rows), int(n)) for s, n_rows, n in _rows(conn, "SELECT source, COUNT(*), COALESCE(SUM(n_trials), 0) FROM trial_registry GROUP BY source")}
    reg_total = sum(n for _, n in reg_src.values())
    monthly: dict[str, dict[str, int]] = {}
    for ym, src, n in _rows(conn, "SELECT substr(recorded_at, 1, 7), source, SUM(n_trials) FROM trial_registry GROUP BY 1, 2 ORDER BY 1"):
        monthly.setdefault(ym, {})[src] = int(n)
    trials = {(t, h): int(n) for t, h, n in _rows(conn, "SELECT target, horizon, COALESCE(SUM(n_trials), 0) FROM trial_registry GROUP BY target, horizon")}
    runs = {(t, h): (int(n), int(c), s) for t, h, n, c, s in _rows(
        conn, "SELECT target, horizon, COUNT(*), COUNT(DISTINCT config_hash), MIN(started_at) FROM run WHERE status = 'done' GROUP BY target, horizon")}
    best = {(t, h): (a, nr) for t, h, a, nr in _rows(
        conn, "SELECT r.target, r.horizon, MAX(a.value), MAX(n.value) FROM run r JOIN trial t ON t.run_id = r.run_id AND t.is_best = 1 "
              "JOIN fold_metric a ON a.trial_id = t.trial_id AND a.split = 'holdout' AND a.metric = 'Acc_dir' "
              "LEFT JOIN fold_metric n ON n.trial_id = t.trial_id AND n.split = 'holdout' AND n.metric = 'n_test' "
              "WHERE r.status = 'done' GROUP BY r.target, r.horizon")}
    ho_runs = {(t, h): int(n) for t, h, n in _rows(
        conn, "SELECT r.target, r.horizon, COUNT(DISTINCT r.run_id) FROM run r JOIN trial t ON t.run_id = r.run_id AND t.is_best = 1 "
              "JOIN fold_metric f ON f.trial_id = t.trial_id AND f.split = 'holdout' AND f.metric = 'F1_dir' WHERE r.status = 'done' GROUP BY r.target, r.horizon")}
    duels = {(t, h): int(n) for t, h, n in _rows(conn, "SELECT target, horizon, COUNT(*) FROM model_archive WHERE duel_json IS NOT NULL GROUP BY target, horizon")}
    reads = {}
    for t, h, purpose, n, n_runs in _rows(conn, "SELECT target, horizon, purpose, COUNT(*), COUNT(DISTINCT run_id) FROM holdout_access GROUP BY target, horizon, purpose"):
        d = reads.setdefault((t, h), {"total": 0, "selecting": 0, "by_purpose": {}})
        d["total"] += int(n)
        d["selecting"] += int(n) if purpose in SELECTING_PURPOSES else 0
        d["by_purpose"][purpose] = int(n)
    pairs = sorted(set(trials) | set(runs) | set(best))
    rows = []
    for key in pairs:
        t, h = key
        n_trials = trials.get(key, 0)
        acc, nr = best.get(key, (None, None))
        n_rows = int(nr) if nr else DEFAULT_HOLDOUT_ROWS
        defl = deflated(acc, n_rows, h or 1, n_trials)
        n_runs, n_cfg, first = runs.get(key, (0, 0, None))
        rd = reads.get(key, {"total": 0, "selecting": 0, "by_purpose": {}})
        verdict = None
        if defl["p_deflated"] is not None:
            # un score au-delà de TOO_GOOD survit à toute déflation et pourtant trahit d'abord une fuite d'information : il se lit à part
            verdict = "suspect" if acc is not None and acc >= TOO_GOOD else ("beyond_noise" if defl["p_deflated"] < 0.10 else "within_noise")
        rows.append({"target": t, "horizon": h, "runs": n_runs, "configs": n_cfg, "trials": n_trials, "best_acc": acc, "n_rows": n_rows,
                     "n_rows_known": bool(nr), **defl, "verdict": verdict, "first_run": first, "reads_recorded": rd["total"],
                     "reads_selecting": rd["selecting"], "reads_inferred": ho_runs.get(key, 0), "duels": duels.get(key, 0)})
    log = [dict(zip(("accessed_at", "target", "horizon", "purpose", "run_id", "holdout_start", "holdout_end", "n_rows", "detail"), r, strict=True))
           for r in _rows(conn, "SELECT accessed_at, target, horizon, purpose, run_id, holdout_start, holdout_end, n_rows, detail FROM holdout_access "
                                "ORDER BY access_id DESC LIMIT ?", (LOG_LIMIT,))]
    n_reads = int(_rows(conn, "SELECT COUNT(*) FROM holdout_access")[0][0])
    first_read = _rows(conn, "SELECT MIN(accessed_at) FROM holdout_access")[0][0]
    from patrick.tracking import stats as trackstats
    fdr = trackstats.fdr_across_targets(conn, alpha=0.10)
    n_beyond = sum(1 for r in rows if r["verdict"] == "beyond_noise")
    n_tested = sum(1 for r in rows if r["verdict"] is not None)
    return sc.jsonable({
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M"),
        "registry": {"total": reg_total, "by_source": {s: {"rows": r, "trials": n} for s, (r, n) in reg_src.items()}, "monthly": monthly,
                     "targets": len({k[0] for k in trials}), "pairs": len(trials)},
        "runs": {"done": sum(v[0] for v in runs.values()), "configs": sum(v[1] for v in runs.values())},
        "reads": {"recorded": n_reads, "first_at": first_read, "selecting": sum(v["selecting"] for v in reads.values()),
                  "inferred": sum(ho_runs.values()), "duels": sum(duels.values()), "pairs_read_more_than_once": sum(1 for r in rows if r["reads_recorded"] + r["reads_inferred"] > 1)},
        "fdr": {"alpha": fdr["alpha"], "n_tested": fdr["n_tested"], "n_raw_significant": fdr["n_raw_significant"], "n_bh_significant": fdr["n_bh_significant"]},
        "rows": rows, "log": log, "verdicts": {"beyond_noise": n_beyond, "tested": n_tested},
    })
