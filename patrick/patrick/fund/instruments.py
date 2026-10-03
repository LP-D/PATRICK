"""Spécifications des instruments du chantier 1 (spec §7) : catalogue de
futures, règles d'échéance, classes d'actifs et plafonds de levier des CFD.

Les marges et commissions du catalogue sont des ORDRES DE GRANDEUR
INDICATIFS (estimation au 2026-10-03, non relevés sur le barème CME Group) :
à rafraîchir depuis les barèmes publiés avant tout usage sérieux."""
from __future__ import annotations

import calendar
import datetime as dt
import re
from dataclasses import dataclass

import numpy as np

MONTH_CODES = {1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M", 7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z"}
QUARTERLY = (3, 6, 9, 12)
ALL_MONTHS = tuple(range(1, 13))


def _third_weekday(year: int, month: int, weekday: int) -> dt.date:
    first = dt.date(year, month, 1)
    shift = (weekday - first.weekday()) % 7
    return first + dt.timedelta(days=shift + 14)


def _bd(day: dt.date, offset: int, roll: str) -> dt.date:
    return np.busday_offset(day, offset, roll=roll).astype(dt.date)


def _last_day(year: int, month: int) -> dt.date:
    return dt.date(year, month, calendar.monthrange(year, month)[1])


# Règles d'échéance approchées (jours fériés ignorés, écart possible de 1 à 2 jours) ;
# si la série stockée s'arrête avant, la dernière date stockée fait foi (engine.simulate).
def expiry_third_friday(year: int, month: int) -> dt.date:
    return _third_weekday(year, month, 4)


def expiry_crude(year: int, month: int) -> dt.date:
    prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    return _bd(_bd(dt.date(prev_year, prev_month, 25), 0, "backward"), -3, "backward")


def expiry_natgas(year: int, month: int) -> dt.date:
    return _bd(dt.date(year, month, 1), -3, "forward")


def expiry_third_last_bd(year: int, month: int) -> dt.date:
    return _bd(_last_day(year, month), -2, "backward")


def expiry_grain(year: int, month: int) -> dt.date:
    return _bd(dt.date(year, month, 15), -1, "forward")


def expiry_treasury(year: int, month: int) -> dt.date:
    return _bd(_bd(_last_day(year, month), 0, "backward"), -7, "backward")


def expiry_fx(year: int, month: int) -> dt.date:
    return _bd(_third_weekday(year, month, 2), -2, "backward")


EXPIRY_RULES = {
    "third_friday": expiry_third_friday, "crude": expiry_crude, "natgas": expiry_natgas,
    "third_last_bd": expiry_third_last_bd, "grain": expiry_grain, "treasury": expiry_treasury, "fx": expiry_fx,
}


@dataclass(frozen=True)
class FutureSpec:
    root: str
    name: str
    exchange: str            # suffixe Yahoo : CME | CBT | NYM | CMX
    currency: str
    multiplier: float        # devise du contrat par point de prix
    tick_size: float
    months: tuple[int, ...]
    expiry_rule: str
    margin: float            # marge initiale par contrat, devise du contrat (indicatif)
    commission: float        # commission par contrat et par sens, devise du contrat (indicatif)
    group: str

    def yahoo_symbol(self, year: int, month: int) -> str:
        return f"{self.root}{MONTH_CODES[month]}{year % 100:02d}.{self.exchange}"

    def expiry(self, year: int, month: int) -> dt.date:
        return EXPIRY_RULES[self.expiry_rule](year, month)


def _f(root, name, exch, ccy, mult, tick, months, rule, margin, comm, group):
    return FutureSpec(root, name, exch, ccy, mult, tick, months, rule, margin, comm, group)


_GRAIN_MONTHS = (3, 5, 7, 9, 12)
FUTURES_CATALOG: dict[str, FutureSpec] = {s.root: s for s in (
    _f("ES", "E-mini S&P 500", "CME", "USD", 50.0, 0.25, QUARTERLY, "third_friday", 22000.0, 2.0, "equity_index"),
    _f("MES", "Micro E-mini S&P 500", "CME", "USD", 5.0, 0.25, QUARTERLY, "third_friday", 2200.0, 0.6, "equity_index"),
    _f("NQ", "E-mini Nasdaq-100", "CME", "USD", 20.0, 0.25, QUARTERLY, "third_friday", 32000.0, 2.0, "equity_index"),
    _f("MNQ", "Micro E-mini Nasdaq-100", "CME", "USD", 2.0, 0.25, QUARTERLY, "third_friday", 3200.0, 0.6, "equity_index"),
    _f("YM", "E-mini Dow", "CBT", "USD", 5.0, 1.0, QUARTERLY, "third_friday", 15000.0, 2.0, "equity_index"),
    _f("RTY", "E-mini Russell 2000", "CME", "USD", 50.0, 0.1, QUARTERLY, "third_friday", 8000.0, 2.0, "equity_index"),
    _f("CL", "Pétrole brut WTI", "NYM", "USD", 1000.0, 0.01, ALL_MONTHS, "crude", 6000.0, 2.5, "energy"),
    _f("MCL", "Micro pétrole brut WTI", "NYM", "USD", 100.0, 0.01, ALL_MONTHS, "crude", 600.0, 0.8, "energy"),
    _f("NG", "Gaz naturel Henry Hub", "NYM", "USD", 10000.0, 0.001, ALL_MONTHS, "natgas", 3500.0, 2.5, "energy"),
    _f("GC", "Or", "CMX", "USD", 100.0, 0.1, (2, 4, 6, 8, 10, 12), "third_last_bd", 11000.0, 2.5, "metal"),
    _f("MGC", "Micro or", "CMX", "USD", 10.0, 0.1, (2, 4, 6, 8, 10, 12), "third_last_bd", 1100.0, 0.8, "metal"),
    _f("SI", "Argent", "CMX", "USD", 5000.0, 0.005, (3, 5, 7, 9, 12), "third_last_bd", 14000.0, 2.5, "metal"),
    _f("HG", "Cuivre", "CMX", "USD", 25000.0, 0.0005, (3, 5, 7, 9, 12), "third_last_bd", 6500.0, 2.5, "metal"),
    _f("ZC", "Maïs", "CBT", "USD", 50.0, 0.25, _GRAIN_MONTHS, "grain", 1800.0, 2.5, "grain"),
    _f("ZW", "Blé", "CBT", "USD", 50.0, 0.25, _GRAIN_MONTHS, "grain", 2200.0, 2.5, "grain"),
    _f("ZS", "Soja", "CBT", "USD", 50.0, 0.25, (1, 3, 5, 7, 8, 9, 11), "grain", 3300.0, 2.5, "grain"),
    _f("ZN", "T-Note 10 ans", "CBT", "USD", 1000.0, 0.015625, QUARTERLY, "treasury", 2000.0, 2.0, "rate"),
    _f("6E", "Euro / dollar", "CME", "USD", 125000.0, 0.00005, QUARTERLY, "fx", 2800.0, 2.5, "fx"),
)}


def listed_contracts(root: str, today: dt.date, n: int | None = None) -> list[dict]:
    """Contrats du produit encore négociables à `today` (échéance calculée dans
    le futur), du plus proche au plus lointain."""
    spec = FUTURES_CATALOG[root]
    limit = n or (6 if len(spec.months) <= 4 else 8)
    out: list[dict] = []
    year, month = today.year, today.month
    for _ in range(24 * 12):
        if month in spec.months:
            expiry = spec.expiry(year, month)
            if expiry > today:
                out.append({"root": root, "year": year, "month": month, "symbol": spec.yahoo_symbol(year, month),
                            "expiry": expiry.isoformat(), "label": f"{MONTH_CODES[month]}{year % 100:02d}"})
                if len(out) >= limit:
                    break
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return out


# ------------------------------------------------------------------ CFD
# Plafonds de levier pour un client non professionnel (mesures d'intervention
# de l'ESMA sur les CFD, 2018) : 30:1 paires de devises majeures ; 20:1 autres
# paires, or et indices majeurs ; 10:1 matières premières hors or et indices
# non majeurs ; 5:1 actions et autres ; 2:1 cryptoactifs.
CFD_LEVERAGE_CAPS = {"fx_major": 30.0, "fx_other": 20.0, "gold": 20.0, "index_major": 20.0, "commodity": 10.0,
                     "index_other": 10.0, "equity": 5.0, "crypto": 2.0, "other": 5.0}
CFD_FEE_CLASS = {"fx_major": "cfd_fx_major", "fx_other": "cfd_fx_other", "gold": "cfd_commodity",
                 "index_major": "cfd_index", "index_other": "cfd_index", "commodity": "cfd_commodity",
                 "equity": "cfd_equity", "crypto": "cfd_crypto", "other": "cfd_other"}
ESMA_MAJOR_CURRENCIES = frozenset({"USD", "EUR", "JPY", "GBP", "CAD", "CHF"})
MAJOR_INDICES = frozenset({"^GSPC", "^DJI", "^NDX", "^FTSE", "^FCHI", "^GDAXI", "^STOXX50E", "^N225", "^AXJO"})
_CRYPTO_RE = re.compile(r"^[A-Z0-9]{2,10}-(USD|EUR|GBP|USDT)$")


def classify_cfd_underlying(symbol: str, quote_type: str | None = None) -> str:
    sym = symbol.upper()
    if sym.endswith("=X"):
        pair = sym[:-2]
        if pair.startswith("XAU"):
            return "gold"
        if len(pair) == 6 and pair[:3] in ESMA_MAJOR_CURRENCIES and pair[3:] in ESMA_MAJOR_CURRENCIES:
            return "fx_major"
        return "fx_other"
    if sym == "GC=F":
        return "gold"
    if sym.endswith("=F"):
        return "commodity"
    if sym.startswith("^"):
        return "index_major" if sym in MAJOR_INDICES else "index_other"
    if (quote_type or "").upper() == "CRYPTOCURRENCY" or _CRYPTO_RE.match(sym):
        return "crypto"
    if (quote_type or "EQUITY").upper() in ("EQUITY", "ETF"):
        return "equity"
    return "other"


def cfd_leverage_cap(symbol: str, quote_type: str | None = None) -> float:
    return CFD_LEVERAGE_CAPS[classify_cfd_underlying(symbol, quote_type)]
