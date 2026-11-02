"""Banc de rejeu du dimensionnement appris (bandit LinUCB et Kelly ridge) contre les heuristiques de /simulate, sur les champions à 1 jour de la vraie base.

Usage : python scripts/bandit_sizing_bench.py [--max-models N] [--out rapport.md]

Lecture seule : la base est ouverte en `mode=ro`, le magasin de données est seulement lu. Le préchauffage lit les prédictions `test` (walk-forward, antérieures au holdout), l'évaluation
porte sur le `holdout`. Biais connu, commun à toutes les politiques comparées : les modèles sont des champions, choisis sur ce même holdout (ADR 0005). Voir `patrick/simulate/sizing_bandit.py`."""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time

import numpy as np
import pandas as pd

from patrick.data.session_calendar import classify_asset_class
from patrick.data.sources.yfinance_source import clean_symbol
from patrick.data.store import DataStore
from patrick.simulate import sizing_bandit as sb
from patrick.tracking import db as trackdb

MIN_TEST, MIN_HOLDOUT = 300, 100


def load_models(conn: sqlite3.Connection, store: DataStore, max_models: int | None):
    champions = conn.execute("SELECT c.target, c.trial_id, c.run_id FROM champion c WHERE c.horizon = 1 ORDER BY c.target").fetchall()
    for target, trial_id, run_id in champions[: max_models or None]:
        if "__alpha_" in target:
            continue
        rows = conn.execute("SELECT ts, split, p_up FROM prediction INDEXED BY sqlite_autoindex_prediction_1 "
                            "WHERE trial_id = ? AND split IN ('test', 'holdout') AND p_up IS NOT NULL ORDER BY ts", (trial_id,)).fetchall()
        df = pd.DataFrame(rows, columns=["ts", "split", "p_up"])
        if (df["split"] == "test").sum() < MIN_TEST or (df["split"] == "holdout").sum() < MIN_HOLDOUT:
            continue
        snapshot = conn.execute("SELECT snapshot_id FROM run WHERE run_id = ?", (run_id,)).fetchone()[0]
        try:
            raw = store.load(f"raw_{target}", snapshot_id=snapshot)
            close = raw[clean_symbol(target)].ffill().dropna()
        except Exception as exc:  # noqa: BLE001 -- un instantané absent ou illisible écarte ce modèle, pas le banc
            print(f"  [SKIP] {target}: {type(exc).__name__}: {str(exc)[:80]}", flush=True)
            continue
        df["ts"] = pd.to_datetime(df["ts"])
        df = df.drop_duplicates("ts").set_index("ts").sort_index()
        yield sb.ModelData(target, df["p_up"].astype(float), df["split"], close)


def fmt(summary: dict) -> list[str]:
    lines = [f"**{summary['candidate']}** : Sharpe net moyen {summary['mean_sharpe']:.3f} sur {summary['n_models']} modèles"]
    lines.append("| contre | Sharpe moyen de l'heuristique | écart moyen | médiane | part meilleure | IC | test des signes (p) |")
    lines.append("|---|---|---|---|---|---|---|")
    for name, v in summary["versus"].items():
        lines.append(f"| {name} | {v['baseline_mean_sharpe']:.3f} | {v['mean_diff']:+.3f} | {v['median_diff']:+.3f} | {v['share_better']:.0%} | "
                     f"[{v['ci'][0]:+.3f} ; {v['ci'][1]:+.3f}] | {v['sign_test_p']:.3f} |")
    lines.append(f"Verdict : {'bat TOUTES les heuristiques (IC > 0)' if summary['beats_all'] else 'ne bat pas toutes les heuristiques'}")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-models", type=int, default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    db_path = trackdb.default_db_path()
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=60)
    store = DataStore()
    results, t0 = [], time.time()
    for k, data in enumerate(load_models(conn, store, args.max_models), 1):
        res = sb.compare_model(data)
        if res.get("ok"):
            res["asset_class"] = classify_asset_class(data.target)
            results.append(res)
        if k % 25 == 0:
            print(f"  {k} modèles rejoués ({time.time() - t0:.0f} s)", flush=True)
    conn.close()
    lines = [f"# Banc de rejeu du dimensionnement appris ({len(results)} champions à 1 jour, coût {sb.COST_BPS:.0f} pb par unité de rotation)", ""]
    for candidate in ("bandit", "kelly_ridge"):
        lines += fmt(sb.summarize(results, candidate, ci_level=0.975)) + [""]          # 2 candidats : IC à 97,5 % (Bonferroni)
    lines.append("Par classe d'actifs (écart de Sharpe moyen contre le seuil 0,55) :")
    for cls in sorted({r["asset_class"] for r in results}):
        sub = [r for r in results if r["asset_class"] == cls]
        d = {c: np.nanmean([r[c]["sharpe"] - r["threshold"]["sharpe"] for r in sub]) for c in ("bandit", "kelly_ridge")}
        lines.append(f"- {cls} ({len(sub)}) : bandit {d['bandit']:+.3f}, kelly_ridge {d['kelly_ridge']:+.3f}")
    text = "\n".join(lines)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
