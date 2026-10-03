"""Estimation des frais d'un ordre (spec §8) : commission déterministe +
coût de spread tiré d'une loi log-normale + frais de change. Le tirage est
reproductible : même graine, même montant. Toutes les constantes sont des
ordres de grandeur indicatifs, pas des mesures sur un courtier réel."""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

import numpy as np

SIGMA = 0.5                       # écart-type du log du coût de spread
FX_FEE_BPS = 10.0                 # frais de change d'une action/ETF en devise étrangère (montant converti)
EQUITY_MIN_COMMISSION = 1.0       # € par ordre action/ETF
EQUITY_COMMISSION_RATE = 0.0005   # 0,05 % du montant
LARGE_CAP_ADV_BASE = 20_000_000.0  # volume moyen quotidien (devise de base) au-delà duquel une action est « grande capitalisation »
EQUITY_PARTICIPATION_SLOPE = 100.0
EQUITY_SIZE_CAP = 5.0
DERIV_SIZE_REF = 1_000_000.0
DERIV_SIZE_CAP = 2.0

# Médiane du coût de spread, en points de base du notionnel.
SPREAD_MEDIAN_BPS = {
    "equity_large": 2.0, "equity_mid": 8.0, "etf": 3.0,
    "cfd_index": 1.0, "cfd_fx_major": 0.8, "cfd_fx_other": 3.0, "cfd_commodity": 4.0,
    "cfd_equity": 5.0, "cfd_crypto": 30.0, "cfd_other": 5.0,
}


@dataclass(frozen=True)
class FeeContext:
    kind: str                       # equity | etf | future | cfd
    notional_base: float
    quantity: float
    currency: str
    base_currency: str = "EUR"
    fee_class: str = ""             # clé de SPREAD_MEDIAN_BPS (CFD) ; ignoré pour action/ETF/future
    adv_notional_base: float | None = None        # volume moyen 20 j en devise de base (action/ETF)
    commission_per_contract_base: float = 0.0     # future : commission fixe par contrat, devise de base
    tick_bps: float = 0.0                          # future : demi-tick en points de base du notionnel


@dataclass(frozen=True)
class FeeBreakdown:
    commission: float
    spread: float
    fx: float

    @property
    def total(self) -> float:
        return round(self.commission + self.spread + self.fx, 2)


def make_seed(*parts) -> int:
    raw = "|".join(str(p) for p in parts).encode()
    return int.from_bytes(hashlib.sha256(raw).digest()[:4], "big")


def estimate_fees(ctx: FeeContext, seed: int) -> FeeBreakdown:
    z = float(np.random.default_rng(seed).standard_normal())
    notional = abs(ctx.notional_base)
    if ctx.kind in ("equity", "etf"):
        commission = max(EQUITY_MIN_COMMISSION, EQUITY_COMMISSION_RATE * notional)
        if ctx.kind == "etf":
            median = SPREAD_MEDIAN_BPS["etf"]
        elif ctx.adv_notional_base and ctx.adv_notional_base >= LARGE_CAP_ADV_BASE:
            median = SPREAD_MEDIAN_BPS["equity_large"]
        else:
            median = SPREAD_MEDIAN_BPS["equity_mid"]
        participation = notional / ctx.adv_notional_base if ctx.adv_notional_base else 0.0
        size = 1.0 + min(EQUITY_SIZE_CAP, EQUITY_PARTICIPATION_SLOPE * participation)
    elif ctx.kind == "future":
        commission = ctx.commission_per_contract_base * ctx.quantity
        median = ctx.tick_bps
        size = 1.0 + min(DERIV_SIZE_CAP, notional / DERIV_SIZE_REF)
    elif ctx.kind == "cfd":
        commission = 0.0
        median = SPREAD_MEDIAN_BPS.get(ctx.fee_class, SPREAD_MEDIAN_BPS["cfd_other"])
        size = 1.0 + min(DERIV_SIZE_CAP, notional / DERIV_SIZE_REF)
    else:
        raise ValueError(f"type d'instrument inconnu : {ctx.kind!r}")
    spread = notional * median / 1e4 * math.exp(SIGMA * z) * size
    # Seuls action/ETF convertissent leur montant ; futures et CFD règlent leur P&L en devise de base
    # sans convertir le notionnel (frais de change nuls, sinon 1 contrat ES coûterait 0,1 % du notionnel).
    converted = ctx.kind in ("equity", "etf") and ctx.currency != ctx.base_currency
    fx = notional * FX_FEE_BPS / 1e4 if converted else 0.0
    return FeeBreakdown(round(commission, 6), round(spread, 6), round(fx, 6))
