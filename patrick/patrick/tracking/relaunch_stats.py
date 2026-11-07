"""Suivi des relances conseillées : quelle suggestion a produit quel job, ce que le duel des champions en a fait, quels modèles ne savent plus prédire.

Tout est de la mesure, jamais une décision : une écriture qui échoue (base verrouillée, table pas encore migrée dans un worker démarré avant la mise à jour)
ne doit jamais faire échouer un lancement, un duel ou une prédiction, donc chaque fonction d'écriture avale `sqlite3.Error` et le dit par son retour.

Le conseiller s'en sert de deux façons, toutes deux inertes tant que la mesure est maigre :
- `suggestion_factor` : le taux de victoire au duel de chaque clé de suggestion, ramené vers le taux global (`PRIOR_WEIGHT`), borne le score entre
  `FACTOR_MIN` et `FACTOR_MAX` une fois `MIN_DUELS_PER_KEY` duels observés pour cette clé et `MIN_DUELS_TOTAL` au total ;
- `live_failure` : un modèle dont la prédiction quotidienne échoue `MIN_FAILURES` jours de suite faute de colonnes d'entrée déclenche la suggestion `inputs_lost`.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime

DECIDED = ("challenger_wins", "champion_wins")
MIN_DUELS_PER_KEY = 30
MIN_DUELS_TOTAL = 100
PRIOR_WEIGHT = 20.0
FACTOR_MIN, FACTOR_MAX = 0.7, 1.3
MIN_FAILURES = 3
_MISSING = re.compile(r"Training pool columns missing from the fresh data: \[(.*?)\]")


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def record_relaunch(conn: sqlite3.Connection, job_id: str, parent_run_id: str, key: str, source: str) -> bool:
    """Note que `job_id` vient de la suggestion `key` du conseiller pour `parent_run_id` (`source` : `batch` ou `form`)."""
    try:
        conn.execute("INSERT OR REPLACE INTO relaunch_log(job_id, parent_run_id, suggestion_key, source) VALUES (?, ?, ?, ?)",
                     (job_id, parent_run_id, key, source))
        conn.commit()
        return True
    except sqlite3.Error:
        return False


def record_duel(conn: sqlite3.Connection, *, job_id: str | None, run_id: str, target: str, horizon: int, decision: dict,
                duration_s: float | None = None, shadow: dict | None = None) -> bool:
    """Une ligne par duel (`decision` : le dictionnaire de `champion_duel._duel_one`). `shadow` : ce que la règle d'arrêt anticipé, observée sans agir, aurait fait."""
    shadow = shadow or {}
    try:
        conn.execute(
            "INSERT INTO duel_outcome(job_id, run_id, target, horizon, decision, criterion, challenger_score, champion_score, duration_s, "
            "shadow_stop_fold, shadow_best, shadow_champion, n_folds) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (job_id, run_id, target, int(horizon), str(decision.get("decision")), decision.get("criterion"),
             decision.get("challenger_score", decision.get("challenger_f1_dir")), decision.get("champion_score", decision.get("champion_f1_dir")),
             duration_s, shadow.get("stop_fold"), shadow.get("best"), shadow.get("champion"), shadow.get("n_folds")))
        conn.commit()
        return True
    except sqlite3.Error:
        return False


def suggestion_stats(conn: sqlite3.Connection) -> dict:
    """`{"total": {"n", "wins"}, "by_key": {clé: {"n", "wins", "win_rate"}}}` sur les duels tranchés des jobs lancés depuis une suggestion."""
    out: dict = {"total": {"n": 0, "wins": 0}, "by_key": {}}
    try:
        rows = conn.execute(
            "SELECT l.suggestion_key, COUNT(*), SUM(d.decision = 'challenger_wins') FROM relaunch_log l JOIN duel_outcome d ON d.job_id = l.job_id "
            f"WHERE d.decision IN ({','.join('?' for _ in DECIDED)}) GROUP BY l.suggestion_key", DECIDED).fetchall()
    except sqlite3.Error:
        return out
    for key, n, wins in rows:
        wins = int(wins or 0)
        out["by_key"][key] = {"n": int(n), "wins": wins, "win_rate": wins / n}
        out["total"]["n"] += int(n)
        out["total"]["wins"] += wins
    return out


def suggestion_factor(stats: dict | None, key: str) -> float:
    """Multiplicateur (entre `FACTOR_MIN` et `FACTOR_MAX`) du score d'une suggestion selon ses victoires passées ; 1,0 tant que la mesure est maigre."""
    if not stats:
        return 1.0
    total, entry = stats["total"], stats["by_key"].get(key)
    if entry is None or entry["n"] < MIN_DUELS_PER_KEY or total["n"] < MIN_DUELS_TOTAL or total["wins"] == 0:
        return 1.0
    overall = total["wins"] / total["n"]
    shrunk = (entry["wins"] + PRIOR_WEIGHT * overall) / (entry["n"] + PRIOR_WEIGHT)
    return max(FACTOR_MIN, min(FACTOR_MAX, shrunk / overall))


# -- modèles qui ne savent plus prédire ---------------------------------------------------------------------------------

def record_live_failure(conn: sqlite3.Connection, run_id: str, error: str) -> bool:
    """Un échec de prédiction quotidienne ; `n` compte les échecs de suite (remis à zéro par `clear_live_failure`)."""
    reason = "missing_columns" if _MISSING.search(error or "") else "other"
    now = _now()
    try:
        conn.execute(
            "INSERT INTO live_failure(run_id, reason, detail, n, first_at, last_at) VALUES (?, ?, ?, 1, ?, ?) "
            # un jour de plus seulement : l'application relance les prédictions à chaque ouverture, plusieurs fois par jour
            "ON CONFLICT(run_id) DO UPDATE SET reason = excluded.reason, detail = excluded.detail, last_at = excluded.last_at, "
            "n = n + CASE WHEN substr(live_failure.last_at, 1, 10) < substr(excluded.last_at, 1, 10) THEN 1 ELSE 0 END",
            (run_id, reason, (error or "")[:400], now, now))
        conn.commit()
        return True
    except sqlite3.Error:
        conn.rollback()
        return False


def clear_live_failure(conn: sqlite3.Connection, run_id: str) -> bool:
    """Efface la note d'échec d'un modèle qui vient de réussir. Ne prend JAMAIS le verrou d'écriture quand il n'y a rien à effacer : un DELETE
    qui ne touche aucune ligne ouvre quand même une transaction d'écriture, que personne ne fermait (pas de commit), et la connexion de suivi,
    gardée ouverte pendant toute la boucle des prédictions du jour, bloquait alors le worker et le serveur pendant des heures."""
    try:
        if conn.execute("SELECT 1 FROM live_failure WHERE run_id = ?", (run_id,)).fetchone() is None:
            return True
        conn.execute("DELETE FROM live_failure WHERE run_id = ?", (run_id,))
        conn.commit()
        return True
    except sqlite3.Error:
        conn.rollback()
        return False


def live_failure(conn: sqlite3.Connection, run_id: str) -> dict | None:
    """`{"reason", "n", "since", "missing": [colonnes…]}` si ce modèle échoue depuis au moins `MIN_FAILURES` jours de suite faute de colonnes, sinon `None`."""
    try:
        row = conn.execute("SELECT reason, detail, n, first_at FROM live_failure WHERE run_id = ?", (run_id,)).fetchone()
    except sqlite3.Error:
        return None
    if row is None or row[0] != "missing_columns" or row[2] < MIN_FAILURES:
        return None
    found = _MISSING.search(row[1] or "")
    missing = re.findall(r"'([^']+)'", found.group(1)) if found else []
    return {"reason": row[0], "n": int(row[2]), "since": row[3], "missing": missing}
