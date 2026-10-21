"""Tests de robustesse sur les prédictions stockées (aucun ré-entraînement) et lecture guidée d'un run.

Ce qui se teste ici sans refaire un modèle : le hasard (permutation par blocs), l'incertitude (bootstrap par blocs), l'alignement dans
le temps (décalage des prédictions), la stabilité (sous-échantillons par pli, par moitié, par année). Ce qui exige de ré-entraîner
(ablation par famille de variables, sensibilité aux hyperparamètres) n'est pas calculé à l'ouverture d'une page : c'est une tâche à mettre
en file."""
from __future__ import annotations

import numpy as np
import pandas as pd

from patrick.analysis import sec_perf, sec_predict
from patrick.analysis import stats_core as sc
from patrick.analysis.context import Ctx

MAX_PERM = 2000
MAX_BOOT = 1000


def _acc(t, p) -> float:
    return float((np.asarray(t) == np.asarray(p)).mean()) if len(t) else float("nan")


def _bal(t, p) -> float | None:
    s = sc.binary_scores(np.asarray(t, dtype=bool), np.asarray(p, dtype=bool))
    return s["bal_acc"]


def _auc(y, s) -> float | None:
    return sc.auc(y, s)


def _chance_acc(share_up: float, share_pred_up: float) -> float:
    """Exactitude attendue d'un signal sans lien avec la réalité qui annonce « hausse » aussi souvent que le modèle."""
    return share_pred_up * share_up + (1 - share_pred_up) * (1 - share_up)


def _block_p(k: int, n: int, p0: float, h: int) -> float | None:
    """p-value binomiale unilatérale avec effectif réduit : à horizon `h`, deux dates voisines partagent des rendements, donc
    ~n/h observations indépendantes. Le test garde la même proportion observée sur cet effectif réduit."""
    if n <= 0:
        return None
    n_eff = max(1, round(n / max(1, h)))
    k_eff = round(k / n * n_eff)
    return sc.binom_p_greater(k_eff, n_eff, p0)


def _one_sample(d: pd.DataFrame, h: int, block: int, n_perm: int, n_boot: int, seed: int) -> dict:
    ut = d["ut"].to_numpy(dtype=float) >= 0.5
    up = d["up"].to_numpy(dtype=bool)
    n = len(d)
    k = int((ut == up).sum())
    share_up = float(ut.mean())
    maj = max(share_up, 1 - share_up)
    p = d["p_up"].to_numpy(dtype=float)
    ok = np.isfinite(p)
    out = {
        "n": n, "acc": k / n, "majority": maj, "chance": _chance_acc(share_up, float(up.mean())),
        "binom_p_naive": sc.binom_p_greater(k, n, maj), "binom_p_blocks": _block_p(k, n, maj, h),
        "perm_acc": sc.permutation_test(_acc, ut, up, block=block, n_perm=n_perm, seed=seed),
        "perm_bal": sc.permutation_test(lambda a, b: _bal(a, b) or float("nan"), ut, up, block=block, n_perm=n_perm, seed=seed + 1),
        "boot_acc": sc.block_bootstrap(_acc, (ut, up), block=block, n_boot=n_boot, seed=seed + 2),
        "boot_bal": sc.block_bootstrap(lambda a, b: _bal(a, b) or float("nan"), (ut, up), block=block, n_boot=n_boot, seed=seed + 3),
        "boot_auc": (sc.block_bootstrap(lambda a, b: _auc(a, b) or float("nan"), (ut[ok], p[ok]), block=block, n_boot=n_boot, seed=seed + 4)
                     if ok.sum() >= 60 else None),
        "shift": sc.shift_curve(ut, up, 10),
    }
    return out


def robustness(ctx: Ctx) -> dict:
    """Permutation, bootstrap, décalage temporel et stabilité des prédictions test / holdout.

    Paramètres : `n_perm` (500), `n_boot` (300), `block` (par défaut l'horizon, au moins 5 pour le bootstrap)."""
    fr = ctx.fr
    d = ctx.evaluated(("test", "holdout"))
    if len(d) < 60:
        return {"available": False, "reason": "not_enough"}
    n_perm = ctx.int_param("n_perm", 500, lo=50, hi=MAX_PERM)
    n_boot = ctx.int_param("n_boot", 300, lo=50, hi=MAX_BOOT)
    h = max(1, fr.horizon)
    block = ctx.int_param("block", h, lo=1, hi=250)
    boot_block = max(block, 5)
    samples = {}
    for name in ("test", "holdout"):
        g = d[d["split_name"] == name]
        if len(g) >= 30:
            samples[name] = _one_sample(g, h, block, n_perm, n_boot, seed=11)
    # sous-échantillons du test : un pli en moins, deux moitiés, une année après l'autre
    t = d[d["split_name"] == "test"]
    stability: dict = {"leave_one_fold_out": [], "halves": [], "years": []}
    if len(t) >= 60:
        ut_all, up_all = t["ut"].to_numpy(dtype=float) >= 0.5, t["up"].to_numpy(dtype=bool)
        full_acc = _acc(ut_all, up_all)
        for fold in sorted(t["fold"].unique()):
            rest = t[t["fold"] != fold]
            if len(rest) >= 30:
                stability["leave_one_fold_out"].append({"fold": int(fold), "acc": _acc(rest["ut"] >= 0.5, rest["up"]), "n": len(rest)})
        mid = len(t) // 2
        for label, g in (("first", t.iloc[:mid]), ("second", t.iloc[mid:])):
            if len(g) >= 30:
                stability["halves"].append({"half": label, "acc": _acc(g["ut"] >= 0.5, g["up"]), "n": len(g),
                                            "majority": max(float((g["ut"] >= 0.5).mean()), 1 - float((g["ut"] >= 0.5).mean()))})
        beat, tested = 0, 0
        for year, g in t.groupby(t["ts"].dt.year):
            if len(g) < 30:
                continue
            gt, gp = g["ut"].to_numpy(dtype=float) >= 0.5, g["up"].to_numpy(dtype=bool)
            maj = max(float(gt.mean()), 1 - float(gt.mean()))
            stability["years"].append({"year": int(year), "acc": _acc(gt, gp), "majority": maj, "n": len(g)})
            tested += 1
            beat += int(_acc(gt, gp) > maj)
        stability["share_years_beating"] = (beat / tested) if tested else None
        stability["full_acc"] = full_acc
    return {"available": True, "samples": samples, "stability": stability, "params": {"n_perm": n_perm, "n_boot": n_boot, "block": block,
            "boot_block": boot_block, "horizon": h}, "requires_retraining": ["ablation_by_family", "hyperparameter_sensitivity"]}


# ------------------------------------------------------------------------------------------------------------ lecture
def _item(level: str, key: str, **params) -> dict:
    return {"level": level, "key": key, "params": {k: (None if (isinstance(v, float) and not np.isfinite(v)) else v)
                                                      for k, v in params.items()}}


def guide(ctx: Ctx) -> dict:
    """Lecture guidée : des constats chiffrés tirés des sections, du plus important au détail. Jamais de recommandation d'achat ou de
    vente : ce sont des constats de méthode (« le modèle bat-il le côté majoritaire ? », « les probabilités sont-elles fiables ? »)."""
    fr = ctx.fr
    d = ctx.evaluated(("test", "holdout"))
    items: list[dict] = []
    if len(d) < 30:
        return {"available": False, "reason": "not_enough"}
    h = max(1, fr.horizon)
    test = d[d["split_name"] == "test"]
    hold = d[d["split_name"] == "holdout"]
    tests = {}
    for name, g in (("test", test), ("holdout", hold)):
        if len(g) >= 30:
            ut, up = g["ut"].to_numpy(dtype=float) >= 0.5, g["up"].to_numpy(dtype=bool)
            k = int((ut == up).sum())
            maj = max(float(ut.mean()), 1 - float(ut.mean()))
            lo, hi = sc.wilson(k, len(g))
            tests[name] = {"acc": k / len(g), "maj": maj, "lo": lo, "hi": hi, "n": len(g), "p": _block_p(k, len(g), maj, h),
                           "share_pred_up": float(up.mean()), "share_up": float(ut.mean())}
    if "test" in tests:
        t = tests["test"]
        beats = t["acc"] > t["maj"] and t["p"] is not None and t["p"] < 0.05
        items.append(_item("ok" if beats else "warn", "acc_vs_majority", acc=t["acc"], maj=t["maj"], edge=t["acc"] - t["maj"], lo=t["lo"],
                           hi=t["hi"], n=t["n"], p=t["p"], h=h))
        if t["share_pred_up"] > 0.7 or t["share_pred_up"] < 0.3:
            items.append(_item("warn", "one_sided", share=t["share_pred_up"], base=t["share_up"]))
    if "test" in tests and "holdout" in tests:
        drop = tests["holdout"]["acc"] - tests["test"]["acc"]
        items.append(_item("warn" if drop < -0.05 else "ok", "holdout_drop", test=tests["test"]["acc"], holdout=tests["holdout"]["acc"],
                           drop=drop, n=tests["holdout"]["n"], lo=tests["holdout"]["lo"], hi=tests["holdout"]["hi"]))
    p = d["p_up"].to_numpy(dtype=float)
    ok = np.isfinite(p)
    if ok.sum() >= 60:
        a = sc.auc(d["ut"].to_numpy(dtype=float)[ok] >= 0.5, p[ok])
        if a is not None:
            items.append(_item("ok" if a >= 0.55 else ("warn" if a < 0.52 else "info"), "auc", auc=a))
        rel = sc.reliability(p[ok], d["ut"].to_numpy(dtype=float)[ok], 10)
        if rel["ece"] is not None:
            items.append(_item("warn" if rel["ece"] > 0.08 else "ok", "calibration", ece=rel["ece"], brier=rel["brier"],
                               base_brier=rel["uncertainty"]))
    # plis : combien battent la base de leur propre échantillon
    n_fold, n_beat, worst = 0, 0, None
    for _, g in test.groupby("fold"):
        if len(g) < 30:
            continue
        ut, up = g["ut"].to_numpy(dtype=float) >= 0.5, g["up"].to_numpy(dtype=bool)
        maj = max(float(ut.mean()), 1 - float(ut.mean()))
        acc = _acc(ut, up)
        n_fold += 1
        n_beat += int(acc > maj)
        worst = acc if worst is None else min(worst, acc)
    if n_fold >= 2:
        items.append(_item("ok" if n_beat == n_fold else ("warn" if n_beat <= n_fold / 2 else "info"), "folds", beat=n_beat, n_folds=n_fold,
                           worst=worst))
    sc_res = sec_predict.scatter(ctx)
    if sc_res.get("available") and sc_res["ic"]["rho"] is not None:
        rho, pv = sc_res["ic"]["rho"], sc_res["ic"]["p"]
        items.append(_item("ok" if (pv is not None and pv < 0.05 and rho > 0) else "info", "ic", rho=rho, p=pv, n=sc_res["ic"]["n"],
                           spread=sc_res.get("spread_top_bottom")))
    eq = sec_perf.equity(ctx)
    if eq.get("available"):
        s = eq["stats"]
        ls, bh = s["long_short"]["all"], s["buy_hold"]["all"]
        dsr = eq.get("dsr") or {}
        dsr_p = dsr.get("p_value")
        items.append(_item("info", "equity", sharpe=ls["sharpe"], bh_sharpe=bh["sharpe"], max_dd=ls["max_dd"], bh_dd=bh["max_dd"],
                           ret=ls["total"], bh_ret=bh["total"], cost=eq["cost_bps"]))
        if dsr_p is not None and not (isinstance(dsr_p, float) and np.isnan(dsr_p)):
            items.append(_item("ok" if dsr_p < 0.1 else "warn", "dsr", dsr=dsr.get("dsr"), p=dsr_p, n_trials=eq["n_trials"]))
    from patrick.tracking import stats as trackstats
    n_trials = trackstats.count_cumulative_trials(ctx.conn, fr.run["target"], fr.horizon)
    items.append(_item("info", "trials", n=int(n_trials)))
    if "test" in tests and tests["test"]["acc"] > 0.70:
        items.append(_item("warn", "too_good", acc=tests["test"]["acc"]))
    for note in fr.notes:
        items.append(_item("info", "note", text=note))
    order = {"warn": 0, "ok": 1, "info": 2}
    items.sort(key=lambda i: order[i["level"]])
    return {"available": True, "items": items}
