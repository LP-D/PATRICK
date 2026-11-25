"""Est-ce que la stratégie tient, ou est-ce un beau hasard ? Six épreuves, toutes calculées sur les rendements quotidiens du backtest.

1. Hors échantillon : les indicateurs avant et après une date de coupure choisie AVANT de regarder les résultats.
2. Hasard : la même exposition, instrument par instrument, décalée dans le temps (permutation circulaire des poids détenus) ; si des
   centaines de calendriers d'exposition au hasard font aussi bien, le choix des dates n'apporte rien. Valeur p = part des calendriers au
   hasard au moins aussi bons (Sharpe brut de frais, pour comparer à armes égales).
3. Frais : la courbe recalculée avec les frais multipliés par 0, ½, 1, 2, 3, 5, 10 ; le multiplicateur où le Sharpe tombe à zéro mesure la
   marge de sécurité (frais réels souvent plus élevés que prévu).
4. Rééchantillonnage : bootstrap par blocs stationnaires des rendements quotidiens (blocs de 20 séances en moyenne) : intervalle à 90 % du
   rendement annualisé, du Sharpe et du pire drawdown sur une période de même longueur.
5. Sharpe probabiliste et Sharpe déflaté (Bailey et López de Prado, 2014) : probabilité que le vrai Sharpe dépasse zéro, puis la même chose
   en tenant compte du nombre de variantes essayées (une grille de 100 réglages en trouve toujours une qui brille).
6. Walk-forward de la grille : chaque année, le réglage au meilleur Sharpe sur les années PRÉCÉDENTES seulement est appliqué l'année
   suivante. C'est la performance qu'aurait obtenue quelqu'un qui optimise honnêtement, sans connaître l'avenir.
"""
from __future__ import annotations

import itertools
import math

import numpy as np
import pandas as pd
from scipy.stats import norm

from patrick.strategylab import metrics

TD = 252
COST_MULTIPLIERS = (0.0, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0)


def _sharpe(r: np.ndarray, rf_daily: float = 0.0) -> float:
    sd = r.std(ddof=1) if len(r) > 1 else 0.0
    return float((r.mean() - rf_daily) / sd * math.sqrt(TD)) if sd > 0 else float("nan")


def split(ret: pd.Series, oos_start: pd.Timestamp | None, cash_rate: float) -> dict | None:
    if oos_start is None:
        return None
    oos_start = pd.Timestamp(oos_start)
    ins, oos = ret[ret.index < oos_start], ret[ret.index >= oos_start]
    if len(ins) < 60 or len(oos) < 60:
        return {"error": "Au moins 60 séances de chaque côté de la date de coupure sont nécessaires."}
    out = {}
    for name, part in (("in_sample", ins), ("out_of_sample", oos)):
        eq = (1 + part).cumprod()
        eq = pd.concat([pd.Series([1.0], index=[part.index[0] - pd.Timedelta(days=1)]), eq])
        out[name] = metrics.core(part, eq, cash_rate)
    si, so = out["in_sample"]["sharpe"], out["out_of_sample"]["sharpe"]
    out["ratio"] = float(so / si) if si and si > 0 and not math.isnan(so) else None
    out["oos_start"] = oos_start.date().isoformat()
    return out


def random_timing(weights: pd.DataFrame, returns: pd.DataFrame, n: int = 300, seed: int = 7, min_shift: int = 21) -> dict:
    W = weights.to_numpy(dtype=float)
    R = returns.reindex(weights.index).fillna(0.0).to_numpy(dtype=float)
    T, K = W.shape
    if T < 3 * min_shift or not np.abs(W).sum():
        return {"available": False}
    lagged = np.vstack([np.zeros((1, K)), W[:-1]])
    actual = _sharpe((lagged * R).sum(axis=1))
    rng = np.random.default_rng(seed)
    sims = np.empty(n)
    for i in range(n):
        shifted = np.empty_like(W)
        for k in range(K):
            shifted[:, k] = np.roll(W[:, k], int(rng.integers(min_shift, T - min_shift)))
        lag_s = np.vstack([np.zeros((1, K)), shifted[:-1]])
        sims[i] = _sharpe((lag_s * R).sum(axis=1))
    sims = sims[np.isfinite(sims)]
    if not len(sims) or not math.isfinite(actual):
        return {"available": False}
    counts, edges = np.histogram(sims, bins=24)
    return {"available": True, "actual": actual, "p_value": float((1 + (sims >= actual).sum()) / (len(sims) + 1)),
            "percentiles": {str(q): float(np.percentile(sims, q)) for q in (5, 25, 50, 75, 95)},
            "hist": {"counts": counts.tolist(), "edges": edges.tolist()}, "n": len(sims)}


def cost_sensitivity(ret_gross: pd.Series, cost_frac: pd.Series, cash_rate: float, bench_cagr: float | None = None) -> dict:
    """Rendements recalculés avec des frais multipliés : `net_k = brut - k x frais` (les ordres restent les mêmes, approximation au premier ordre)."""
    rows = []
    for k in COST_MULTIPLIERS:
        r = ret_gross - k * cost_frac
        eq = (1 + r).cumprod()
        rows.append({"mult": k, "cagr": metrics.cagr(pd.concat([pd.Series([1.0], index=[r.index[0] - pd.Timedelta(days=1)]), eq])),
                     "sharpe": _sharpe(r.to_numpy(), cash_rate / TD)})
    breakeven = None
    for a, b in itertools.pairwise(rows):
        if a["sharpe"] > 0 >= b["sharpe"]:
            breakeven = a["mult"] + (b["mult"] - a["mult"]) * a["sharpe"] / (a["sharpe"] - b["sharpe"])
            break
    if breakeven is None and rows[0]["sharpe"] <= 0:
        breakeven = 0.0
    beat = None
    if bench_cagr is not None:
        for a, b in itertools.pairwise(rows):
            if a["cagr"] > bench_cagr >= b["cagr"]:
                beat = a["mult"] + (b["mult"] - a["mult"]) * (a["cagr"] - bench_cagr) / (a["cagr"] - b["cagr"])
                break
        if beat is None and rows[0]["cagr"] <= bench_cagr:
            beat = 0.0
    return {"rows": rows, "breakeven_sharpe": breakeven, "breakeven_benchmark": beat, "annual_cost": float(cost_frac.sum() / max(len(cost_frac) / TD, 1e-9))}


def stationary_bootstrap(r: np.ndarray, n: int, mean_block: int, seed: int) -> np.ndarray:
    """`n` séries rééchantillonnées de même longueur (indices), blocs de longueur géométrique (Politis et Romano)."""
    T = len(r)
    rng = np.random.default_rng(seed)
    p = 1.0 / mean_block
    starts = rng.integers(0, T, size=(n, T))
    new_block = rng.random((n, T)) < p
    new_block[:, 0] = True
    idx = np.empty((n, T), dtype=np.int64)
    idx[:, 0] = starts[:, 0]
    for t in range(1, T):
        idx[:, t] = np.where(new_block[:, t], starts[:, t], (idx[:, t - 1] + 1) % T)
    return idx


def bootstrap(ret: pd.Series, n: int = 1000, mean_block: int = 20, seed: int = 3, cash_rate: float = 0.0) -> dict:
    r = ret.to_numpy(dtype=float)
    if len(r) < 60:
        return {"available": False}
    idx = stationary_bootstrap(r, n, mean_block, seed)
    paths = r[idx]
    growth = np.cumprod(1 + paths, axis=1)
    years = len(r) / TD
    cagr = growth[:, -1] ** (1 / years) - 1
    sd = paths.std(axis=1, ddof=1)
    sharpe = np.where(sd > 0, (paths.mean(axis=1) - cash_rate / TD) / sd * math.sqrt(TD), np.nan)
    peak = np.maximum.accumulate(growth, axis=1)
    mdd = (growth / peak - 1).min(axis=1)
    q = lambda x: {"p05": float(np.nanpercentile(x, 5)), "p50": float(np.nanpercentile(x, 50)), "p95": float(np.nanpercentile(x, 95))}
    return {"available": True, "n": n, "cagr": q(cagr), "sharpe": q(sharpe), "max_dd": q(mdd), "prob_loss": float((cagr < 0).mean())}


def psr(r: np.ndarray, sr0_daily: float = 0.0) -> float | None:
    """Sharpe probabiliste : P(vrai Sharpe > sr0) compte tenu de la longueur, de l'asymétrie et des queues épaisses."""
    T = len(r)
    if T < 30 or r.std(ddof=1) == 0:
        return None
    sr = r.mean() / r.std(ddof=1)
    g3 = float(pd.Series(r).skew())
    g4 = float(pd.Series(r).kurt()) + 3
    den = 1 - g3 * sr + (g4 - 1) / 4 * sr ** 2
    if den <= 0:
        return None
    return float(norm.cdf((sr - sr0_daily) * math.sqrt(T - 1) / math.sqrt(den)))


def deflated(r: np.ndarray, trial_sharpes_daily: np.ndarray) -> dict | None:
    """Sharpe déflaté : le seuil SR0 est le Sharpe maximal attendu parmi N essais sans aucun talent, d'après la dispersion des Sharpe essayés."""
    trials = trial_sharpes_daily[np.isfinite(trial_sharpes_daily)]
    N = len(trials)
    if N < 2:
        return None
    gamma = 0.5772156649
    sd = float(trials.std(ddof=1))
    sr0 = sd * ((1 - gamma) * norm.ppf(1 - 1 / N) + gamma * norm.ppf(1 - 1 / (N * math.e)))
    value = psr(r, sr0)
    return {"dsr": value, "trials": N, "sr0_annual": float(sr0 * math.sqrt(TD))}


PBO_BLOCKS = 8


def pbo_of(returns: pd.DataFrame, n_blocks: int = PBO_BLOCKS) -> dict | None:
    """A20 (24/11) : probabilité de sur-apprentissage (Bailey, Borwein, López de Prado et Zhu 2017) de la grille de réglages. Le Sharpe de chaque
    réglage sur `n_blocks` tranches de temps égales ; pour chaque moitié de tranches, le meilleur réglage « en échantillon » est-il au-dessus de
    la médiane « hors échantillon » ? PBO = part des cas où non. Proche de 0,5 ou plus : le meilleur réglage doit sa place au hasard."""
    from patrick.validation.pbo import compute_pbo

    if returns.shape[1] < 2 or len(returns) < n_blocks * 20:
        return None
    blocks = np.array_split(np.arange(len(returns)), n_blocks)
    matrix = np.full((returns.shape[1], n_blocks), np.nan)
    for j, idx in enumerate(blocks):
        part = returns.iloc[idx]
        sd = part.std().replace(0, np.nan)
        matrix[:, j] = (part.mean() / sd).to_numpy()
    matrix = np.nan_to_num(matrix, nan=0.0)                     # tranche sans variation : Sharpe nul
    out = compute_pbo(matrix)
    pbo = out.get("pbo")
    return {"pbo": None if pbo is None or not np.isfinite(pbo) else float(pbo), "n_trials": int(returns.shape[1]), "n_blocks": int(out.get("n_blocks", n_blocks)),
            "n_combinations": int(out.get("n_combinations", 0))}


def walk_forward(returns: pd.DataFrame, labels: list[str], min_train_years: int = 2) -> dict | None:
    """Sélection annuelle du meilleur réglage sur le passé seul (fenêtre croissante), appliqué l'année suivante."""
    if returns.shape[1] < 2:
        return None
    years = sorted(set(returns.index.year))
    if len(years) <= min_train_years:
        return None
    pieces, chosen = [], []
    for y in years[min_train_years:]:
        train = returns[returns.index.year < y]
        test = returns[returns.index.year == y]
        if len(train) < TD or test.empty:
            continue
        sd = train.std()
        score = (train.mean() / sd.replace(0, np.nan)).fillna(-np.inf)
        best = int(np.argmax(score.to_numpy()))
        pieces.append(test.iloc[:, best])
        chosen.append({"year": int(y), "label": labels[best]})
    if not pieces:
        return None
    oos = pd.concat(pieces)
    eq = (1 + oos).cumprod()
    eq = pd.concat([pd.Series([1.0], index=[oos.index[0] - pd.Timedelta(days=1)]), eq])
    return {"metrics": metrics.core(oos, eq), "chosen": chosen, "dates": [d.date().isoformat() for d in eq.index[::5]],
            "equity": [float(v) for v in eq.iloc[::5]], "start": oos.index[0].date().isoformat()}


def verdict(core: dict, bench: dict | None, rand: dict | None, oos: dict | None, cost: dict | None, dsr: dict | None, n_trades: int) -> dict:
    """Une lecture en clair : chaque épreuve passée, échouée ou non jouée, puis un état d'ensemble (robuste, fragile, pas d'avantage)."""
    checks = []

    def add(key: str, ok: bool | None, value=None):
        checks.append({"key": key, "ok": ok, "value": value})

    if bench:
        add("beats_benchmark", bool(core.get("sharpe") is not None and bench.get("sharpe") is not None and core["sharpe"] > bench["sharpe"]),
            [core.get("sharpe"), bench.get("sharpe")])
    else:
        add("beats_benchmark", None)
    add("positive_sharpe", bool((core.get("sharpe") or 0) > 0), core.get("sharpe"))
    add("random_test", (rand["p_value"] < 0.05) if rand and rand.get("available") else None, rand.get("p_value") if rand else None)
    if oos and "out_of_sample" in oos:
        so, si = oos["out_of_sample"]["sharpe"], oos["in_sample"]["sharpe"]
        add("oos_holds", bool(not math.isnan(so) and so > 0 and (si is None or si <= 0 or so >= 0.5 * si)), [si, so])
    else:
        add("oos_holds", None)
    add("cost_margin", (cost["breakeven_sharpe"] is None or cost["breakeven_sharpe"] >= 2) if cost else None, cost.get("breakeven_sharpe") if cost else None)
    add("deflated_sharpe", (dsr["dsr"] is not None and dsr["dsr"] >= 0.95) if dsr else None, dsr.get("dsr") if dsr else None)
    add("enough_trades", n_trades >= 30 or core.get("years", 0) >= 5, n_trades)
    played = [c for c in checks if c["ok"] is not None]
    failed = [c["key"] for c in played if not c["ok"]]
    if not (core.get("sharpe") or 0) > 0 or ("beats_benchmark" in failed and "random_test" in failed):
        state = "none"
    elif not failed:
        state = "robust"
    else:
        state = "fragile"
    return {"state": state, "checks": checks, "failed": failed}
