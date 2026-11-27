"""Fixed-rate bonds held in a wealth account (OAT, bullet corporate bonds).

Conventions (those of the OAT, Agence France Trésor):
- `quantity` = nominal in the account currency (16 404 = 16 404 EUR of
  nominal), `price` = clean price as a FRACTION of nominal (0.8836 =
  88.36 %, Trade Republic's own convention);
- one annual coupon `rate` x nominal on the anniversary of `maturity`,
  redemption at par on `maturity`;
- accrued interest ACT/ACT (ICMA): rate x nominal x days since the last
  coupon / days of the coupon period;
- a bond movement is a buy/sell carrying `maturity` (and `rate`, the
  coupon, when known). The ledger keeps the broker's cash amount: nominal x
  clean price + accrued interest at settlement + fees, so the cash matches
  the statement. The accrued interest paid stays in the cost basis; the
  next coupon (a `dividend` movement) pays it back.

Valuation: nominal x clean price + accrued interest of the day. The clean
price is the Yahoo close when the bond is quoted there (OATs are not), else
the price at the constant yield of the last trade -- amortised cost: the
pull to par is there, a market move is not (said in `price_source`).
"""
from __future__ import annotations

import math
import re

import pandas as pd
from scipy.optimize import brentq

SETTLEMENT_LAG_BDAYS = 2          # EU bonds settle T+2 (CSDR)
COUPON_GRID = 0.00025             # coupons are multiples of 0.025 % (2 %, 2.4 %, 2.75 %, 0.125 %...)
COUPON_SNAP_TOL = 0.00005
MIN_ACCRUED_FOR_INFERENCE = 0.5   # EUR: below, the rounding of the amount drowns the coupon

_OAT_RE = re.compile(r"\bO\.?\s?A\.?\s?T\b\.?", re.IGNORECASE)
_BOND_RE = re.compile(r"\b(?:bond|bonds|obligation|obligations|oblig|anleihe|bund|btp|treasury|gilt)\b", re.IGNORECASE)
_FULL_DATE_RE = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](20\d{2}|\d{2})\b")
_COUPON_RE = re.compile(r"(?<![\d.,])(\d{1,2}(?:[.,]\d{1,4})?)\s?%")
_MONTHS = {"jan": 1, "janv": 1, "feb": 2, "fev": 2, "fevr": 2, "mar": 3, "mars": 3, "mrz": 3, "maer": 3, "apr": 4,
           "avr": 4, "may": 5, "mai": 5, "jun": 6, "juin": 6, "jul": 7, "juil": 7, "aug": 8, "aou": 8, "aout": 8,
           "sep": 9, "sept": 9, "oct": 10, "okt": 10, "nov": 11, "dec": 12, "dez": 12}
_MONTH_YEAR_RE = re.compile(r"\b([a-z]{3,9})\.?\s+(20\d{2})\b")
OAT_MATURITY_DAY = 25             # every OAT matures on the 25th


class BondError(ValueError):
    """A bond computation without a meaningful answer (price out of range...)."""


# ------------------------------------------------------------------ calendar

def coupon_period(maturity, day) -> tuple[pd.Timestamp, pd.Timestamp]:
    """(previous coupon date, next coupon date) around `day` (< maturity)."""
    mat, d = pd.Timestamp(maturity), pd.Timestamp(day)
    k = mat.year - d.year
    nxt = mat - pd.DateOffset(years=k)
    if nxt <= d:
        k -= 1
        nxt = mat - pd.DateOffset(years=k)
    return nxt - pd.DateOffset(years=1), nxt


def settlement_day(trade_day) -> pd.Timestamp:
    return pd.Timestamp(trade_day) + pd.offsets.BDay(SETTLEMENT_LAG_BDAYS)


def accrued_interest(nominal: float, rate: float | None, maturity, day) -> float:
    """Coupon accrued since the last coupon date, ACT/ACT ICMA. Zero at and
    after maturity, or when the coupon is unknown."""
    if not rate or pd.Timestamp(day) >= pd.Timestamp(maturity):
        return 0.0
    prev, nxt = coupon_period(maturity, day)
    return nominal * rate * (pd.Timestamp(day) - prev).days / (nxt - prev).days


# ------------------------------------------------------------------ pricing

def dirty_price(rate: float, maturity, day, ytm: float) -> float:
    """Price per 1 of nominal, accrued interest included, at the annual
    yield `ytm` (ICMA: fraction of the current period + whole years)."""
    d, mat = pd.Timestamp(day), pd.Timestamp(maturity)
    if d >= mat:
        return 1.0
    prev, nxt = coupon_period(mat, d)
    first = (nxt - d).days / (nxt - prev).days
    n = mat.year - nxt.year
    pv = sum(rate / (1.0 + ytm) ** (first + i) for i in range(n + 1))
    return pv + 1.0 / (1.0 + ytm) ** (first + n)


def clean_price(rate: float, maturity, day, ytm: float) -> float:
    return dirty_price(rate, maturity, day, ytm) - accrued_interest(1.0, rate, maturity, day)


def yield_to_maturity(rate: float, maturity, day, price: float) -> float:
    """Annual yield giving the clean `price` (fraction of nominal)."""
    if pd.Timestamp(day) >= pd.Timestamp(maturity):
        raise BondError("obligation échue")
    try:
        return float(brentq(lambda y: clean_price(rate, maturity, day, y) - price, -0.5, 2.0, xtol=1e-12))
    except ValueError as exc:
        raise BondError(f"prix {price:.4f} hors de portée d'un rendement réaliste") from exc


def model_clean_price(rate: float | None, maturity, trade_day, trade_price: float, day) -> tuple[float, float | None]:
    """(clean price on `day`, yield) at the constant yield of the last trade.
    Without a coupon there is no yield: the trade price is kept."""
    if pd.Timestamp(day) >= pd.Timestamp(maturity):
        return 1.0, None
    if rate is None:
        return trade_price, None
    try:
        y = yield_to_maturity(rate, maturity, trade_day, trade_price)
    except BondError:
        return trade_price, None
    return clean_price(rate, maturity, max(pd.Timestamp(day), pd.Timestamp(trade_day)), y), y


# ------------------------------------------------------------------ import helpers

def looks_like_bond(asset_class: str | None, *texts: str | None) -> bool:
    ac = (asset_class or "").upper()
    if "BOND" in ac or "OBLIG" in ac:
        return True
    return any(t and (_OAT_RE.search(t) or _BOND_RE.search(t)) for t in texts)


def quote_as_fraction(price: float) -> float:
    """Bonds are quoted in % of nominal (88.36) or as a fraction (0.8836)."""
    return price / 100.0 if price > 3.0 else price


def maturity_from_text(*texts: str | None) -> str | None:
    """`25/11/2032` as such; `Nov. 2032` on the 25th for an OAT (their
    common maturity day), else unknown -- never a guessed day."""
    blob = " ".join(t for t in texts if t)
    m = _FULL_DATE_RE.search(blob)
    if m:
        day, month, year = (int(g) for g in m.groups())
        year += 2000 if year < 100 else 0
        try:
            return pd.Timestamp(year=year, month=month, day=day).date().isoformat()
        except ValueError:
            pass
    if not _OAT_RE.search(blob):
        return None
    folded = blob.lower().replace("é", "e").replace("û", "u").replace("ä", "ae")
    for word, year in _MONTH_YEAR_RE.findall(folded):
        month = _MONTHS.get(word) or _MONTHS.get(word[:4]) or _MONTHS.get(word[:3])
        if month:
            return pd.Timestamp(year=int(year), month=month, day=OAT_MATURITY_DAY).date().isoformat()
    return None


def coupon_from_text(*texts: str | None) -> float | None:
    for t in texts:
        m = _COUPON_RE.search(t or "")
        if m:
            value = float(m.group(1).replace(",", ".")) / 100.0
            if 0.0 <= value < 0.2:
                return value
    return None


def infer_coupon(accrued_paid: float, nominal: float, maturity, trade_day) -> float | None:
    """Coupon rate implied by the accrued interest paid at purchase (T+2
    settlement), when it lands on the 0.025 % grid -- else None."""
    if accrued_paid < MIN_ACCRUED_FOR_INFERENCE or nominal <= 0:
        return None
    settle = settlement_day(trade_day)
    if settle >= pd.Timestamp(maturity):
        return None
    prev, nxt = coupon_period(maturity, settle)
    fraction = (settle - prev).days / (nxt - prev).days
    if fraction <= 0:
        return None
    rate = accrued_paid / (nominal * fraction)
    snapped = round(rate / COUPON_GRID) * COUPON_GRID
    if not math.isfinite(rate) or abs(rate - snapped) > COUPON_SNAP_TOL or not 0 < snapped < 0.2:
        return None
    return round(snapped, 6)
