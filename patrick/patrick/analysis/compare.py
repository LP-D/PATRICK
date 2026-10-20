"""Comparaison détaillée de 2 à 4 runs ML / DL : chiffres de tête côte à côte, courbes superposées (équité, exactitude glissante, fiabilité,
ROC), exactitude par pli, matrice de tests de Diebold-Mariano corrigée par Holm, différences de configuration.

Les tests de Diebold-Mariano comparent la perte 0/1 de la direction sur les DATES COMMUNES à deux runs (test et holdout confondus, une
seule trajectoire CPCV) : deux runs de cibles différentes n'ont aucune date de prédiction comparable au-delà du calendrier, le test est alors dit
non testable plutôt que calculé sur un alignement douteux (même cible et même horizon exigés)."""
from __future__ import annotations

import json
import sqlite3
from itertools import combinations

import pandas as pd

from patrick.analysis import sec_meta, sec_perf, sec_predict
from patrick.analysis import stats_core as sc
from patrick.analysis.context import Ctx
from patrick.analysis.registry import get_frame
from patrick.validation.diebold_mariano import diebold_mariano

MAX_RUNS = 4
MIN_COMMON = 30
MAX_DIFF_ROWS = 300


def _flatten(obj, prefix: str = "") -> dict[str, str]:
    """Configuration aplatie en `chemin -> texte JSON`. Les listes sont gardées entières (leur égalité compte) mais résumées à l'affichage."""
    out: dict[str, str] = {}
    if isinstance(obj, dict):
        for k in sorted(obj):
            out.update(_flatten(obj[k], f"{prefix}.{k}" if prefix else str(k)))
    else:
        out[prefix] = json.dumps(obj, ensure_ascii=False, sort_keys=True)
    return out


def config_diff(configs: list[dict]) -> list[dict]:
    flat = [_flatten(c) for c in configs]
    keys = sorted({k for f in flat for k in f})
    rows = []
    for k in keys:
        vals = [f.get(k) for f in flat]
        if len(set(vals)) > 1:
            rows.append({"key": k, "values": [_short(v) for v in vals]})
    return rows[:MAX_DIFF_ROWS]


def _short(v: str | None) -> str | None:
    """Valeur d'affichage : les chaînes sans leurs guillemets JSON, le reste en JSON compact, tronqué à 90 caractères."""
    if v is None:
        return None
    try:
        parsed = json.loads(v)
    except ValueError:
        parsed = v
    text = parsed if isinstance(parsed, str) else v
    return text if len(text) <= 90 else text[:87] + "…"


def _losses(ctx: Ctx) -> pd.Series:
    d = ctx.evaluated(("test", "holdout"))
    d = d.drop_duplicates("ts", keep="last")
    return pd.Series(((d["ut"] >= 0.5) != d["up"]).astype(float).to_numpy(), index=d["ts"].to_numpy())


def dm_matrix(ctxs: list[Ctx], names: list[str]) -> dict:
    """Matrice (ligne contre colonne) des p-values de Diebold-Mariano, corrigées par Holm sur l'ensemble des paires testables.
    `better` : celui des deux dont la perte moyenne est la plus basse sur les dates communes."""
    n = len(ctxs)
    losses = [_losses(c) for c in ctxs]
    pairs = []
    for i, j in combinations(range(n), 2):
        same = (ctxs[i].fr.run["target"] == ctxs[j].fr.run["target"]) and (ctxs[i].fr.horizon == ctxs[j].fr.horizon)
        idx = losses[i].index.intersection(losses[j].index)
        cell = {"i": i, "j": j, "n": len(idx), "p": None, "p_adj": None, "stat": None, "better": None, "reason": None}
        if not same:
            cell["reason"] = "different_target_or_horizon"
        elif len(idx) < MIN_COMMON:
            cell["reason"] = "few_common_dates"
        else:
            a, b = losses[i].loc[idx].to_numpy(), losses[j].loc[idx].to_numpy()
            res = diebold_mariano(a, b, h=ctxs[i].fr.horizon)
            if res.get("untestable_reason"):
                cell["reason"] = res["untestable_reason"]
            else:
                cell["p"], cell["stat"] = res["p_value"], res["dm_stat"]
                cell["better"] = i if float(a.mean()) < float(b.mean()) else (j if float(b.mean()) < float(a.mean()) else None)
                cell["loss_i"], cell["loss_j"] = float(a.mean()), float(b.mean())
        pairs.append(cell)
    testable = sorted((c for c in pairs if c["p"] is not None), key=lambda c: c["p"])
    m = len(testable)
    running = 0.0
    for rank, c in enumerate(testable):                     # Holm : p_(k) * (m - k + 1), croissant
        running = max(running, min(1.0, c["p"] * (m - rank)))
        c["p_adj"] = running
    return {"names": names, "pairs": pairs, "n_tested": m}


def _equity_overlay(ctx: Ctx, cost_bps: float) -> dict | None:
    fr = ctx.fr
    if fr.levels is None:
        return None
    d = ctx.one_path(fr.df[fr.df["split_name"].isin(["test", "holdout", "live"])]).sort_values("ts", kind="mergesort")
    strat = sec_perf.build_strategies(fr, d)
    if strat is None:
        return None
    ls = sc.equity_from_returns(sec_perf._net(strat["long_short"], cost_bps).to_numpy())
    bh = sc.equity_from_returns(strat["buy_hold"]["gross"].to_numpy())
    idx = sc.thin_indices(len(ls), 700)
    dates = strat["dates"]
    return {"dates": [dates[i].strftime("%Y-%m-%d") for i in idx], "long_short": ls[idx], "buy_hold": bh[idx],
            "stats": sc.performance_summary(sec_perf._net(strat["long_short"], cost_bps).to_numpy())}


def compare(conn: sqlite3.Connection, run_ids: list[str], cost_bps: float = 5.0, window: int = 120, db_key: str = "") -> dict | None:
    """`None` si un identifiant est inconnu ou sans essai retenu."""
    run_ids = list(dict.fromkeys(run_ids))[:MAX_RUNS]
    ctxs: list[Ctx] = []
    for rid in run_ids:
        fr = get_frame(conn, rid, None, db_key)
        if fr is None:
            return None
        ctxs.append(Ctx(conn, fr, {"window": str(window)}))
    runs = []
    for c in ctxs:
        ov = sec_meta.overview(c)
        conf = sec_predict.confusion(c)
        cal = sec_predict.calibration(c)
        roll = sec_predict.rolling(c)
        test_conf = (conf.get("splits") or {}).get("test") or {}
        test_cal = ((cal.get("splits") or {}).get("test") or {}).get("quantile")
        runs.append({
            "run_id": c.fr.run["run_id"], "name": ov["run"]["name"], "target": c.fr.run["target"], "horizon": c.fr.horizon,
            "algo": c.fr.trial["algo"], "n_features": c.fr.trial["n_features"], "scheme": ov["scheme"], "started_at": c.fr.run["started_at"],
            "headline": ov["headline"], "has_levels": ov["has_levels"],
            "rolling": ({"t": roll["t"], "acc": roll["acc"], "lo": roll["lo"], "hi": roll["hi"], "window": roll["window"]} if roll.get("available") else None),
            "equity": _equity_overlay(c, cost_bps),
            "reliability": test_cal["bins"] if test_cal else None,
            "roc": ({"fpr": test_conf["roc"]["fpr"], "tpr": test_conf["roc"]["tpr"], "auc": test_conf["roc"]["auc"]} if test_conf.get("roc") else None),
            "folds": [{"fold": f["fold"], "split": f["split"], "acc": f["acc"], "base_up": f["base_up"], "n": f["n"]} for f in (conf.get("by_fold") or [])],
        })
    names = [r["name"] for r in runs]
    return sc.jsonable({"runs": runs, "dm": dm_matrix(ctxs, names), "config_diff": config_diff([c.fr.config for c in ctxs]), "cost_bps": cost_bps,
                        "same_target": len({(c.fr.run["target"], c.fr.horizon) for c in ctxs}) == 1})
