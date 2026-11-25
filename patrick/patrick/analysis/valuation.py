"""Valorisation d'une action (A8) : multiples, DCF inversé et DCF à hypothèses explicites, sur la fiche de l'actif.

Données : `yfinance.Ticker(symbol).info` (état ACTUEL, aucune garantie point-in-time : jamais utilisé comme variable d'entraînement).
- Multiples : PER passé et attendu, valeur d'entreprise / EBITDA, VE / chiffre d'affaires, cours / actif net, rendement du flux de trésorerie
  disponible (FCF / capitalisation) et du dividende des douze derniers mois.
- DCF inversé : la croissance annuelle du FCF sur 10 ans que le prix ACTUEL suppose, à taux d'actualisation et croissance terminale donnés.
  C'est la lecture la plus honnête d'un DCF : on ne prétend pas connaître la croissance, on dit ce que le marché paie.
- DCF : valeur par action sous une hypothèse de croissance choisie, avec une table de sensibilité (taux × croissance), parce qu'un DCF
  sans sa sensibilité donne une précision qu'il n'a pas.
Taux d'actualisation par le MEDAF (modèle d'évaluation des actifs financiers) : taux sans risque de la devise de cotation (État à 10 ans :
^TNX pour le dollar, séries de l'OCDE sur FRED pour l'euro, la livre, le franc suisse et le yen) + bêta × prime de risque du marché (5 %),
bêta borné entre 0,5 et 2. Pas de DCF quand le FCF est négatif ou que les comptes ne sont
pas dans la devise de cotation (certificats de titres étrangers, ADR).
"""
from __future__ import annotations

import math

YEARS = 10
TERMINAL_GROWTH = 0.02
EQUITY_PREMIUM = 0.05
DEFAULT_RF = 0.04
DEFAULT_GROWTH = 0.05


def _num(info: dict, *keys: str) -> float | None:
    for k in keys:
        v = info.get(k)
        if isinstance(v, (int, float)) and math.isfinite(v):
            return float(v)
    return None


def multiples(info: dict) -> dict:
    """Multiples lus (None quand la source ne les donne pas)."""
    cap, fcf = _num(info, "marketCap"), _num(info, "freeCashflow")
    return {"pe_trailing": _num(info, "trailingPE"), "pe_forward": _num(info, "forwardPE"), "ev_ebitda": _num(info, "enterpriseToEbitda"),
            "ev_sales": _num(info, "enterpriseToRevenue"), "price_book": _num(info, "priceToBook"),
            "fcf_yield": (fcf / cap) if fcf is not None and cap else None,
            "dividend_yield": _num(info, "trailingAnnualDividendYield")}


def discount_rate(beta: float | None, rf: float = DEFAULT_RF, premium: float = EQUITY_PREMIUM) -> float:
    b = min(max(beta if beta is not None else 1.0, 0.5), 2.0)
    return rf + b * premium


def enterprise_value(fcf0: float, growth: float, rate: float, terminal: float = TERMINAL_GROWTH, years: int = YEARS) -> float:
    """Valeur actuelle des FCF : `years` ans à `growth`, puis croissance perpétuelle `terminal` (formule de Gordon)."""
    if rate <= terminal:
        raise ValueError("le taux d'actualisation doit dépasser la croissance terminale")
    pv, cash = 0.0, fcf0
    for t in range(1, years + 1):
        cash *= 1 + growth
        pv += cash / (1 + rate) ** t
    return pv + cash * (1 + terminal) / (rate - terminal) / (1 + rate) ** years


def implied_growth(ev: float, fcf0: float, rate: float, terminal: float = TERMINAL_GROWTH, years: int = YEARS) -> float | None:
    """Croissance annuelle du FCF qui égale la valeur d'entreprise observée (bissection : la valeur croît avec la croissance)."""
    if fcf0 <= 0 or ev <= 0 or rate <= terminal:
        return None
    lo, hi = -0.5, 1.0
    if not enterprise_value(fcf0, lo, rate, terminal, years) <= ev <= enterprise_value(fcf0, hi, rate, terminal, years):
        return None
    for _ in range(100):
        mid = (lo + hi) / 2
        if enterprise_value(fcf0, mid, rate, terminal, years) < ev:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def analyse(info: dict, rf: float | None = None, growth: float = DEFAULT_GROWTH) -> dict:
    """Tout ce que la fiche affiche ; `dcf` vaut None avec une raison (`dcf_reason`) quand il n'a pas de sens."""
    out: dict = {"name": info.get("longName") or info.get("shortName"), "currency": info.get("currency"), "sector": info.get("sector"),
                 "price": _num(info, "currentPrice", "regularMarketPrice"), "market_cap": _num(info, "marketCap"),
                 "multiples": multiples(info), "dcf": None, "dcf_reason": None}
    fcf, ev, cap, shares = (_num(info, "freeCashflow"), _num(info, "enterpriseValue"), _num(info, "marketCap"),
                            _num(info, "sharesOutstanding"))
    rate = discount_rate(_num(info, "beta"), DEFAULT_RF if rf is None else rf)
    fin_ccy = info.get("financialCurrency")
    if fcf is None or ev is None or cap is None or not shares or out["price"] is None:
        out["dcf_reason"] = "missing"
    elif fcf <= 0:
        out["dcf_reason"] = "negative_fcf"
    elif fin_ccy and out["currency"] and fin_ccy != out["currency"]:
        out["dcf_reason"] = "currency"
    else:
        net_debt = ev - cap

        def per_share(g: float, r: float) -> float:
            return (enterprise_value(fcf, g, r) - net_debt) / shares
        grid_r = [rate + d for d in (-0.01, 0.0, 0.01)]
        grid_g = [growth + d for d in (-0.02, 0.0, 0.02)]
        out["dcf"] = {"rate": rate, "rf": DEFAULT_RF if rf is None else rf, "beta": _num(info, "beta"), "terminal": TERMINAL_GROWTH,
                      "years": YEARS, "growth": growth, "implied_growth": implied_growth(ev, fcf, rate),
                      "value": per_share(growth, rate), "upside": per_share(growth, rate) / out["price"] - 1,
                      "grid_rates": grid_r, "grid_growths": grid_g,
                      "grid": [[per_share(g, r) for g in grid_g] for r in grid_r]}
    return out


def load_info(symbol: str) -> dict:
    """`Ticker.info` de yfinance ; dict vide si la source ne répond pas (frontière fournisseur)."""
    import yfinance as yf

    try:
        info = yf.Ticker(symbol).info
    except Exception:  # noqa: BLE001 -- frontière fournisseur : le scraping de yfinance lève n'importe quoi
        return {}
    return info if isinstance(info, dict) else {}


# Taux sans risque de la devise de cotation : Trésor américain à 10 ans (^TNX, quotidien) ; pour l'euro, la livre, le franc suisse et le yen,
# le rendement des emprunts d'État à 10 ans de l'OCDE sur FRED (mensuel). Autre devise : le taux américain, faute de mieux.
RF_SERIES = {"EUR": ("fred", "IRLTLT01DEM156N"), "GBP": ("fred", "IRLTLT01GBM156N"), "CHF": ("fred", "IRLTLT01CHM156N"),
             "JPY": ("fred", "IRLTLT01JPM156N")}


def risk_free(currency: str | None = None, loader=None) -> float | None:
    """Rendement à 10 ans de l'État de la devise (en fraction), ou None si la série ne répond pas."""
    source, symbol = RF_SERIES.get((currency or "USD").upper(), ("yfinance", "^TNX"))
    if loader is None:
        from patrick.webapp import market_data

        def loader(sym: str, src: str = source) -> dict:
            return market_data.price_history(sym, src, "1y")
    closes = [c for c in (loader(symbol).get("closes") or []) if c is not None]
    return closes[-1] / 100.0 if closes and -2 < closes[-1] < 25 else None
