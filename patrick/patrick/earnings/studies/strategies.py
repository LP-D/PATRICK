"""Tradabilité (§3.K) : trois stratégies de référence, jamais présumées rentables.

- run-up : position prise AVANT l'annonce, sortie avant la réaction ;
- drift : entrée à l'ouverture de J0+k (k = 1 ou 2) selon la surprise ou la réaction, sortie après h séances ;
- fade : pari sur le retournement d'une réaction extrême, entrée à l'ouverture suivante.

Contraintes d'évaluation, toutes appliquées :
- ENTRÉE À L'OUVERTURE SUIVANTE : jamais à la clôture du jour de l'annonce (un titre qui publie après la clôture a déjà gappé à
  l'ouverture ; on mesure donc depuis l'ouverture, ce qui est le premier prix réellement exécutable) ;
- coûts de transaction par côté + slippage proportionnel au gap d'entrée (les gaps d'ouverture sont les moments de slippage maximal) ;
- chaque stratégie est testée sur une GRILLE de paramètres : le nombre d'essais est déclaré à la DSR (Sharpe corrigé du nombre d'essais)
  et à la PBO (probabilité de surajustement du backtest, sur des blocs de temps) du projet ;
- HOLDOUT TERMINAL préservé : la configuration est CHOISIE sur les événements antérieurs au holdout (Sharpe d'entraînement) et jugée sur
  le holdout, jamais l'inverse.
Une transaction = une unité de capital. Les transactions entrées la même semaine forment une cohorte (rendement moyen) : Sharpe, DSR et
perte maximale se lisent sur les cohortes, car des annonces d'une même semaine partagent les chocs de marché. Pas de capitalisation sur des
positions qui se chevauchent : l'équité est la somme des rendements de cohortes.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from patrick.earnings.studies.base import (
    Ctx,
    Param,
    insufficient,
    kv,
    line,
    note,
    ok,
    study,
    table,
)
from patrick.validation.dsr import deflated_sharpe_ratio
from patrick.validation.pbo import compute_pbo

MIN_TRADES = 30
COMMON = (Param("cost_bps", "float", 5.0, "Coût par côté (points de base)", lo=0, hi=100),
          Param("slip_gap", "float", 0.10, "Slippage (part du gap d'entrée)", lo=0, hi=1),
          Param("holdout_months", "int", 15, "Holdout terminal (mois)", lo=3, hi=60))


@dataclass
class Trade:
    symbol: str
    entry: pd.Timestamp
    exit: pd.Timestamp
    gross: float
    net: float
    day0: pd.Timestamp


def _sessions(ctx: Ctx, symbol: str):
    px = ctx.prices.raw(symbol)
    if px is None or len(px) < 100:
        return None
    return px


def make_trade(px: pd.DataFrame, day0: pd.Timestamp, entry_off: int, exit_off: int, direction: float, cost_bps: float, slip_gap: float,
               entry_at: str = "open", exit_at: str = "close") -> Trade | None:
    """Entrée à `entry_off` séances de J0 (ouverture ou clôture), sortie à `exit_off`. Net = brut - 2 coûts - slippage x |gap d'entrée|."""
    idx = px.index
    if day0 not in idx:
        return None
    i0 = int(idx.get_loc(day0))
    ie, ix = i0 + entry_off, i0 + exit_off
    if ie < 1 or ix >= len(idx) or ix < ie:
        return None
    entry = float(px["Open"].iloc[ie] if entry_at == "open" else px["Close"].iloc[ie])
    exit_ = float(px["Close"].iloc[ix] if exit_at == "close" else px["Open"].iloc[ix])
    if not (entry > 0 and exit_ > 0):
        return None
    gross = direction * (exit_ / entry - 1)
    prev_close = float(px["Close"].iloc[ie - 1])
    gap = abs(entry / prev_close - 1) if entry_at == "open" and prev_close > 0 else 0.0
    net = gross - 2 * cost_bps / 1e4 - slip_gap * gap
    return Trade("", idx[ie], idx[ix], gross, net, day0)


def stats_of(trades: list[Trade], n_trials: int) -> dict:
    """Statistiques d'une liste de transactions. Les transactions ouvertes la même semaine partagent les chocs de marché : le Sharpe, la
    DSR et la perte maximale se calculent sur des COHORTES (moyenne des rendements nets des transactions entrées la même semaine), pas
    sur des transactions supposées indépendantes, ce qui les gonflerait."""
    if not trades:
        return {"n": 0}
    t = sorted(trades, key=lambda x: x.entry)
    net = np.array([x.net for x in t])
    frame = pd.DataFrame({"week": [x.entry.strftime("%G-W%V") for x in t], "net": net, "exit": [x.exit for x in t]})
    cohort = frame.groupby("week").agg(net=("net", "mean"), exit=("exit", "max")).sort_values("exit")
    c = cohort["net"].to_numpy()
    span = max((t[-1].exit - t[0].entry).days / 365.25, 0.25)
    per_year = max(len(c) / span, 1)
    sd = c.std(ddof=1) if len(c) > 1 else np.nan
    eq = np.cumsum(c)
    d = deflated_sharpe_ratio(c, n_trials=n_trials, periods_per_year=round(per_year)) if len(c) >= 20 else {}
    return {"n": len(net), "n_cohorts": len(c), "mean": float(net.mean()), "hit": float((net > 0).mean()),
            "sharpe": float(c.mean() / sd * np.sqrt(per_year)) if sd and sd > 0 else np.nan, "max_dd": float((eq - np.maximum.accumulate(eq)).min()),
            "total": float(c.sum()), "dsr_p": d.get("p_value"), "per_year": per_year, "equity": eq.tolist(), "dates": list(cohort["exit"])}


def evaluate_grid(trades_by_cfg: dict[str, list[Trade]], holdout_start: pd.Timestamp, n_trials: int) -> dict:
    """Choix sur l'entraînement (avant le holdout), jugement sur le holdout, PBO sur blocs de temps."""
    rows, train_sharpe = [], {}
    for name, tr in trades_by_cfg.items():
        train = [x for x in tr if x.day0 < holdout_start]
        hold = [x for x in tr if x.day0 >= holdout_start]
        s_tr, s_ho = stats_of(train, n_trials), stats_of(hold, n_trials)
        train_sharpe[name] = s_tr.get("sharpe", np.nan) if s_tr.get("n", 0) >= 10 else np.nan
        rows.append((name, s_tr, s_ho, stats_of(tr, n_trials)))
    valid = {k: v for k, v in train_sharpe.items() if np.isfinite(v)}
    chosen = max(valid, key=valid.get) if valid else None
    # PBO : matrice (configurations x blocs de temps) du rendement moyen net
    all_days = sorted({x.day0 for tr in trades_by_cfg.values() for x in tr})
    pbo = None
    if len(all_days) >= 40 and len(trades_by_cfg) >= 3:
        edges = np.array_split(np.array(all_days, dtype="datetime64[ns]"), 8)
        mat = np.full((len(trades_by_cfg), 8), np.nan)
        for r, tr in enumerate(trades_by_cfg.values()):
            for b, blk in enumerate(edges):
                lo, hi = blk.min(), blk.max()
                vals = [x.net for x in tr if lo <= np.datetime64(x.day0) <= hi]
                if vals:
                    mat[r, b] = np.mean(vals)
        mat = np.where(np.isfinite(mat), mat, 0.0)
        pbo = compute_pbo(mat)
    return {"rows": rows, "chosen": chosen, "pbo": pbo, "n_trials": n_trials}


def _render(ctx: Ctx, title: str, res: dict, n_events: int, grid_label: str) -> dict:
    rows = []
    for name, s_tr, s_ho, s_all in res["rows"]:
        mark = " ◀ choisie" if name == res["chosen"] else ""
        rows.append([name + mark, s_all.get("n", 0), s_tr.get("sharpe"), s_ho.get("n", 0), s_ho.get("mean"), s_ho.get("hit"), s_ho.get("sharpe"), s_ho.get("max_dd"),
                     s_ho.get("dsr_p")])
    blocks = [table(f"{title} : {grid_label}", ["Configuration", "Transactions", "Sharpe (entraînement)", "Holdout : N", "Holdout : gain net moyen", "Holdout : taux de gain",
                                                  "Holdout : Sharpe", "Holdout : perte max", "p (DSR holdout)"], rows,
                     ["str", "int", "num2", "int", "pct", "pct0", "num2", "pct", "p"], n_col=1,
                     note=f"{res['n_trials']} configurations testées (comptées dans la DSR). Entrée à l'ouverture suivante, coûts et slippage inclus.")]
    chosen = next((r for r in res["rows"] if r[0] == res["chosen"]), None)
    if chosen and chosen[3].get("equity"):
        s = chosen[3]
        blocks.append(line("Somme cumulée des rendements nets de la configuration choisie (toute la période)", [str(d.date()) for d in s["dates"]],
                           [{"name": "somme cumulée", "y": s["equity"]}], "date de sortie", "pct"))
    if res["pbo"] and np.isfinite(res["pbo"].get("pbo", np.nan)):
        blocks.append(kv("Surajustement", [("PBO (probabilité de surajustement)", res["pbo"]["pbo"], "pct0"), ("Configurations", res["pbo"]["n_trials"], "int"),
                                           ("Blocs de temps", res["pbo"]["n_blocks"], "int")]))
    blocks.append(note("Hypothèse à tester, pas un signal : un holdout positif avec une DSR élevée et une PBO basse serait un indice, pas une preuve. "
                       "Un Sharpe d'entraînement flatteur sans holdout équivalent est du surajustement."))
    pv = {f"k.{title}.holdout_dsr": chosen[2].get("dsr_p")} if chosen and chosen[2].get("dsr_p") is not None else {}
    return ok(blocks, n_events, pvalues=pv)


def _holdout_start(df: pd.DataFrame, months: int) -> pd.Timestamp:
    return df["day0"].max() - pd.DateOffset(months=months)


@study("k_strategy_runup", "K", "Stratégie run-up", "Position avant l'annonce, sortie avant la réaction (dernière séance avant J0).",
       needs=("prices",), heavy=True, params=COMMON)
def k_strategy_runup(ctx: Ctx, p: dict) -> dict:
    df = ctx.full.frame
    if len(df) < MIN_TRADES:
        return insufficient(len(df), MIN_TRADES)
    cfgs = {f"achat à J0−{k}, sortie J0−1 (long)": (k, 1.0) for k in (3, 5, 10)}
    cfgs.update({f"vente à découvert à J0−{k}, sortie J0−1": (k, -1.0) for k in (3, 5, 10)})
    trades = {name: [] for name in cfgs}
    for sym, g in df.groupby("symbol"):
        px = _sessions(ctx, sym)
        if px is None:
            continue
        for day0 in g["day0"]:
            for name, (k, d) in cfgs.items():
                t = make_trade(px, day0, -k, -1, d, p["cost_bps"], p["slip_gap"], entry_at="open", exit_at="close")
                if t:
                    t.symbol = sym
                    trades[name].append(t)
    res = evaluate_grid(trades, _holdout_start(df, p["holdout_months"]), len(cfgs))
    return _render(ctx, "Run-up", res, len(df), "entrer k séances avant J0 à l'ouverture, sortir à la clôture de J0−1")


@study("k_strategy_drift", "K", "Stratégie de dérive (drift)",
       "Entrée à l'ouverture de J0+k selon le sens de la surprise ou de la réaction, sortie après h séances.", needs=("prices",), heavy=True, params=COMMON)
def k_strategy_drift(ctx: Ctx, p: dict) -> dict:
    df = ctx.full.frame.dropna(subset=["car"])
    if len(df) < MIN_TRADES:
        return insufficient(len(df), MIN_TRADES)
    cfgs = {}
    for signal in ("surprise", "réaction"):
        for k in (1, 2):
            for h in (5, 20, 60):
                cfgs[f"{signal} · entrée J0+{k} · tenue {h} séances"] = (signal, k, h)
    trades = {name: [] for name in cfgs}
    for sym, g in df.groupby("symbol"):
        px = _sessions(ctx, sym)
        if px is None:
            continue
        for r in g.itertuples():
            for name, (signal, k, h) in cfgs.items():
                sign = np.sign(r.surprise_pct) if signal == "surprise" else np.sign(r.car)
                if not sign or not np.isfinite(sign):
                    continue
                t = make_trade(px, r.day0, k, k + h - 1, float(sign), p["cost_bps"], p["slip_gap"], entry_at="open", exit_at="close")
                if t:
                    t.symbol = sym
                    trades[name].append(t)
    res = evaluate_grid(trades, _holdout_start(df, p["holdout_months"]), len(cfgs))
    return _render(ctx, "Dérive", res, len(df), "suivre le sens de la surprise de BPA ou de la réaction")


@study("k_strategy_fade", "K", "Stratégie de retournement (fade)",
       "Pari contre une réaction extrême, entrée à l'ouverture suivante.", needs=("prices",), heavy=True, params=COMMON)
def k_strategy_fade(ctx: Ctx, p: dict) -> dict:
    df = ctx.full.frame.dropna(subset=["car", "z_abs"])
    if len(df) < MIN_TRADES:
        return insufficient(len(df), MIN_TRADES)
    cfgs = {f"réaction > {thr:g}σ · tenue {h} séances": (thr, h) for thr in (2.0, 3.0) for h in (1, 3, 5)}
    trades = {name: [] for name in cfgs}
    for sym, g in df.groupby("symbol"):
        px = _sessions(ctx, sym)
        if px is None:
            continue
        for r in g.itertuples():
            for name, (thr, h) in cfgs.items():
                if r.z_abs <= thr:
                    continue
                t = make_trade(px, r.day0, 1, h, -float(np.sign(r.car)), p["cost_bps"], p["slip_gap"], entry_at="open", exit_at="close")
                if t:
                    t.symbol = sym
                    trades[name].append(t)
    res = evaluate_grid(trades, _holdout_start(df, p["holdout_months"]), len(cfgs))
    return _render(ctx, "Fade", res, len(df), "parier contre une réaction qui dépasse k écarts-types quotidiens")
