"""Base de démonstration : une petite base PATRICK remplie de données SYNTHÉTIQUES, pour regarder l'interface sans la vraie base.

    python scripts/make_demo_db.py C:\\chemin\\demo\\patrick.db

Puis lancer l'interface dessus, sans prédictions ni worker :

    set PATRICK_DB_PATH=C:\\chemin\\demo\\patrick.db
    set PATRICK_LIVE_REFRESH=0
    set PATRICK_NO_AUTO_WORKER=1
    python -m patrick.cli serve --port 8765

La vraie base (plusieurs dizaines de Go) ne se copie pas pour un examen visuel, et l'ouvrir avec une version en cours de
développement lui appliquerait ses migrations. Cette base-ci tient en quelques Mo : des cibles de chaque classe d'actifs, leurs
champions, des scores de test et de holdout, des prédictions réelles jugées, un signal regroupé, quelques duels et un modèle en échec.
Aucun modèle n'est entraîné et rien n'est téléchargé : tous les chiffres sont tirés au hasard (graine fixe), ils ne veulent rien dire.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import sys
from pathlib import Path

from patrick.config.schema import RunConfig
from patrick.tracking import db as trackdb
from patrick.tracking import relaunch_stats

TARGETS = ("^GSPC", "^VIX", "AAPL", "MSFT", "MC.PA", "TTE.PA", "EURUSD=X", "GC=F", "CL=F", "BTC-USD")
HORIZONS = (1, 5, 10)
ALGOS = ("LightGBM", "XGBoost", "RandomForest", "CatBoost")
LIVE_DAYS = 45


def _business_days(end: dt.date, n: int) -> list[dt.date]:
    days: list[dt.date] = []
    day = end
    while len(days) < n:
        if day.weekday() < 5:
            days.append(day)
        day -= dt.timedelta(days=1)
    return days[::-1]


def build(db_path: str, today: dt.date | None = None, seed: int = 7) -> dict:
    """Crée (ou complète) la base `db_path`. Renvoie `{"runs", "champions", "live"}` (nombres de lignes écrites)."""
    today = today or dt.date.today()
    rng = random.Random(seed)
    conn = trackdb.connect(db_path)
    try:
        trackdb.upsert_snapshot(conn, "demo_snapshot", "demo_hash", len(TARGETS), 0, None)
        days = _business_days(today, LIVE_DAYS)
        n_live = 0
        for target in TARGETS:
            skill = rng.uniform(-0.04, 0.10)                       # « talent » synthétique de la cible : certaines au-dessus du hasard
            for horizon in HORIZONS:
                run_id = f"demo_{target}_{horizon}".replace("^", "").replace("=", "_").replace(".", "_").replace("-", "_")
                config = RunConfig.model_validate({"name": run_id, "objective": {"target_symbol": target, "horizons": [horizon]}})
                trackdb.create_run(conn, run_id, target, horizon, "demo_snapshot", config.model_dump_json(), "demo", "demo", 42)
                trial_id = trackdb.create_trial(conn, run_id, "GLOBAL", rng.choice(ALGOS), "SMOTE", rng.choice((6, 8, 12)), "shap")
                trackdb.mark_best_trial(conn, trial_id)
                auc = 0.5 + skill + rng.uniform(-0.02, 0.02)
                for fold in range(1, 6):
                    trackdb.add_fold_metrics(conn, trial_id, fold, "test", {
                        "AUC_ovr_4cls": auc + rng.uniform(-0.03, 0.03), "F1_dir": 0.5 + skill / 2 + rng.uniform(-0.03, 0.03),
                        "AUC_dir": auc + rng.uniform(-0.03, 0.03), "Acc_dir": 0.5 + skill / 2 + rng.uniform(-0.03, 0.03)})
                trackdb.add_fold_metrics(conn, trial_id, 0, "holdout", {
                    "AUC_ovr_4cls": auc - 0.01, "F1_dir": 0.5 + skill / 2, "AUC_dir": auc - 0.01, "Acc_dir": 0.5 + skill / 2,
                    "Brier_up": 0.25 - skill / 10, "ECE_up": 0.05})
                trackdb.finish_run(conn, run_id, "done", n_trials=20)
                conn.execute("INSERT OR REPLACE INTO champion (target, horizon, run_id, trial_id, reason, holdout_f1_dir) "
                             "VALUES (?, ?, ?, ?, 'first', ?)", (target, horizon, run_id, trial_id, 0.5 + skill / 2))
                rows = []
                for index, day in enumerate(days):
                    went_up = rng.random() < 0.56
                    right = rng.random() < 0.5 + skill
                    said_up = went_up if right else not went_up
                    p_up = min(0.95, max(0.05, (0.62 if said_up else 0.38) + rng.uniform(-0.1, 0.1)))
                    judged = index < len(days) - horizon              # les derniers signaux attendent encore leur échéance
                    rows.append((trial_id, day.isoformat(), (1.0 if went_up else 0.0) if judged else None, 3 if said_up else 0, 0.6, p_up))
                conn.executemany("INSERT OR REPLACE INTO prediction (trial_id, ts, split, y_true, y_pred, y_proba, p_up) "
                                 "VALUES (?, ?, 'live', ?, ?, ?, ?)", rows)
                n_live += len(rows)
                conn.execute("INSERT OR REPLACE INTO pooled_signal (target, horizon, n_runs, n_dates, auc, auc_run_mean, p_value, q_value, significant) "
                             "VALUES (?, ?, 1, 300, ?, ?, ?, ?, ?)",
                             (target, horizon, auc, auc, 0.01 if skill > 0.05 else 0.4, 0.04 if skill > 0.05 else 0.6, int(skill > 0.05)))
        conn.commit()
        relaunch_stats.record_duel(conn, job_id="demo_job_1", run_id="demo_AAPL_1", target="AAPL", horizon=1,
                                   decision={"decision": "challenger_wins", "criterion": "AUC_dir", "challenger_score": 0.58, "champion_score": 0.54})
        relaunch_stats.record_duel(conn, job_id="demo_job_2", run_id="demo_MSFT_1", target="MSFT", horizon=1,
                                   decision={"decision": "champion_wins", "criterion": "AUC_dir", "challenger_score": 0.51, "champion_score": 0.55})
        relaunch_stats.record_live_failure(
            conn, "demo_CL_F_5", "Training pool columns missing from the fresh data: ['OJ=F_vol_10d'] -- the config may have changed since export.")
        n_runs = conn.execute("SELECT COUNT(*) FROM run").fetchone()[0]
        n_champions = conn.execute("SELECT COUNT(*) FROM champion").fetchone()[0]
        return {"runs": int(n_runs), "champions": int(n_champions), "live": n_live, "config": json.loads(config.model_dump_json())["name"]}
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Crée une base PATRICK de démonstration (données synthétiques).")
    parser.add_argument("db_path", help="Fichier à créer, HORS du dossier des vraies données")
    args = parser.parse_args(argv)
    target = Path(args.db_path).resolve()
    if target.exists():
        print(f"{target} existe déjà : choisis un fichier neuf (rien n'est écrasé).")
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    done = build(str(target))
    print(f"Base de démonstration écrite : {target} ({done['runs']} runs, {done['champions']} champions, {done['live']} prédictions réelles).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
