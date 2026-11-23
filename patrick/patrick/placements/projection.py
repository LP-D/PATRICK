"""Projection d'une épargne réelle : versements programmés, abondement, frais d'enveloppe, prélèvements sociaux, fiscalité de sortie.

`project` simule des milliers de trajectoires mensuelles du portefeuille par bootstrap par blocs des rendements mensuels OBSERVÉS de la
fenêtre d'étude (blocs de 6 mois tirés ensemble pour tous les supports : les corrélations et les crises communes sont conservées), avec en
option un recentrage « prudent » de la performance (même règle que les scénarios : 30 % de la performance passée, 70 % d'une prime de
risque modeste). Sur chaque trajectoire : versement initial et mensuels (progression annuelle facultative) et annuels, abondement plafonné
par année civile et net de CSG-CRDS, frais d'entrée, frais de gestion de l'enveloppe sur la part hors fonds en euros, prélèvements sociaux
annuels sur les intérêts du fonds en euros, puis impôts de sortie (`envelopes.exit_tax`).

`replay` rejoue la même épargne sur l'HISTOIRE réelle de la fenêtre (versements le dernier jour de chaque mois, rééquilibrage annuel) et
calcule le taux de rendement interne (TRI, pondéré par les montants). `frontier` trace la frontière efficiente sous contraintes, et
`risk_contributions` dit d'où vient le risque d'une allocation.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from patrick.placements import envelopes
from patrick.placements.stats import FREQ

QUANTILES = (5, 25, 50, 75, 95)


def block_indices(T: int, months: int, n: int, block: int = 6, seed: int = 5) -> np.ndarray:
    """Indices de mois `(n, months)` : blocs consécutifs de `block` mois (circulaires) tirés au hasard."""
    rng = np.random.default_rng(seed)
    n_blocks = math.ceil(months / block)
    starts = rng.integers(0, T, size=(n, n_blocks))
    offsets = np.arange(block)
    idx = (starts[:, :, None] + offsets[None, None, :]) % T
    return idx.reshape(n, -1)[:, :months]


def recentre_shift(port: np.ndarray, target_annual: float | None) -> float:
    """Décalage mensuel (en log) qui ramène la performance géométrique moyenne au rendement visé ; 0 sans recentrage."""
    if target_annual is None:
        return 0.0
    return math.log1p(target_annual) / FREQ - float(np.mean(np.log1p(port)))


def simulate(port_paths: np.ndarray, euro_paths: np.ndarray, euro_share: float, env: dict, contrib: dict, months: int,
             charge_fees: bool = True, track_quantiles: bool = False) -> dict:
    """Trajectoires de capital (vectorisées sur les chemins). `port_paths` : rendements mensuels du portefeuille ; `euro_paths` : la part de ce
    rendement qui vient du fonds en euros (pour ses prélèvements sociaux annuels)."""
    n = port_paths.shape[0]
    entry = env["entry_fee"] / 100 if charge_fees else 0.0
    mgmt = env["mgmt_fee"] / 100 / FREQ if charge_fees else 0.0
    rate, cap, csg = env["abond_rate"] / 100, env["abond_cap"], env["abond_csg"] / 100
    euro_ps = env["euro_ps"] / 100
    W = np.zeros(n)
    invested = 0.0
    abond_total = 0.0
    fees = np.zeros(n)
    taxed = np.zeros(n)
    ps_paid = np.zeros(n)
    cap_left = cap
    yearly_values = []
    monthly_q = []                     # quantiles du capital à la fin de chaque mois (éventail mensuel)

    def deposit(amount: float):
        nonlocal invested, abond_total, cap_left, W
        if amount <= 0:
            return
        ab = min(amount * rate, max(cap_left, 0.0)) if rate > 0 else 0.0
        cap_left -= ab
        ab_net = ab * (1 - csg)
        invested += amount
        abond_total += ab_net
        gross = amount + ab_net
        fees_now = gross * entry
        W += gross - fees_now
        fees[:] += fees_now

    growth = 1 + contrib["growth"] / 100
    deposit(contrib["initial"])
    for m in range(1, months + 1):
        r = port_paths[:, m - 1]
        e = euro_paths[:, m - 1]
        euro_gain = W * e
        W = W * (1 + r)
        if euro_ps > 0:
            tax = np.maximum(euro_gain, 0.0) * euro_ps
            W -= tax
            ps_paid += tax
            taxed += np.maximum(euro_gain, 0.0)
        if mgmt > 0:
            fee = W * (1 - euro_share) * mgmt
            W -= fee
            fees += fee
        year = (m - 1) // FREQ
        deposit(contrib["monthly"] * growth ** year)
        if m % FREQ == 0:
            deposit(contrib["yearly"] * growth ** year)
            cap_left = cap
            yearly_values.append(W.copy())
        if track_quantiles:
            monthly_q.append(np.percentile(W, QUANTILES))
    return {"W": W, "invested": invested, "abond": abond_total, "fees": fees, "taxed": taxed, "ps_paid": ps_paid, "yearly": yearly_values,
            "monthly_q": monthly_q}


def _q(x: np.ndarray) -> dict:
    return {f"p{q:02d}": float(np.percentile(x, q)) for q in QUANTILES}


def project(panel: pd.DataFrame, w: pd.Series, euro_keys: list[str], env: dict, contrib: dict, years: int, target_annual: float | None = None,
            n: int = 3000, seed: int = 5, couple: bool = False) -> dict:
    months = years * FREQ
    w = w.reindex(panel.columns).fillna(0.0)
    R = panel.to_numpy(dtype=float)
    port = R @ w.to_numpy()
    euro_mask = np.array([c in euro_keys for c in panel.columns])
    euro = R[:, euro_mask] @ w.to_numpy()[euro_mask] if euro_mask.any() else np.zeros(len(R))
    euro_share = float(w[euro_mask].sum()) if euro_mask.any() else 0.0
    idx = block_indices(len(R), months, n, seed=seed)
    shift = recentre_shift(port, target_annual)
    port_paths = (1 + port[idx]) * math.exp(shift) - 1
    euro_paths = euro[idx]
    sim = simulate(port_paths, euro_paths, euro_share, env, contrib, months, track_quantiles=True)
    free = simulate(port_paths, euro_paths, euro_share, env, contrib, months, charge_fees=False)
    W = sim["W"]
    base = sim["invested"] + sim["abond"]
    gains = W - base
    taxes = np.array([envelopes.exit_tax(g, sim["invested"], years, env, t, couple)["total"] for g, t in zip(gains, sim["taxed"])])
    net = W - taxes
    goal = contrib.get("goal") or 0.0
    # Éventail MENSUEL (un point par mois, plus précis que la fin de chaque année) ; `fan_step` le dit aux lecteurs.
    fan = {f"p{q:02d}": [float(contrib["initial"])] + [round(float(row[i]), 2) for row in sim["monthly_q"]] for i, q in enumerate(QUANTILES)}
    saving = sim["invested"] * env["tmi_in"] / 100 if env.get("deductible") else 0.0
    return {
        "years": years, "invested": sim["invested"], "abondement": sim["abond"], "gross": _q(W), "net": _q(net),
        "taxes_median": float(np.median(taxes)), "fees_median": float(np.median(sim["fees"])), "euro_ps_median": float(np.median(sim["ps_paid"])),
        "fee_drag_median": float(np.median(free["W"]) - np.median(W)), "prob_goal": float((net >= goal).mean()) if goal > 0 else None,
        "prob_loss": float((net < sim["invested"]).mean()), "tax_saving_entry": saving,
        "net_irr_median": irr_constant(contrib, years, float(np.median(net))), "fan": fan, "fan_step": "month",
        "centering": "prudent" if target_annual is not None else "historique",
        "dist_net": distribution(net),
    }


def distribution(x: np.ndarray, bins: int = 36) -> dict:
    """Histogramme d'une distribution simulée (bornes aux centiles 0,5 et 99,5 : quelques chemins extrêmes écraseraient le reste), avec
    moyenne et écart-type pour superposer la loi normale de même moyenne et même écart-type, et les quantiles à tracer en traits."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 2:
        return {"edges": [], "counts": [], "mean": None, "std": None, "n": int(len(x)), "q": {}}
    lo, hi = np.percentile(x, [0.5, 99.5])
    if hi <= lo:
        hi = lo + 1.0
    counts, edges = np.histogram(np.clip(x, lo, hi), bins=bins, range=(lo, hi))
    return {"edges": [float(e) for e in edges], "counts": [int(c) for c in counts], "mean": float(x.mean()), "std": float(x.std(ddof=1)),
            "n": int(len(x)), "q": {f"p{q:02d}": float(np.percentile(x, q)) for q in QUANTILES}}


def irr_constant(contrib: dict, years: int, final: float) -> float | None:
    """TRI annuel d'un échéancier de versements (initial, mensuels, annuels) qui aboutit à `final`."""
    months = years * FREQ
    flows = np.zeros(months + 1)
    growth = 1 + contrib["growth"] / 100
    flows[0] -= contrib["initial"]
    for m in range(1, months + 1):
        year = (m - 1) // FREQ
        flows[m] -= contrib["monthly"] * growth ** year
        if m % FREQ == 0:
            flows[m] -= contrib["yearly"] * growth ** year
    flows[-1] += final
    return irr(flows)


def irr(flows: np.ndarray) -> float | None:
    """Taux annuel r tel que la valeur actuelle des flux mensuels est nulle (bissection sur le taux mensuel)."""
    if not (flows < 0).any() or not (flows > 0).any():
        return None
    t = np.arange(len(flows))

    def npv(rm: float) -> float:
        return float(np.sum(flows / (1 + rm) ** t))

    lo, hi = -0.99 / FREQ, 1.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-9:
            break
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return float((1 + (lo + hi) / 2) ** FREQ - 1)


def replay(panel: pd.DataFrame, w: pd.Series, euro_keys: list[str], env: dict, contrib: dict) -> dict:
    """La même épargne rejouée sur l'histoire réelle de la fenêtre, avec rééquilibrage annuel vers les poids cibles."""
    w = w.reindex(panel.columns).fillna(0.0).to_numpy()
    R = panel.to_numpy(dtype=float)
    euro_mask = np.array([c in euro_keys for c in panel.columns])
    entry, mgmt = env["entry_fee"] / 100, env["mgmt_fee"] / 100 / FREQ
    rate, cap, csg, euro_ps = env["abond_rate"] / 100, env["abond_cap"], env["abond_csg"] / 100, env["euro_ps"] / 100
    h = np.zeros(len(w))
    invested = abond = 0.0
    cap_left = cap
    flows = [0.0] * (len(R) + 1)
    values, inv_series = [], []
    growth = 1 + contrib["growth"] / 100

    def deposit(amount: float, step: int):
        nonlocal h, invested, abond, cap_left
        if amount <= 0:
            return
        ab = min(amount * rate, max(cap_left, 0.0)) if rate > 0 else 0.0
        cap_left -= ab
        gross = amount + ab * (1 - csg)
        h = h + gross * (1 - entry) * w
        invested += amount
        abond += ab * (1 - csg)
        flows[step] -= amount

    deposit(contrib["initial"], 0)
    values.append(float(h.sum()))
    inv_series.append(invested)
    for m in range(1, len(R) + 1):
        r = R[m - 1]
        gain_euro = h[euro_mask] * r[euro_mask]
        h = h * (1 + r)
        if euro_ps > 0 and euro_mask.any():
            h[euro_mask] -= np.maximum(gain_euro, 0) * euro_ps
        if mgmt > 0:
            h[~euro_mask] *= (1 - mgmt)
        year = (m - 1) // FREQ
        deposit(contrib["monthly"] * growth ** year, m)
        if m % FREQ == 0:
            deposit(contrib["yearly"] * growth ** year, m)
            cap_left = cap
            total = h.sum()
            h = total * w                       # rééquilibrage annuel
        values.append(float(h.sum()))
        inv_series.append(invested)
    final = values[-1]
    flows[-1] += final
    v = pd.Series(values)
    peak = v.cummax()
    dates = [(panel.index[0] - pd.offsets.MonthEnd(1)).date().isoformat(), *[d.date().isoformat() for d in panel.index]]
    return {"dates": dates, "value": values, "invested": inv_series, "final": final, "total_invested": invested, "abondement": abond,
            "irr": irr(np.array(flows)), "max_dd": float((v / peak - 1).min()), "years": len(R) / FREQ}


def _bounds(cols: list[str], bounds_map: dict | None, cap: float, cash: str | None) -> list[tuple[float, float]]:
    out = []
    for c in cols:
        lo, hi = 0.0, 1.0 if c == cash else cap
        if bounds_map and c in bounds_map:
            lo, hi = max(lo, bounds_map[c][0]), min(hi, bounds_map[c][1])
        out.append((lo, max(lo, hi)))
    return out


def frontier(panel: pd.DataFrame, cash: str, bounds_map: dict | None = None, groups: list | None = None, cap: float = 1.0, points: int = 14) -> dict:
    """Frontière efficiente (rendement moyen annualisé maximal pour chaque niveau de volatilité), supports seuls en points."""
    cols = list(panel.columns)
    m = panel.mean().to_numpy() * FREQ
    C = panel.cov().to_numpy() * FREQ
    bnds = _bounds(cols, bounds_map, cap, cash)
    cons = [{"type": "eq", "fun": lambda w: w.sum() - 1}]
    for keys, lo, hi in groups or []:
        mask = np.array([c in keys for c in cols])
        cons.append({"type": "ineq", "fun": lambda w, mk=mask, lo=lo: w[mk].sum() - lo})
        cons.append({"type": "ineq", "fun": lambda w, mk=mask, hi=hi: hi - w[mk].sum()})
    lo_arr = np.array([b[0] for b in bnds])
    hi_arr = np.array([b[1] for b in bnds])
    if lo_arr.sum() > 1 + 1e-9 or hi_arr.sum() < 1 - 1e-9:
        return {"points": [], "funds": []}

    def start() -> np.ndarray:
        x = lo_arr.copy()
        room = hi_arr - lo_arr
        x += room / max(room.sum(), 1e-12) * (1 - lo_arr.sum())
        return x

    def solve(fun, extra=()):
        res = minimize(fun, start(), method="SLSQP", bounds=bnds, constraints=cons + list(extra), options={"maxiter": 500, "ftol": 1e-12})
        return res.x if res.success else None

    w_min = solve(lambda w: w @ C @ w)
    w_max = solve(lambda w: -(w @ m))
    out = []
    if w_min is not None and w_max is not None:
        v_lo, v_hi = math.sqrt(max(w_min @ C @ w_min, 0)), math.sqrt(max(w_max @ C @ w_max, 0))
        for target in np.linspace(v_lo, max(v_hi, v_lo + 1e-6), points):
            wt = solve(lambda w: -(w @ m), [{"type": "ineq", "fun": lambda w, t=target: t * t - w @ C @ w}])
            if wt is None:
                continue
            top = sorted(((cols[i], float(wt[i])) for i in range(len(cols)) if wt[i] > 0.01), key=lambda x: -x[1])[:5]
            out.append({"vol": float(math.sqrt(max(wt @ C @ wt, 0))), "ret": float(wt @ m), "weights": top})
    funds = [{"key": c, "vol": float(math.sqrt(C[i, i])), "ret": float(m[i])} for i, c in enumerate(cols)]
    return {"points": out, "funds": funds}


def point(panel: pd.DataFrame, w: pd.Series) -> dict:
    w = w.reindex(panel.columns).fillna(0.0).to_numpy()
    m = panel.mean().to_numpy() * FREQ
    C = panel.cov().to_numpy() * FREQ
    return {"vol": float(math.sqrt(max(w @ C @ w, 0))), "ret": float(w @ m)}


def risk_contributions(panel: pd.DataFrame, w: pd.Series, threshold: float = 0.005) -> list[dict]:
    """Part de la variance du portefeuille apportée par chaque support : w_i (Σw)_i / w'Σw (la somme fait 100 %)."""
    wv = w.reindex(panel.columns).fillna(0.0).to_numpy()
    C = panel.cov().to_numpy() * FREQ
    var = float(wv @ C @ wv)
    if var <= 0:
        return []
    rc = wv * (C @ wv) / var
    return sorted(({"key": c, "weight": float(wv[i]), "risk": float(rc[i])} for i, c in enumerate(panel.columns) if wv[i] > threshold),
                  key=lambda x: -x["risk"])
