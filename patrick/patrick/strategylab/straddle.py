"""Straddle long autour d'un événement, primes reconstruites par Black-Scholes (port de `STRAT RESULTS/earnings_straddle_backtest_avance.ipynb`).

Yahoo ne fournit pas les chaînes d'options historiques : la prime d'entrée est un MODÈLE, pas un prix exécutable. Hypothèses (modifiables) :
- achat à la clôture de la séance précédant le jour 0, vente à la clôture du jour 0 (première clôture après la publication) ;
- volatilité d'entrée = `entry_iv_mult` x volatilité réalisée sur `lookback` séances (les options se paient plus cher que la volatilité passée avant
  une annonce), volatilité de sortie = `exit_iv_ratio` x volatilité d'entrée (l'écrasement de volatilité après l'annonce : le risque principal du
  straddle) ;
- strike = `strike_factor` x cours d'entrée, maturité `maturity_days` jours calendaires, taux `rate` ;
- coûts par contrat de 100 actions : commission par jambe et par transaction, demi-écart acheteur-vendeur et glissement par option et par transaction.
Un straddle perd si le cours bouge moins que ce que la prime payée et l'écrasement de volatilité exigent.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import norm

from patrick.research.event_study import event_day_zero
from patrick.strategylab.core import StrategyError

MULT = 100
MIN_IV, MAX_IV = 0.05, 3.0
MATURITIES = (3, 7, 14, 30)
EXIT_RATIOS = (0.5, 0.65, 0.8, 0.95, 1.1)


@dataclass
class StraddleParams:
    maturity_days: int = 7
    strike_factor: float = 1.0
    entry_iv_mult: float = 1.25
    exit_iv_ratio: float = 0.85
    lookback: int = 60
    rate: float = 0.04
    commission: float = 0.65
    half_spread: float = 0.025
    slippage: float = 0.005
    stake: float = 10_000.0
    n_boot: int = 2000
    seed: int = 42
    split_frac: float = 0.7

    def validate(self) -> None:
        if not 1 <= self.maturity_days <= 365:
            raise StrategyError("La maturité doit être comprise entre 1 et 365 jours.")
        if not 0.7 <= self.strike_factor <= 1.3:
            raise StrategyError("Le strike doit être compris entre 70 % et 130 % du cours.")
        if not 0.5 <= self.entry_iv_mult <= 3:
            raise StrategyError("Le multiple de volatilité d'entrée doit être compris entre 0,5 et 3.")
        if not 0.2 <= self.exit_iv_ratio <= 2:
            raise StrategyError("Le ratio de volatilité de sortie doit être compris entre 0,2 et 2.")
        if not 20 <= self.lookback <= 250:
            raise StrategyError("La fenêtre de volatilité réalisée doit être comprise entre 20 et 250 séances.")
        if not 0.05 <= self.split_frac <= 0.95 or not 200 <= self.n_boot <= 20_000 or not 0 < self.stake < 1e9:
            raise StrategyError("Paramètres de validation ou de mise hors limites.")


def bs(spot: float, strike: float, t: float, vol: float, option: str, rate: float) -> float:
    """Prix Black-Scholes (sans dividende) d'un call ou d'un put européen ; volatilité bornée à [5 %, 300 %]."""
    if t <= 0:
        return max(spot - strike, 0.0) if option == "call" else max(strike - spot, 0.0)
    vol = float(np.clip(vol, MIN_IV, MAX_IV))
    root = math.sqrt(t)
    d1 = (math.log(spot / strike) + (rate + 0.5 * vol * vol) * t) / (vol * root)
    d2 = d1 - vol * root
    if option == "call":
        return spot * norm.cdf(d1) - strike * math.exp(-rate * t) * norm.cdf(d2)
    return strike * math.exp(-rate * t) * norm.cdf(-d2) - spot * norm.cdf(-d1)


def straddle_value(spot: float, strike: float, t: float, vol: float, rate: float) -> float:
    return bs(spot, strike, t, vol, "call", rate) + bs(spot, strike, t, vol, "put", rate)


def realized_vol(close: np.ndarray, i: int, lookback: int) -> float:
    """Volatilité annualisée des `lookback` rendements logarithmiques quotidiens se terminant à la séance `i` (NaN si historique insuffisant)."""
    if i < lookback:
        return float("nan")
    window = np.log(close[i - lookback + 1:i + 1] / close[i - lookback:i])
    return float(window.std(ddof=1) * math.sqrt(252))


def trade_cost(params: StraddleParams) -> float:
    """Coût d'un aller-retour sur un straddle (4 transactions d'option), en dollars par contrat."""
    return 4 * (params.commission + params.half_spread * MULT + params.slippage * MULT)


def price_event(close: np.ndarray, days: pd.DatetimeIndex, i0: int, params: StraddleParams) -> dict | None:
    """P&L d'un straddle acheté à la clôture `i0 - 1` et vendu à la clôture `i0` ; `None` si le cours ou la volatilité manquent."""
    if i0 < 1 or i0 >= len(close):
        return None
    s0, s1 = float(close[i0 - 1]), float(close[i0])
    rv = realized_vol(close, i0 - 1, params.lookback)
    if not (s0 > 0 and s1 > 0 and math.isfinite(rv)):
        return None
    iv_in = float(np.clip(params.entry_iv_mult * rv, MIN_IV, MAX_IV))
    iv_out = float(np.clip(iv_in * params.exit_iv_ratio, MIN_IV, MAX_IV))
    strike = s0 * params.strike_factor
    held_days = max(1, (days[i0] - days[i0 - 1]).days)
    t0 = params.maturity_days / 365
    t1 = max(params.maturity_days - held_days, 0) / 365
    premium = straddle_value(s0, strike, t0, iv_in, params.rate) * MULT
    value = straddle_value(s1, strike, t1, iv_out, params.rate) * MULT
    if premium <= 0:
        return None
    pnl = value - premium - trade_cost(params)
    return {"premium": premium, "value": value, "pnl": pnl, "ret": pnl / premium, "move": s1 / s0 - 1, "iv_in": iv_in}


def simulate(events: pd.DataFrame, source, params: StraddleParams, progress: Callable[[float, str], None] | None = None) -> tuple[pd.DataFrame, dict]:
    """Un straddle par événement : `(table[symbol, day0, group, premium, pnl, ret, move, iv_in], écartés)`."""
    say = progress or (lambda _f, _m: None)
    skipped: dict[str, int] = {}
    rows = []
    symbols = list(events["symbol"].unique())
    for n, symbol in enumerate(symbols):
        say(0.05 + 0.60 * n / max(1, len(symbols)), f"Cours de {symbol} ({n + 1}/{len(symbols)})")
        sub = events[events["symbol"] == symbol]
        start = (sub["at"].min() - pd.Timedelta(days=int(params.lookback * 1.6) + 20)).strftime("%Y-%m-%d")
        px = source.ohlc(symbol, start)
        if px is None or px.empty:
            skipped["cours introuvables"] = skipped.get("cours introuvables", 0) + len(sub)
            continue
        days, close = px.index, px["close"].to_numpy(float)
        for _, ev in sub.iterrows():
            day0 = event_day_zero(ev["at"], days)
            if day0 is None:
                skipped["hors des cours disponibles"] = skipped.get("hors des cours disponibles", 0) + 1
                continue
            res = price_event(close, days, int(days.searchsorted(day0)), params)
            if res is None:
                skipped["historique ou cours insuffisant"] = skipped.get("historique ou cours insuffisant", 0) + 1
                continue
            rows.append({"symbol": symbol, "day0": day0, "group": ev["group"], **res})
    table = pd.DataFrame(rows)
    if not table.empty:
        table = table.sort_values("day0", kind="stable").reset_index(drop=True)
    return table, skipped


def sensitivity(events: pd.DataFrame, source, base: StraddleParams) -> list[dict]:
    """Matrice maturité x ratio de volatilité de sortie : rendement moyen, médian et taux de gain. Les cours sont téléchargés une seule fois (cache)."""
    out = []
    cache: dict[str, pd.DataFrame | None] = {}

    class Cached:
        def ohlc(self, symbol: str, start: str):
            if symbol not in cache:
                cache[symbol] = source.ohlc(symbol, start)
            return cache[symbol]

    cached = Cached()
    for maturity in MATURITIES:
        for ratio in EXIT_RATIOS:
            p = StraddleParams(**{**base.__dict__, "maturity_days": maturity, "exit_iv_ratio": ratio})
            table, _ = simulate(events, cached, p)
            if table.empty:
                continue
            r = table["ret"].to_numpy(float)
            out.append({"maturity": maturity, "exit_ratio": ratio, "n": len(r), "mean": float(r.mean()), "median": float(np.median(r)), "win": float((r > 0).mean())})
    return out
