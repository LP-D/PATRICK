"""Moteur de backtest quotidien, général : n'importe quelles règles d'entrée et de sortie, une sélection par classement, un mode de
pondération, des sorties de risque, des frais réalistes.

Trois étages, tous calculés à la clôture d'une séance de décision t, exécutés à t + `lag` (au moins une séance par défaut : jamais d'ordre passé
sur un cours qu'on ne connaissait pas) :
1. ÉLIGIBILITÉ (règles) : machine à états par instrument : 0 -> +1 si l'entrée longue est vraie, +1 -> 0 si la sortie est vraie (ou, sans règle
   de sortie, dès que l'entrée devient fausse) ; idem en vente à découvert. Sans aucune règle : toujours investi. Les règles ne sont relues
   qu'aux dates de décision (`decision` : chaque séance, semaine, mois, trimestre).
2. SÉLECTION (facultative) : aux dates de décision, parmi les éligibles, les `top` meilleurs (et `bottom` pires, à découvert) selon un
   indicateur ; la sélection est gardée jusqu'à la décision suivante.
3. RISQUE (chaque séance) : stop de perte, objectif de gain, stop suiveur, durée maximale. Une position coupée ne revient qu'après que le
   signal (ou la sélection) l'a lâchée puis reprise : pas de ré-entrée le lendemain d'un stop sur un signal qui n'a pas changé.

Pondérations : égales, inverse de la volatilité, cible de volatilité par ligne, poids fixes ; « par poche » (1/N par instrument ou par place
de la sélection, le reste en liquidités) ou « investi » (renormalisé sur les positions ouvertes). Plafond par ligne, levier maximal, et cible
de volatilité du portefeuille (estimée sur la covariance glissante). Les poids des positions dérivent avec les cours ; ils ne sont remis à la
cible qu'aux dates de rééquilibrage (`rebalance`) — une entrée ou une sortie, elle, s'exécute toujours.

Frais : commission proportionnelle avec minimum par ordre, frais fixes par ordre, glissement (écart acheteur-vendeur et impact), coût
d'emprunt des titres vendus à découvert, rémunération des liquidités et coût du financement du levier. Exécution à la clôture ou à
l'ouverture de la séance d'exécution (la performance de la séance est alors coupée en nuit + séance).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from patrick.strategylab import indicators, rules

FREQS = ("daily", "weekly", "monthly", "quarterly", "annual", "never")
SIZING = ("equal", "inverse_vol", "vol_target", "fixed")
REASONS = ("", "signal", "stop", "objectif", "stop suiveur", "durée max", "sélection", "fin des cours", "fin de période")
R_NONE, R_SIGNAL, R_STOP, R_TP, R_TRAIL, R_DAYS, R_SELECTION, R_DATA = range(8)


class BacktestError(ValueError):
    """Paramètres incohérents : message en français."""


@dataclass
class Strategy:
    long_entry: dict | None = None
    long_exit: dict | None = None
    short_entry: dict | None = None
    short_exit: dict | None = None
    selection: dict | None = None          # {"rank_by": opérande, "order": "desc"|"asc", "top": n, "bottom": m}
    sizing: dict = field(default_factory=lambda: {"method": "equal"})
    overlay: dict | None = None            # {"target_vol": 0.10, "n": 60}
    risk: dict = field(default_factory=dict)  # {"stop_loss": 0.1, "take_profit": 0.3, "trailing": 0.15, "max_days": 20}
    decision: str = "daily"
    rebalance: str = "monthly"
    synthetic: dict | None = None          # paire : {"long": "A", "short": "B"} (géré par `data`)


@dataclass
class Costs:
    commission: float = 0.001              # fraction du montant négocié
    min_fee: float = 0.0                   # minimum par ordre (devise)
    fixed: float = 0.0                     # frais fixes par ordre (devise)
    slippage: float = 0.0005               # fraction du montant négocié
    borrow: float = 0.01                   # coût annuel d'emprunt des titres vendus à découvert
    cash_rate: float = 0.02                # rémunération annuelle des liquidités
    financing_spread: float = 0.01         # surcoût annuel du financement (liquidités négatives)

    def scaled(self, k: float) -> Costs:
        return Costs(self.commission * k, self.min_fee * k, self.fixed * k, self.slippage * k, self.borrow * k, self.cash_rate, self.financing_spread * k)


@dataclass
class Result:
    daily: pd.DataFrame                    # equity, cash, gross, net, positions, costs, turnover, ret, ret_gross
    weights: pd.DataFrame                  # poids détenus à la clôture (après les ordres)
    trades: list[dict]
    contributions: dict[str, float]
    costs_total: float
    notes: list[str]
    directions: np.ndarray                 # directions finales (séance de décision)


def _calendar_mask(index: pd.DatetimeIndex, freq: str) -> np.ndarray:
    """Vrai à la DERNIÈRE séance de chaque période (semaine, mois…) : une décision prise à la clôture de fin de période."""
    if freq == "daily":
        return np.ones(len(index), dtype=bool)
    if freq == "never":
        return np.zeros(len(index), dtype=bool)
    code = {"weekly": "W", "monthly": "M", "quarterly": "Q", "annual": "Y"}[freq]
    period = index.to_period(code)
    last = pd.Series(np.arange(len(index)), index=index).groupby(period).transform("max").to_numpy()
    return np.arange(len(index)) == last


def eligibility(L_in, L_out, S_in, S_out, valid: np.ndarray, decide: np.ndarray) -> np.ndarray:
    """Étage 1 : directions éligibles (−1, 0, +1) par séance et par instrument."""
    T, K = valid.shape
    always = L_in is None and S_in is None
    out = np.zeros((T, K), dtype=np.int8)
    pos = np.zeros(K, dtype=np.int8)
    for t in range(T):
        v = valid[t]
        if always:
            pos = np.where(v, 1, 0).astype(np.int8)
        elif decide[t]:
            if L_in is not None:
                exit_long = (L_out[t] if L_out is not None else ~L_in[t]) & (pos == 1)
                pos = np.where(exit_long, 0, pos)
            if S_in is not None:
                exit_short = (S_out[t] if S_out is not None else ~S_in[t]) & (pos == -1)
                pos = np.where(exit_short, 0, pos)
            flat = pos == 0
            if L_in is not None:
                pos = np.where(flat & L_in[t] & v, 1, pos)
                flat = pos == 0
            if S_in is not None:
                pos = np.where(flat & S_in[t] & v, -1, pos)
            pos = np.where(v, pos, 0).astype(np.int8)
        else:
            pos = np.where(v, pos, 0).astype(np.int8)
        out[t] = pos
    return out


def select(elig: np.ndarray, scores: np.ndarray | None, decide: np.ndarray, top: int, bottom: int, order: str, short_any: bool = True) -> np.ndarray:
    """Étage 2 : parmi les éligibles, les `top` meilleurs (positions longues) et les `bottom` pires (à découvert), gardés entre deux décisions.

    `short_any` : sans règle de vente à découvert, les `bottom` se choisissent parmi tous les instruments éligibles."""
    if scores is None:
        return elig
    T, K = elig.shape
    out = np.zeros_like(elig)
    held = np.zeros(K, dtype=np.int8)
    sign = 1.0 if order == "desc" else -1.0
    for t in range(T):
        if decide[t]:
            s = scores[t] * sign
            held = np.zeros(K, dtype=np.int8)
            if top:
                cand = np.where((elig[t] == 1) & np.isfinite(s))[0]
                if len(cand):
                    held[cand[np.argsort(-s[cand], kind="stable")[:top]]] = 1
            if bottom:
                pool = elig[t] != 0 if short_any else elig[t] == -1
                cand = np.where(pool & np.isfinite(s) & (held == 0))[0]
                if len(cand):
                    held[cand[np.argsort(s[cand], kind="stable")[:bottom]]] = -1
        else:
            held = np.where(elig[t] == 0, 0, held).astype(np.int8)    # une sortie de signal entre deux décisions libère la place
        out[t] = held
    return out


def apply_risk(sel: np.ndarray, close: np.ndarray, risk: dict) -> tuple[np.ndarray, np.ndarray]:
    """Étage 3 : sorties de risque quotidiennes. Retourne `(directions finales, raison de sortie)` ; la raison est notée à la séance où la
    direction finale repasse à 0."""
    T, K = sel.shape
    stop, tp, trail, max_days = (risk.get("stop_loss"), risk.get("take_profit"), risk.get("trailing"), risk.get("max_days"))
    any_risk = any(x not in (None, 0, "") for x in (stop, tp, trail, max_days))
    final = sel.copy()
    reason = np.zeros((T, K), dtype=np.int8)
    pos = np.zeros(K, dtype=np.int8)
    entry = np.full(K, np.nan)
    extreme = np.full(K, np.nan)
    days = np.zeros(K)
    blocked = np.zeros(K, dtype=bool)
    for t in range(T):
        want = sel[t]
        px = close[t]
        blocked &= want != 0                                  # le signal a lâché : la position peut revenir
        target = np.where(blocked, 0, want).astype(np.int8)
        if any_risk:
            open_ = pos != 0
            same = open_ & (target == pos)
            ret = np.where(same, (px / entry - 1) * pos, 0.0)
            extreme = np.where(same, np.where(pos > 0, np.fmax(extreme, px), np.fmin(extreme, px)), extreme)
            days = np.where(same, days + 1, days)
            hit = np.zeros(K, dtype=np.int8)
            if stop:
                hit = np.where(same & (hit == 0) & (ret <= -float(stop)), R_STOP, hit)
            if tp:
                hit = np.where(same & (hit == 0) & (ret >= float(tp)), R_TP, hit)
            if trail:
                dd = np.where(pos > 0, px / extreme - 1, extreme / px - 1)
                hit = np.where(same & (hit == 0) & (dd <= -float(trail)), R_TRAIL, hit)
            if max_days:
                hit = np.where(same & (hit == 0) & (days >= int(max_days)), R_DAYS, hit)
            cut = hit > 0
            if cut.any():
                target = np.where(cut, 0, target).astype(np.int8)
                blocked |= cut
                reason[t] = np.where(cut, hit, reason[t])
        new = (target != 0) & (target != pos)
        entry = np.where(new, px, np.where(target == 0, np.nan, entry))
        extreme = np.where(new, px, np.where(target == 0, np.nan, extreme))
        days = np.where(new | (target == 0), 0, days)
        closed = (pos != 0) & (target != pos) & (reason[t] == 0)
        reason[t] = np.where(closed, R_SIGNAL, reason[t])
        pos = target
        final[t] = target
    return final, reason


def target_weights(dirs: np.ndarray, valid: np.ndarray, sizing: dict, vol: np.ndarray | None, n_slots: int | None) -> np.ndarray:
    """Poids cibles d'une séance (vecteur K)."""
    active = dirs != 0
    if not active.any():
        return np.zeros(len(dirs))
    method = sizing.get("method", "equal")
    mode = sizing.get("allocation", "sleeves")
    base = n_slots if n_slots else max(int(valid.sum()), 1)
    n_active = int(active.sum())
    if method == "fixed":
        fixed = np.asarray(sizing.get("_fixed"), dtype=float)
        w = np.where(active, fixed, 0.0)
        if mode == "active" and w.sum() > 0:
            w = w / w.sum() * fixed[fixed > 0].sum()
        w = w * dirs
    elif method in ("inverse_vol", "vol_target") and vol is not None:
        v = np.where(np.isfinite(vol) & (vol > 1e-6), vol, np.nan)
        if method == "inverse_vol":
            iv = np.where(active, 1 / v, 0.0)
            if not np.isfinite(iv).any() or np.nansum(iv) <= 0:
                iv = active.astype(float)
            iv = np.nan_to_num(iv)
            share = 1.0 if mode == "active" else n_active / base
            w = iv / iv.sum() * share * dirs
        else:
            target = float(sizing.get("target", 0.10))
            raw = np.nan_to_num(np.where(active, target / v, 0.0))
            w = raw / (n_active if mode == "active" else base) * dirs
    else:
        w = dirs / (n_active if mode == "active" else base)
    cap = float(sizing.get("max_weight", 1.0) or 1.0)
    w = np.clip(w, -cap, cap)
    lev = float(sizing.get("leverage", 1.0) or 1.0)
    gross = np.abs(w).sum()
    if gross > lev:
        w = w * lev / gross
    return w


def run(m: indicators.Market, strat: Strategy, costs: Costs, start: pd.Timestamp, end: pd.Timestamp, capital: float = 10_000.0,
        lag: int = 1, at: str = "close") -> Result:
    if not 0 <= lag <= 5:
        raise BacktestError("Le délai d'exécution doit être compris entre 0 et 5 séances.")
    if at == "open" and lag < 1:
        raise BacktestError("Exécution à l'ouverture : le délai doit être d'au moins une séance (le signal est connu à la clôture).")
    if strat.decision not in FREQS[:4] or strat.rebalance not in FREQS:
        raise BacktestError("Fréquence de décision ou de rééquilibrage inconnue.")
    cols = list(m.traded)
    idx = m.index
    close_df = m.close[cols]
    raw_close = close_df.to_numpy(dtype=float)
    first = close_df.apply(lambda s: s.first_valid_index())
    last = close_df.apply(lambda s: s.last_valid_index())
    close_ff = close_df.ffill(limit=5)
    close = close_ff.to_numpy(dtype=float)
    pos_idx = np.arange(len(idx))
    valid = np.zeros_like(raw_close, dtype=bool)
    for k, c in enumerate(cols):
        if first[c] is None or pd.isna(first[c]):
            continue
        a, b = idx.get_loc(first[c]), idx.get_loc(last[c])
        valid[:, k] = (pos_idx >= a) & (pos_idx <= b) & np.isfinite(close[:, k])
    R = close_ff.pct_change(fill_method=None).fillna(0.0).to_numpy(dtype=float, copy=True)
    R[~valid] = 0.0

    decide = _calendar_mask(idx, strat.decision)
    L_in, L_out = rules.to_array(rules.group(m, strat.long_entry), cols), rules.to_array(rules.group(m, strat.long_exit), cols)
    S_in, S_out = rules.to_array(rules.group(m, strat.short_entry), cols), rules.to_array(rules.group(m, strat.short_exit), cols)
    elig = eligibility(L_in, L_out, S_in, S_out, valid, decide)
    n_slots = None
    if strat.selection:
        top, bottom = int(strat.selection.get("top", 0) or 0), int(strat.selection.get("bottom", 0) or 0)
        if top < 0 or bottom < 0 or top + bottom == 0 or top + bottom > len(cols):
            raise BacktestError(f"Sélection : entre 1 et {len(cols)} instruments au total.")
        try:
            scores = indicators.compute(m, strat.selection["rank_by"])[cols].to_numpy(dtype=float)
        except (indicators.IndicatorError, KeyError, TypeError) as exc:
            raise BacktestError(f"Sélection : indicateur de classement invalide ({exc}).") from exc
        sel = select(elig, scores, decide, top, bottom, strat.selection.get("order", "desc"), short_any=S_in is None)
        n_slots = top + bottom
    else:
        sel = elig
    final, reason = apply_risk(sel, close, strat.risk or {})
    # sortie forcée quand les cours d'un instrument s'arrêtent (titre radié, fin du fichier)
    for k, c in enumerate(cols):
        if last[c] is not None and not pd.isna(last[c]):
            b = idx.get_loc(last[c])
            if b < len(idx) - 1 and final[b, k] != 0:
                final[b, k] = 0
                reason[b, k] = R_DATA
                final[b + 1:, k] = 0

    sizing = dict(strat.sizing or {"method": "equal"})
    if sizing.get("method") not in SIZING:
        raise BacktestError("Mode de pondération inconnu.")
    if sizing.get("method") == "fixed":
        weights_in = sizing.get("weights") or {}
        fixed = np.array([max(float(weights_in.get(c, 0.0) or 0.0), 0.0) for c in cols])
        if fixed.sum() <= 0:
            raise BacktestError("Poids fixes : indiquez au moins un poids positif.")
        sizing["_fixed"] = fixed / fixed.sum()
    vol = None
    if sizing.get("method") in ("inverse_vol", "vol_target") or strat.overlay:
        n_vol = int(sizing.get("n", 60) or 60)
        vol = indicators.compute(m, {"ind": "vol", "n": max(5, min(n_vol, 400))})[cols].to_numpy(dtype=float)
    overlay = strat.overlay or None
    ov_n = int((overlay or {}).get("n", 60) or 60)
    ov_target = float((overlay or {}).get("target_vol", 0.10) or 0.10)

    i0 = int(idx.searchsorted(pd.Timestamp(start)))
    i1 = int(idx.searchsorted(pd.Timestamp(end), side="right")) - 1
    if i1 - i0 < 20:
        raise BacktestError("Période d'étude trop courte (au moins 20 séances avec des cours).")
    rebal = _calendar_mask(idx, strat.rebalance)
    opens = m.open[cols].ffill(limit=5).to_numpy(dtype=float) if at == "open" else None

    K = len(cols)
    h = np.zeros(K)
    cash = float(capital)
    held = np.zeros(K, dtype=np.int8)
    W_cache: dict[int, np.ndarray] = {}

    def weights_at(s: int) -> np.ndarray:
        if s in W_cache:
            return W_cache[s]
        w = target_weights(final[s], valid[s], sizing, None if vol is None else vol[s], n_slots)
        if overlay and np.abs(w).sum() > 0 and s >= ov_n:
            window = R[s - ov_n + 1:s + 1]
            cov = np.cov(window, rowvar=False) if K > 1 else np.array([[np.var(window, ddof=1)]])
            est = float(np.sqrt(max(w @ np.atleast_2d(cov) @ w, 0.0) * 252))
            if est > 1e-9:
                lev = float(sizing.get("leverage", 1.0) or 1.0)
                w = w * min(ov_target / est, lev / max(np.abs(w).sum(), 1e-12))
        W_cache[s] = w
        return w

    n_days = i1 - i0 + 1
    rec = {k: np.zeros(n_days) for k in ("equity", "cash", "gross", "net", "positions", "costs", "turnover", "ret", "ret_gross")}
    W_held = np.zeros((n_days, K))
    trades: list[dict] = []
    open_trade: dict[int, dict] = {}
    pnl_asset = np.zeros(K)
    costs_total = 0.0
    daily_cash = costs.cash_rate / 252
    daily_fin = (costs.cash_rate + costs.financing_spread) / 252
    daily_borrow = costs.borrow / 252
    prev_equity = float(capital)
    notes: list[str] = []
    if lag == 0:
        notes.append("exécution à la clôture du jour du signal : optimiste (il faut connaître la clôture avant qu'elle ne soit fixée)")

    def trade_to(target_vals: np.ndarray, mask: np.ndarray, price: np.ndarray, day: int, reasons: np.ndarray) -> tuple[float, float]:
        nonlocal cash, h
        delta = np.where(mask, target_vals - h, 0.0)
        traded = np.abs(delta) > max(1e-6 * max(cash + h.sum(), 1.0), 1e-9)
        if not traded.any():
            return 0.0, 0.0
        gross_traded = np.abs(delta[traded])
        fee = np.maximum(gross_traded * costs.commission, costs.min_fee) + costs.fixed + gross_traded * costs.slippage
        cost = float(fee.sum())
        per_asset = np.zeros(K)
        per_asset[traded] = fee
        cash -= float(delta[traded].sum()) + cost
        h = np.where(traded, h + delta, h)
        new_dir = np.sign(np.where(np.abs(h) > 1e-9, h, 0.0)).astype(np.int8)
        for k in np.where(traded)[0]:
            pnl_asset[k] -= per_asset[k]
            if held[k] != 0 and new_dir[k] != held[k]:
                tr = open_trade.pop(k, None)
                if tr:
                    tr.update({"exit": idx[day].date().isoformat(), "exit_price": float(price[k]), "reason": REASONS[int(reasons[k]) or R_SIGNAL],
                               "days": int(day - tr["_i"]), "return": float((price[k] / tr["entry_price"] - 1) * tr["side"]) if tr["entry_price"] else None,
                               "pnl": float(tr["_pnl"] - per_asset[k]), "costs": float(tr["costs"] + per_asset[k])})
                    trades.append(tr)
            if new_dir[k] != 0 and new_dir[k] != held[k]:
                open_trade[k] = {"symbol": cols[k], "side": int(new_dir[k]), "entry": idx[day].date().isoformat(), "entry_price": float(price[k]),
                                 "_i": day, "_pnl": 0.0, "costs": float(per_asset[k])}
            elif k in open_trade:
                open_trade[k]["costs"] += float(per_asset[k])
                open_trade[k]["_pnl"] -= float(per_asset[k])
        held[:] = new_dir
        return cost, float(gross_traded.sum())

    for j, i in enumerate(range(i0, i1 + 1)):
        s = i - lag
        trade_day = False
        if s >= 0:
            dirs = final[s]
            changed = dirs != held
            trade_day = j == 0 or rebal[i] or bool(changed.any())
        # 1) performance de la séance (en deux temps si l'exécution a lieu à l'ouverture)
        if j > 0:
            if at == "open" and trade_day:
                overnight = np.where(valid[i], opens[i] / close[i - 1] - 1, 0.0)
                overnight = np.nan_to_num(overnight)
                move = h * overnight
            else:
                move = h * R[i]
            pnl_asset += move
            for k, tr in open_trade.items():
                tr["_pnl"] += float(move[k])
            h = h + move
            short_value = float(-h[h < 0].sum())
            carry = cash * (daily_cash if cash >= 0 else daily_fin) - short_value * daily_borrow
            cash += carry
        equity_before = cash + h.sum()
        cost_today, turnover_today = 0.0, 0.0
        if s >= 0 and trade_day:
            price = opens[i] if at == "open" else close[i]
            w = weights_at(s)
            target_vals = w * equity_before
            if j == 0 or rebal[i]:
                mask = np.ones(K, dtype=bool)
            else:
                mask = (final[s] != held)
            c_, t_ = trade_to(target_vals, mask, price, i, reason[s])
            cost_today += c_
            turnover_today += t_
            if at == "open" and j > 0:
                intraday = np.nan_to_num(np.where(valid[i], close[i] / opens[i] - 1, 0.0))
                move = h * intraday
                pnl_asset += move
                for k, tr in open_trade.items():
                    tr["_pnl"] += float(move[k])
                h = h + move
        costs_total += cost_today
        equity = cash + h.sum()
        if equity <= 0:
            notes.append(f"capital épuisé le {idx[i].date().isoformat()} : la simulation s'arrête")
            for key in rec:
                rec[key] = rec[key][:j]
            W_held = W_held[:j]
            n_days = j
            break
        rec["equity"][j] = equity
        rec["cash"][j] = cash
        rec["gross"][j] = np.abs(h).sum() / equity
        rec["net"][j] = h.sum() / equity
        rec["positions"][j] = int((np.abs(h) > 1e-9).sum())
        rec["costs"][j] = cost_today
        rec["turnover"][j] = turnover_today / max(equity_before, 1e-9)
        rec["ret"][j] = equity / prev_equity - 1 if j else equity / capital - 1
        rec["ret_gross"][j] = (equity + cost_today) / prev_equity - 1 if j else (equity + cost_today) / capital - 1
        W_held[j] = h / equity
        prev_equity = equity
    last_day = i0 + n_days - 1
    for k, tr in list(open_trade.items()):
        px = close[last_day, k]
        tr.update({"exit": None, "exit_price": float(px), "reason": REASONS[8], "days": int(last_day - tr["_i"]),
                   "return": float((px / tr["entry_price"] - 1) * tr["side"]) if tr["entry_price"] else None, "pnl": float(tr["_pnl"])})
        trades.append(tr)
    for tr in trades:
        tr.pop("_i", None)
        tr.pop("_pnl", None)
    trades.sort(key=lambda x: (x["entry"], x["symbol"]))
    dates = idx[i0:i0 + n_days]
    daily = pd.DataFrame(rec, index=dates)
    return Result(daily=daily, weights=pd.DataFrame(W_held, index=dates, columns=cols), trades=trades,
                  contributions={c: float(pnl_asset[k]) for k, c in enumerate(cols)}, costs_total=float(costs_total), notes=notes,
                  directions=final[i0:i0 + n_days])
