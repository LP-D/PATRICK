"""Signal regroupé par paire cible-horizon : lecture des prédictions du holdout, test, enregistrement (`pooled_signal`, migration 0049).

Calcul pur dans `validation/pooled_signal.py` ; ici seulement l'accès à la base. Lecture seule sur les prédictions : seules les lignes du
HOLDOUT (15 derniers mois, jamais vus à l'entraînement ni au choix du modèle) entrent, une série par run (son meilleur essai). Les runs
suspects (cible macro retirée, change d'avant l'alignement 2, score impossible) n'y entrent pas."""
from __future__ import annotations

import sqlite3

import pandas as pd

from patrick.data.session_calendar import classify_asset_class
from patrick.tracking import db as trackdb
from patrick.validation import pooled_signal as core

ALPHA = 0.10
REFRESH_DAYS = 7.0          # âge au-delà duquel `refresh_if_stale` recalcule (les holdouts ne bougent qu'avec de nouveaux runs)


def _good_run_ids(conn: sqlite3.Connection) -> dict[str, tuple[str, int]]:
    """`{run_id: (cible, horizon)}` des runs terminés, non archivés et non suspects."""
    return {r["run_id"]: (r["target"], int(r["horizon"])) for r in trackdb.list_all_runs(conn)
            if r["status"] == "done" and not r["suspect"] and r["horizon"]}


def holdout_pairs(conn: sqlite3.Connection) -> dict[tuple[str, int], dict]:
    """`{(cible, horizon): {"frames": [P(hausse) par run], "y": direction réelle, "run_ids": [...]}}` sur le holdout."""
    good = _good_run_ids(conn)
    if not good:
        return {}
    rows = pd.read_sql_query(
        "SELECT t.run_id AS run_id, p.ts AS ts, p.y_true AS y_true, p.p_up AS p_up "
        "FROM trial t JOIN prediction p ON p.trial_id = t.trial_id "
        "WHERE t.is_best = 1 AND p.split = 'holdout' AND p.p_up IS NOT NULL", conn)
    rows = rows[rows.run_id.isin(good)]
    out: dict[tuple[str, int], dict] = {}
    for run_id, group in rows.groupby("run_id"):
        key = good[run_id]
        group = group.drop_duplicates("ts").set_index(pd.to_datetime(group.drop_duplicates("ts").ts))
        entry = out.setdefault(key, {"frames": [], "ys": [], "run_ids": []})
        entry["frames"].append(group.p_up.astype(float))
        entry["ys"].append((group.y_true >= 2).astype(int))
        entry["run_ids"].append(run_id)
    for entry in out.values():                      # direction réelle d'une date : vote des runs (identique pour une cible brute)
        entry["y"] = (pd.concat(entry.pop("ys"), axis=1).mean(axis=1) >= 0.5).astype(int)
    return out


def compute_all(conn: sqlite3.Connection, n_shift: int = core.DEFAULT_SHIFTS, seed: int = 7, alpha: float = ALPHA) -> list[dict]:
    """Teste chaque paire puis corrige l'ensemble (Benjamini-Hochberg) ; renvoie une ligne par paire testable."""
    results: dict[str, dict] = {}
    for (target, horizon), entry in holdout_pairs(conn).items():
        res = core.test_pair(entry["frames"], entry["y"], horizon, n_shift=n_shift, seed=seed)
        if res["n_dates"] >= core.MIN_DATES:
            results[f"{target}|{horizon}"] = {"target": target, "horizon": horizon, **res}
    adjusted = core.adjust(results, alpha=alpha)
    return sorted(adjusted.values(), key=lambda r: (r["q_value"] is None, r["q_value"] if r["q_value"] is not None else 1.0))


def save(conn: sqlite3.Connection, rows: list[dict]) -> None:
    with conn:
        conn.execute("DELETE FROM pooled_signal")
        conn.executemany(
            "INSERT INTO pooled_signal (target, horizon, n_runs, n_dates, auc, auc_run_mean, p_value, q_value, significant) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(r["target"], r["horizon"], r["n_runs"], r["n_dates"], _num(r["auc"]), _num(r["auc_run_mean"]), _num(r["p_value"]),
              r["q_value"], int(r["significant"])) for r in rows])


def refresh_if_stale(conn: sqlite3.Connection, max_age_days: float = REFRESH_DAYS) -> dict:
    """Recalcule la table quand elle est vide ou plus vieille que `max_age_days` : la Synthèse et les cartes de lots la lisent, et elle
    n'était écrite que par une commande à lancer à la main (vide le 2026-11-13, pour 3 375 champions). `{"refreshed", "n_pairs",
    "n_significant"}`. Le calcul ne fait que lire ; l'écriture est une transaction courte."""
    row = conn.execute("SELECT COUNT(*), MIN(computed_at) FROM pooled_signal").fetchone()
    if row[0]:
        age = conn.execute("SELECT julianday('now') - julianday(?)", (row[1],)).fetchone()[0]
        if age is not None and age < max_age_days:
            return {"refreshed": False, "n_pairs": int(row[0]), "n_significant": None}
    rows = compute_all(conn)
    if rows:                                         # rien de testable : on garde l'ancienne mesure plutôt qu'une table vide
        save(conn, rows)
    return {"refreshed": bool(rows), "n_pairs": len(rows), "n_significant": sum(1 for r in rows if r["significant"])}


def _num(value):
    return None if value is None or pd.isna(value) else float(value)


def load(conn: sqlite3.Connection) -> list[dict]:
    cur = conn.execute("SELECT target, horizon, n_runs, n_dates, auc, auc_run_mean, p_value, q_value, significant, computed_at "
                       "FROM pooled_signal ORDER BY q_value IS NULL, q_value, target, horizon")
    return [dict(zip(("target", "horizon", "n_runs", "n_dates", "auc", "auc_run_mean", "p_value", "q_value", "significant", "computed_at"),
                     row)) for row in cur]


def class_summary(rows: list[dict]) -> list[dict]:
    """Par classe d'actifs : paires testées, paires significatives (BH), AUC regroupée moyenne. Plus forte AUC d'abord."""
    by_class: dict[str, list[dict]] = {}
    for row in rows:
        target = row["target"].split("__alpha_")[0]
        by_class.setdefault(classify_asset_class(target), []).append(row)
    out = []
    for key, items in by_class.items():
        aucs = [r["auc"] for r in items if r["auc"] is not None]
        out.append({"class": key, "n_pairs": len(items), "n_significant": sum(1 for r in items if r["significant"]),
                    "auc": sum(aucs) / len(aucs) if aucs else None})
    return sorted(out, key=lambda c: (c["auc"] is None, -(c["auc"] or 0.0)))


def summary(conn: sqlite3.Connection) -> dict | None:
    """Pour la Synthèse : `{n_tested, n_significant, alpha, computed_at, classes}` ou `None` si jamais calculé."""
    rows = load(conn)
    if not rows:
        return None
    return {"n_tested": sum(1 for r in rows if r["p_value"] is not None), "n_significant": sum(1 for r in rows if r["significant"]),
            "alpha": ALPHA, "computed_at": rows[0]["computed_at"], "classes": class_summary(rows)}
