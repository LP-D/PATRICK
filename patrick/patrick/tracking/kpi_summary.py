"""KPI summary of a finished launch: per algorithm, per number of features,
a ranking of the tested configurations and the best one per horizon -- to
decide which setup to launch next.

Read-only, computed from the tracking database (`trial` / `fold_metric`), so
it works for any past run and costs nothing at training time.

Comparison window. Candidates must be compared on the SAME rows:
- total-window screening: every candidate was scored once on the whole
  out-of-sample window (split 'valid', fold 0); that is the window.
- otherwise, the set of folds every candidate of a horizon went through: the
  first fold only in first-fold staged screening (non-finalists stop there),
  all folds in exhaustive mode. A candidate's score is the mean of its test
  metrics over that window.
The best candidate's walk-forward score over ITS complete period (all the
'test' folds it went through) is reported separately.

The grid is the untuned `global` scan: Optuna re-evaluations (params_json
other than '{}') and the other model categories are not candidates.
"""
from __future__ import annotations

import sqlite3

METRICS = ("F1_dir", "Acc_dir", "MCC_4cls", "BalAcc_4cls")
_CHUNK = 400
_TOP_RANKING_IN_TEXT = 10


def sibling_run_ids(conn: sqlite3.Connection, run_id: str) -> list[str]:
    """The runs of the same launch (one run per horizon share a `job_id`);
    just `[run_id]` for a run without a job (CLI); [] if unknown."""
    row = conn.execute("SELECT job_id FROM run WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        return []
    if not row[0]:
        return [run_id]
    return [r[0] for r in conn.execute("SELECT run_id FROM run WHERE job_id = ? ORDER BY horizon", (row[0],))]


def _mean(values) -> float | None:
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _chunks(items: list, size: int = _CHUNK):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _load_trials(conn: sqlite3.Connection, run_ids: list[str]) -> list[dict]:
    trials: list[dict] = []
    for chunk in _chunks(run_ids):
        marks = ",".join("?" * len(chunk))
        rows = conn.execute(
            "SELECT t.trial_id, t.run_id, r.horizon, r.target, t.algo, t.sampler, t.n_features, t.regime "
            "FROM trial t JOIN run r ON r.run_id = t.run_id "
            f"WHERE t.run_id IN ({marks}) AND t.category = 'global' "
            "AND (t.params_json IS NULL OR t.params_json IN ('{}', ''))", chunk).fetchall()
        keys = ("trial_id", "run_id", "horizon", "target", "algo", "sampler", "n_features", "regime")
        trials.extend(dict(zip(keys, row)) for row in rows)
    by_id = {t["trial_id"]: t for t in trials}
    for t in trials:
        t["folds"] = {}
        t["screen"] = {}
    ids = list(by_id)
    for chunk in _chunks(ids):
        marks = ",".join("?" * len(chunk))
        for trial_id, split, fold, metric, value in conn.execute(
                f"SELECT trial_id, split, fold_index, metric, value FROM fold_metric WHERE trial_id IN ({marks}) "
                "AND split IN ('test', 'valid') AND metric IN (" + ",".join("?" * len(METRICS)) + ")",
                [*chunk, *METRICS]):
            if split == "valid":
                by_id[trial_id]["screen"][metric] = value        # total-window screening score
            else:
                by_id[trial_id]["folds"].setdefault(int(fold), {})[metric] = value
    return [t for t in trials if t["folds"] or t["screen"]]   # a candidate without any result is not comparable


def _score(folds: dict[int, dict], which) -> dict[str, float | None]:
    return {m: _mean(folds[f].get(m) for f in which) for m in METRICS}


def _ranked(rows: list[dict]) -> list[dict]:
    rows.sort(key=lambda r: (r["F1_dir"] is None, -(r["F1_dir"] or 0.0)) + tuple(
        str(r.get(k, "")) for k in ("algo", "n_features", "sampler")))
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows


def _group(trials: list[dict], key_fields: tuple[str, ...]) -> list[dict]:
    groups: dict[tuple, list[dict]] = {}
    for t in trials:
        groups.setdefault(tuple(t[k] for k in key_fields), []).append(t)
    rows = []
    for key, members in groups.items():
        row = dict(zip(key_fields, key, strict=True))
        row["n"] = len(members)
        row["n_horizons"] = len({m["horizon"] for m in members})
        for metric in METRICS:
            row[metric] = _mean(m["score"].get(metric) for m in members)
        rows.append(row)
    return _ranked(rows)


def _final_model(conn: sqlite3.Connection, run_id: str) -> dict:
    row = conn.execute(
        "SELECT trial_id, algo, n_features FROM trial WHERE run_id = ? AND is_best = 1 "
        "ORDER BY trial_id DESC LIMIT 1", (run_id,)).fetchone()
    if row is None:
        return {"final_algo": None, "final_n_features": None, "holdout_F1_dir": None, "holdout_Acc_dir": None}
    holdout = dict(conn.execute(
        "SELECT metric, AVG(value) FROM fold_metric WHERE trial_id = ? AND split = 'holdout' "
        "AND metric IN ('F1_dir', 'Acc_dir') GROUP BY metric", (row[0],)).fetchall())
    return {"final_algo": row[1], "final_n_features": row[2],
            "holdout_F1_dir": holdout.get("F1_dir"), "holdout_Acc_dir": holdout.get("Acc_dir")}


def _holdout_diagnostic(conn: sqlite3.Connection, trial_id: int) -> dict:
    """Holdout score of a scan trial (`holdout_diagnostic`, read-only, never
    used to choose anything): the best config BEFORE Optuna, for every
    horizon -- the final holdout evaluation only covers the launch's best
    horizon."""
    scores = dict(conn.execute(
        "SELECT metric, value FROM holdout_diagnostic WHERE trial_id = ? AND metric IN ('F1_dir', 'Acc_dir')",
        (trial_id,)).fetchall())
    return {"diag_F1_dir": scores.get("F1_dir"), "diag_Acc_dir": scores.get("Acc_dir")}


def summarize(conn: sqlite3.Connection, run_ids: list[str]) -> dict:
    trials = _load_trials(conn, list(run_ids)) if run_ids else []
    runs = {t["run_id"]: t["horizon"] for t in trials}

    folds_by_horizon: dict[int, list[int]] = {}
    extended = False
    total_window = False
    for run_id, horizon in runs.items():
        members = [t for t in trials if t["run_id"] == run_id]
        if all(t["screen"] for t in members):                  # every candidate screened on the total window
            total_window = True
            folds_by_horizon[horizon] = [0]
            for t in members:
                t["window"] = [0]
                t["score"] = {m: t["screen"].get(m) for m in METRICS}
            continue
        members = [t for t in members if t["folds"]]
        common = set.intersection(*(set(t["folds"]) for t in members)) if members else set()
        folds_by_horizon[horizon] = sorted(common)
        extended = extended or any(set(t["folds"]) != common for t in members)
        for t in members:
            t["window"] = sorted(common)
            t["score"] = _score(t["folds"], t["window"]) if common else {}
    trials = [t for t in trials if t.get("window")]

    target = trials[0]["target"] if trials else None
    if not trials:
        note = "Aucun candidat de la grille d'exploration n'a de résultat pour ce lancement."
    elif total_window:
        note = ("Tous les candidats sont comparés sur la même fenêtre : la fenêtre totale (un seul entraînement par "
                "candidat, testé d'un coup sur toute la période hors-échantillon ; seul le meilleur de chaque horizon "
                "passe ensuite au walk-forward). Le meilleur y étant choisi, son score sur cette fenêtre est "
                "optimiste : compare-le à sa performance en walk-forward (toute sa période) et au holdout.")
    elif extended:
        note = ("Tous les candidats sont comparés sur la même fenêtre : le premier fold (dépistage par étapes : "
                "seul le meilleur de chaque horizon est évalué sur les folds suivants). Le meilleur y étant choisi, "
                "son score sur cette fenêtre est optimiste : compare-le à sa performance sur toute sa période et au holdout.")
    else:
        note = "Tous les candidats sont comparés sur la même fenêtre : l'ensemble des folds de validation."

    by_horizon = []
    for run_id, horizon in sorted(runs.items(), key=lambda kv: kv[1]):
        members = [t for t in trials if t["run_id"] == run_id]
        best = min(members, key=lambda t: (-(t["score"].get("F1_dir") or 0.0), t["algo"], t["n_features"]))
        full = _score(best["folds"], sorted(best["folds"])) if best["folds"] else dict.fromkeys(METRICS)
        by_horizon.append({
            "horizon": horizon, "run_id": run_id, "algo": best["algo"], "n_features": best["n_features"],
            "sampler": best["sampler"],
            "window_F1_dir": best["score"].get("F1_dir"), "window_Acc_dir": best["score"].get("Acc_dir"),
            "full_F1_dir": full["F1_dir"], "full_Acc_dir": full["Acc_dir"], "full_folds": len(best["folds"]),
            **_holdout_diagnostic(conn, best["trial_id"]), **_final_model(conn, run_id)})

    return {
        "run_ids": list(runs), "target": target, "horizons": sorted(set(runs.values())),
        "n_candidates": len(trials),
        "window": {"mode": "total_window" if total_window else ("first_fold" if extended else "all_folds"),
                   "folds_by_horizon": folds_by_horizon, "note": note},
        "by_algo": _group(trials, ("algo",)),
        "by_n_features": _group(trials, ("n_features",)),
        "ranking": _group(trials, ("algo", "n_features", "sampler")),
        "by_horizon": by_horizon,
    }


def _f(value) -> str:
    return "  —  " if value is None else f"{value:.3f}"


def format_text(summary: dict) -> str:
    """Plain-text report (worker log). Same figures as the web page."""
    if not summary["n_candidates"]:
        return "[KPI] " + summary["window"]["note"]
    horizons = ", ".join(str(h) for h in summary["horizons"])
    title = (f"[KPI] Synthèse des modèles -- {summary['target']}, horizons {horizons} "
             f"({summary['n_candidates']} candidats testés)")
    out = [title, f"      {summary['window']['note']}", ""]
    head = f"{'rang':>4}  {{label:<14}} {'n':>5}  {'F1_dir':>6}  {'Acc_dir':>7}  {'MCC_4cls':>8}  {'BalAcc_4cls':>11}"

    def table(title: str, rows: list[dict], label_of):
        out.append(title)
        out.append(head.format(label=""))
        for r in rows:
            out.append(f"{r['rank']:>4}  {label_of(r):<14} {r['n']:>5}  {_f(r['F1_dir']):>6}  "
                       f"{_f(r['Acc_dir']):>7}  {_f(r['MCC_4cls']):>8}  {_f(r['BalAcc_4cls']):>11}")
        out.append("")

    table("Par algorithme (moyenne sur les horizons et les nombres de variables) :",
          summary["by_algo"], lambda r: r["algo"])
    table("Par nombre de variables (moyenne sur les horizons et les algorithmes) :",
          summary["by_n_features"], lambda r: f"N={r['n_features']}")
    top = summary["ranking"][:_TOP_RANKING_IN_TEXT]
    table(f"Classement des configurations (algorithme x nombre de variables), top {len(top)} sur "
          f"{len(summary['ranking'])} :", top, lambda r: f"{r['algo']} N={r['n_features']}")
    out.append("Par horizon -- meilleure configuration, sa performance sur toute sa période, son holdout "
               "(config du scan, avant Optuna), puis le modèle final :")
    out.append(f"{'h':>4}  {'meilleure config':<20} {'F1 fenêtre':>10}  {'F1 période':>10} {'folds':>5}  "
               f"{'F1 holdout':>10}  {'Acc holdout':>11}  {'modèle final':<18} {'F1 holdout final':>16}")
    for r in summary["by_horizon"]:
        final = f"{r['final_algo']} N={r['final_n_features']}" if r["final_algo"] else "—"
        out.append(f"{r['horizon']:>4}  {r['algo'] + ' N=' + str(r['n_features']):<20} "
                   f"{_f(r['window_F1_dir']):>10}  {_f(r['full_F1_dir']):>10} {r['full_folds']:>5}  "
                   f"{_f(r['diag_F1_dir']):>10}  {_f(r['diag_Acc_dir']):>11}  "
                   f"{final:<18} {_f(r['holdout_F1_dir']):>16}")
    return "\n".join(out)
