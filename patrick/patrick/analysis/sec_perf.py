"""Sections de performance : stratégie simulée (équité, drawdown, coûts) et analyse d'erreurs (régimes, calendrier, confiance).

La stratégie est un outil de LECTURE, pas une recommandation : elle applique mécaniquement le signal du modèle aux rendements réalisés,
sans autre règle. À horizon `h` > 1 les paris se chevauchent : le portefeuille tient `h` tranches de `1/h`, chacune ouverte à la clôture
de la date du signal et gardée `h` barres (même convention que les simulations de `simulate/`). Les coûts sont linéaires en turnover."""
from __future__ import annotations

import numpy as np
import pandas as pd

from patrick.analysis import stats_core as sc
from patrick.analysis.context import Ctx, iso

DEFAULT_COST_BPS = 5.0
STRATEGIES = ("long_short", "long_flat", "buy_hold")
MIN_GROUP = 5


# --------------------------------------------------------------------------------------------------------------- équité
def _tranche(position: pd.Series, h: int) -> pd.Series:
    """Exposition du portefeuille de `h` tranches : moyenne des `h` positions des barres précédentes (décalées de 1..h)."""
    acc = pd.Series(0.0, index=position.index)
    for k in range(1, h + 1):
        acc = acc.add(position.shift(k).fillna(0.0), fill_value=0.0)
    return acc / h


def build_strategies(fr, d: pd.DataFrame) -> dict | None:
    """Rendements bruts et turnover quotidiens des trois stratégies sur la période prédite ; `None` si le niveau manque."""
    if fr.levels is None or fr.daily is None or d.empty:
        return None
    lv_idx = fr.levels.index
    d = d[d["ts"].isin(lv_idx)].drop_duplicates("ts", keep="last")
    if d.empty:
        return None
    h = max(1, fr.horizon)
    pos = pd.Series(np.nan, index=lv_idx)
    pos.loc[d["ts"].to_numpy()] = np.where(d["up"].to_numpy(dtype=bool), 1.0, -1.0)
    i0 = lv_idx.get_loc(pos.first_valid_index())
    i1 = min(len(lv_idx) - 1, lv_idx.get_loc(pos.last_valid_index()) + h)
    pos_w = pos.iloc[i0:i1 + 1].ffill()
    daily = fr.daily.iloc[i0:i1 + 1].fillna(0.0)
    e_ls = _tranche(pos_w, h)
    e_lf = _tranche((pos_w > 0).astype(float), h)
    out = {"dates": daily.index, "daily": daily, "i0": i0, "i1": i1}
    for name, e in (("long_short", e_ls), ("long_flat", e_lf)):
        turn = e.diff().abs()
        turn.iloc[0] = abs(e.iloc[0])
        out[name] = {"gross": e * daily, "turn": turn, "exposure": e}
    out["buy_hold"] = {"gross": daily, "turn": pd.Series(0.0, index=daily.index), "exposure": pd.Series(1.0, index=daily.index)}
    return out


def _net(s: dict, cost_bps: float) -> pd.Series:
    return s["gross"] - s["turn"] * cost_bps * 1e-4


def equity(ctx: Ctx) -> dict:
    fr = ctx.fr
    if fr.levels is None or fr.daily is None:
        return {"available": False, "reason": "no_returns"}
    d = ctx.one_path(fr.df[fr.df["split_name"].isin(["test", "holdout", "live"])]).sort_values("ts", kind="mergesort")
    strat = build_strategies(fr, d)
    if strat is None:
        return {"available": False, "reason": "no_returns"}
    cost = ctx.float_param("cost_bps", DEFAULT_COST_BPS, lo=0.0, hi=500.0)
    dates = strat["dates"]
    spans = {}
    for name in ("test", "holdout", "live"):
        g = d[d["split_name"] == name]
        if len(g):
            spans[name] = (g["ts"].min(), g["ts"].max())

    def window(series: pd.Series, name: str) -> pd.Series:
        if name == "all":
            return series
        a, b = spans[name]
        return series[(series.index >= a) & (series.index <= b + pd.Timedelta(days=int(fr.horizon * 1.6) + 1))]

    stats = {}
    for s in STRATEGIES:
        net = _net(strat[s], cost)
        stats[s] = {"all": sc.performance_summary(net.to_numpy())}
        for name in spans:
            stats[s][name] = sc.performance_summary(window(net, name).to_numpy())
        e = strat[s]["exposure"]
        years = max(len(e) / 252.0, 1e-9)
        stats[s]["exposure"] = {"mean_abs": float(e.abs().mean()), "share_long": float((e > 0.05).mean()),
                                "share_short": float((e < -0.05).mean()), "turnover_per_year": float(strat[s]["turn"].sum() / years)}
    from patrick.tracking import stats as trackstats
    n_trials = trackstats.count_cumulative_trials(ctx.conn, fr.run["target"], fr.horizon)
    dsr = None
    try:
        from patrick.validation.dsr import deflated_sharpe_ratio
        dsr = deflated_sharpe_ratio(_net(strat["long_short"], cost).to_numpy(), max(1, n_trials))
    except (ValueError, ImportError, FloatingPointError):
        dsr = None
    net_ls = _net(strat["long_short"], cost)
    monthly = (1.0 + net_ls).groupby([net_ls.index.year, net_ls.index.month]).prod() - 1.0
    months = [{"y": int(y), "m": int(m), "r": float(v)} for (y, m), v in monthly.items()]
    fold_marks = []
    for (split, fold), g in d.groupby(["split_name", "fold"]):
        fold_marks.append({"fold": int(fold), "split": split, "start": iso(g["ts"].min())})
    fold_marks.sort(key=lambda f: f["start"])
    series = {s: {"gross": np.round(strat[s]["gross"].to_numpy(), 6), "turn": np.round(strat[s]["turn"].to_numpy(), 5)}
              for s in STRATEGIES}
    return {"available": True, "dates": [iso(t) for t in dates], "series": series, "cost_bps": cost, "stats": stats,
            "horizon": fr.horizon, "is_alpha": fr.is_alpha, "folds": fold_marks,
            "holdout_start": iso(spans["holdout"][0]) if "holdout" in spans else None,
            "live_start": iso(spans["live"][0]) if "live" in spans else None, "months": months,
            "dsr": dsr, "n_trials": int(n_trials), "n_missing_levels": int((~d["ts"].isin(fr.levels.index)).sum())}


# ------------------------------------------------------------------------------------------------------------- erreurs
def _group_table(d: pd.DataFrame, col: str, order: list | None = None) -> list[dict]:
    rows = []
    for key, g in d.groupby(col, sort=True, observed=True):
        n = len(g)
        if n < MIN_GROUP:
            continue
        ut = g["ut"].to_numpy(dtype=float) >= 0.5
        up = g["up"].to_numpy(dtype=bool)
        k = int((ut == up).sum())
        lo, hi = sc.wilson(k, n)
        share_true = float(ut.mean())
        base = max(share_true, 1 - share_true)
        bs = sc.binary_scores(ut, up)
        ret = g["ret"]
        rows.append({"key": key if not isinstance(key, (np.integer, np.floating)) else float(key), "n": int(n), "acc": k / n, "lo": lo,
                     "hi": hi, "base": base, "edge": k / n - base, "f1_dir": bs["f1_dir"], "share_pred_up": float(up.mean()),
                     "share_true_up": share_true,
                     "ret_if_up": float(ret[g["up"]].mean()) if ret[g["up"]].notna().any() else None,
                     "ret_if_down": float(ret[~g["up"]].mean()) if ret[~g["up"]].notna().any() else None})
    if order:
        pos = {k: i for i, k in enumerate(order)}
        rows.sort(key=lambda r: pos.get(r["key"], 99))
    return rows


def _regimes(fr, d: pd.DataFrame) -> pd.DataFrame:
    """Ajoute à `d` les colonnes de régime lues dans les niveaux (volatilité, tendance, baisse, momentum) : toutes connues à la date du
    signal (fenêtres passées seulement). Les terciles de volatilité sont ceux de l'échantillon analysé (lecture descriptive)."""
    d = d.copy()
    if fr.levels is None or fr.daily is None:
        return d
    lv = fr.levels.ffill()
    vol = fr.daily.rolling(20, min_periods=15).std() * np.sqrt(252)
    ma200 = lv.rolling(200, min_periods=150).mean()
    peak = lv.rolling(252, min_periods=60).max()
    mom = lv / lv.shift(20) - 1.0
    d["vol_raw"] = d["ts"].map(vol)
    q = d["vol_raw"].quantile([1 / 3, 2 / 3])
    d["vol"] = np.where(d["vol_raw"].isna(), None, np.where(d["vol_raw"] <= q.iloc[0], "vol_low",
                                                              np.where(d["vol_raw"] <= q.iloc[1], "vol_mid", "vol_high")))
    t = d["ts"].map(lv - ma200)
    d["trend"] = np.where(t.isna(), None, np.where(t >= 0, "trend_up", "trend_down"))
    dd = d["ts"].map(lv / peak - 1.0)
    d["dd"] = np.where(dd.isna(), None, np.where(dd < -0.10, "dd_stress", "dd_normal"))
    m = d["ts"].map(mom)
    d["mom"] = np.where(m.isna(), None, np.where(m >= 0, "mom_up", "mom_down"))
    return d


def errors(ctx: Ctx) -> dict:
    """Où le modèle se trompe : exactitude par pli, année, mois, jour de semaine, régime de volatilité / tendance / baisse / momentum,
    niveau de confiance, décile de P(hausse), classe prédite et réelle ; séries d'erreurs ; meilleurs et pires mois."""
    fr = ctx.fr
    d = ctx.evaluated(("test", "holdout"))
    if len(d) < 30:
        return {"available": False, "reason": "not_enough"}
    d = _regimes(fr, d)
    d["year"] = d["ts"].dt.year
    d["month"] = d["ts"].dt.month
    d["weekday"] = d["ts"].dt.weekday
    d["fold_label"] = d["split_name"] + ":" + d["fold"].astype(str)
    conf = d["conf"]
    if conf.notna().sum() >= 50:
        d["conf_q"] = pd.qcut(conf.rank(method="first"), 5, labels=["Q1", "Q2", "Q3", "Q4", "Q5"])
    p = d["p_up"]
    if p.notna().sum() >= 100:
        d["pup_d"] = pd.qcut(p.rank(method="first"), 10, labels=[f"D{i}" for i in range(1, 11)])
    d["yp_i"] = d["yp"].astype(int)
    d["yt_i"] = d["yt"].fillna(-1).astype(int)
    tables: dict = {
        "fold": _group_table(d, "fold_label"), "year": _group_table(d, "year"), "month": _group_table(d, "month"),
        "weekday": _group_table(d, "weekday"),
        "pred_class": _group_table(d, "yp_i"), "true_class": _group_table(d[d["yt_i"] >= 0], "yt_i"),
    }
    for col, order in (("vol", ["vol_low", "vol_mid", "vol_high"]), ("trend", ["trend_up", "trend_down"]),
                       ("dd", ["dd_normal", "dd_stress"]), ("mom", ["mom_up", "mom_down"])):
        if col in d.columns:
            tables[col] = _group_table(d[d[col].notna()], col, order)
    if "conf_q" in d.columns:
        tables["conf"] = _group_table(d[d["conf_q"].notna()], "conf_q", ["Q1", "Q2", "Q3", "Q4", "Q5"])
    if "pup_d" in d.columns:
        tables["pup"] = _group_table(d[d["pup_d"].notna()], "pup_d", [f"D{i}" for i in range(1, 11)])
    ut, up = d["ut"].to_numpy(dtype=float) >= 0.5, d["up"].to_numpy(dtype=bool)
    wrong = ut != up
    ts = d["ts"].to_numpy()
    streaks = [{"start": iso(ts[r["start"]]), "end": iso(ts[r["end"]]), "length": r["length"]} for r in sc.longest_runs(wrong, 5)]
    ym = d.assign(ym=d["ts"].dt.strftime("%Y-%m")).groupby("ym")
    months = []
    for key, g in ym:
        if len(g) >= 10:
            months.append({"ym": key, "n": len(g), "acc": float((g["ut"].to_numpy(dtype=float) >= 0.5).__eq__(g["up"].to_numpy(dtype=bool)).mean())})
    months.sort(key=lambda r: r["acc"])
    return {"available": True, "n": len(d), "tables": tables, "streaks": streaks, "worst_months": months[:6],
            "best_months": months[-6:][::-1], "has_regimes": fr.levels is not None,
            "overall_error_rate": float(wrong.mean())}
