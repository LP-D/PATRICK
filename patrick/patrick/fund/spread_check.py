"""Écart achat-vente observé contre le modèle de frais des fonds (AM11 du 25/11) : une MESURE, pas une bascule.

Le modèle de frais (`fund/fees.py`) tire un écart log-normal autour d'une médiane par classe (`SPREAD_MEDIAN_BPS`, valeurs indicatives
posées à la main). Ici on relève l'écart réel affiché par Yahoo (`bid`, `ask` du jour) sur des titres représentatifs de chaque classe et
on le compare à la médiane du modèle : `ratio` > 1 = le modèle sous-estime les frais de cette classe.

Remplacer les médianes changerait les frais de tous les ordres simulés, donc le P&L passé des fonds : décision (suivi du 25/11). Les
écarts de Yahoo ne valent que pendant la séance (hors séance, `bid`/`ask` sont souvent nuls ou figés) : une mesure se lit avec son heure.
"""
from __future__ import annotations

import statistics
from collections.abc import Callable

from patrick.fund.fees import SPREAD_MEDIAN_BPS

SAMPLES: dict[str, tuple[str, ...]] = {
    "equity_large": ("AAPL", "MSFT", "MC.PA", "SAP.DE", "ASML.AS"),
    "etf": ("SPY", "QQQ", "CW8.PA", "EWQ"),
    "equity_mid": ("ALO.PA", "SOI.PA", "UBI.PA"),
    "cfd_fx_major": ("EURUSD=X", "USDJPY=X", "GBPUSD=X"),
    "cfd_fx_other": ("USDTRY=X", "USDZAR=X", "USDMXN=X"),
    "cfd_index": ("^GSPC", "^FCHI", "^GDAXI"),
    "cfd_commodity": ("GC=F", "CL=F"),
    "cfd_crypto": ("BTC-USD", "ETH-USD"),
}


def _yahoo_quote(symbol: str) -> tuple[float | None, float | None]:
    import yfinance as yf
    info = yf.Ticker(symbol).info or {}
    return info.get("bid"), info.get("ask")


def relative_spread_bps(bid, ask) -> float | None:
    try:
        bid, ask = float(bid), float(ask)
    except (TypeError, ValueError):
        return None
    if bid <= 0 or ask <= 0 or ask < bid:
        return None
    mid = (bid + ask) / 2
    return (ask - bid) / mid * 1e4


def measure(quote: Callable[[str], tuple] | None = None, samples: dict[str, tuple[str, ...]] | None = None) -> list[dict]:
    """Une ligne par classe : `{fee_class, model_bps, measured_bps (médiane), n, ratio, symbols: {symbole: bps}}`."""
    quote = quote or _yahoo_quote
    out = []
    for fee_class, symbols in (samples or SAMPLES).items():
        found: dict[str, float] = {}
        for sym in symbols:
            try:
                bps = relative_spread_bps(*quote(sym))
            except Exception:  # noqa: BLE001 -- frontière fournisseur : un titre en échec ne fausse pas la classe, il en sort
                bps = None
            if bps is not None:
                found[sym] = round(bps, 2)
        model = SPREAD_MEDIAN_BPS.get(fee_class)
        measured = statistics.median(found.values()) if found else None
        out.append({"fee_class": fee_class, "model_bps": model, "measured_bps": measured, "n": len(found),
                    "ratio": (measured / model) if measured is not None and model else None, "symbols": found})
    return out
