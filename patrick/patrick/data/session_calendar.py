"""Per-asset-class time alignment (Phase 0.4): this project's DataFrames are
indexed by CALENDAR DATE (daily yfinance bars), with no close timestamp — a
"same date" join implicitly treats a Tokyo close (~08:00 UTC) and a New York
close (~20:00-21:00 UTC) of the same calendar day as simultaneous. This is
correct in one direction (Tokyo closes before New York the same day, using it
as a "same-day" feature for a US target is legitimate) but wrong in the
other: a feature whose "same-day" close happens AFTER the target's close
contains information not yet available at decision time.

Without real intraday timestamps (out of reach with daily yfinance bars —
getting them would require migrating the entire ingestion to hourly data,
out of scope here), the fix applied is a one-business-day shift: any feature
whose asset class closes (approximate UTC hour) AFTER the target's is
delayed by one bar before being joined — i.e. on date D, the feature used is
its value known as of D-1 (already fully elapsed before the target's close),
not its "same-day" value (not yet known). A documented approximation, better
than no alignment at all, but not equivalent to a true intraday as-of join.
"""
from __future__ import annotations

# Approximate UTC close hour per asset class (0-24 scale, latest value of the
# class — conservative: when in doubt, assume a late close, which delays MORE
# features rather than fewer, at the cost of some freshness, never at the
# cost of leaking information).
CLOSE_UTC_HOUR = {
    "crypto": 24.0,           # 24/7, the "same-day" bar is only complete at the end of the UTC day
    "fx": 22.0,                # NY close convention ~5pm ET
    "futures": 21.0,           # CME/ICE settlement, late US afternoon
    "equities_us": 20.0,       # NYSE/NASDAQ ~4pm ET
    "volatility_index": 20.0,  # VIX & related, quoted on the same session as US indices
    "equities_americas_other": 21.0,
    "equities_europe": 16.5,   # Paris/Frankfurt/London ~16:30-17:30 UTC
    "equities_asia_pacific": 8.0,   # Tokyo/HK/Shanghai/Sydney, the earliest
    "macro": 24.0,              # FRED series used as a direct target (not yfinance)
    "other": 24.0,              # unknown -> treated as the latest (conservative)
}

_EU_SUFFIXES = (".PA", ".DE", ".AS", ".BR", ".MI", ".MC", ".LS", ".VI", ".L",
                ".IR", ".SW", ".ST", ".HE", ".CO", ".OL")
_ASIA_SUFFIXES = (".HK", ".T", ".SS", ".SZ", ".KS", ".TW", ".SI", ".JK", ".KL",
                   ".BO", ".NS", ".AX", ".NZ")
_AMERICAS_OTHER_SUFFIXES = (".SA", ".MX", ".TO", ".BA")

# Indices ("^"-prefixed) classified individually (the suffix alone isn't
# enough to distinguish their region) — not exhaustive: any absent index
# falls back to "other" (conservative handling, see CLOSE_UTC_HOUR["other"]).
_VOLATILITY_INDICES = ("^VIX", "^VIX3M", "^VVIX", "^VXN", "^OVX", "^GVZ", "^EVZ")

_INDEX_REGION = {
    "^GSPC": "equities_us", "^DJI": "equities_us", "^IXIC": "equities_us",
    "^RUT": "equities_us", "^NYA": "equities_us", "^XAX": "equities_us",
    "^FCHI": "equities_europe", "^GDAXI": "equities_europe", "^FTSE": "equities_europe",
    "^STOXX50E": "equities_europe", "^IBEX": "equities_europe", "^N100": "equities_europe",
    "^BFX": "equities_europe",
    "^HSI": "equities_asia_pacific", "^N225": "equities_asia_pacific",
    "^AXJO": "equities_asia_pacific", "^AORD": "equities_asia_pacific",
    "^BSESN": "equities_asia_pacific", "^NSEI": "equities_asia_pacific",
    "^KS11": "equities_asia_pacific", "^TWII": "equities_asia_pacific",
    "^STI": "equities_asia_pacific", "^JKSE": "equities_asia_pacific",
    "^KLSE": "equities_asia_pacific", "^NZ50": "equities_asia_pacific",
    "000001.SS": "equities_asia_pacific",
    "^BVSP": "equities_americas_other", "^MXX": "equities_americas_other",
    "^MERV": "equities_americas_other", "^GSPTSE": "equities_americas_other",
    "DX-Y.NYB": "fx",
}


def classify_asset_class(symbol: str, source: str = "yfinance") -> str:
    """Asset class of a yfinance symbol, by ticker pattern — deliberately
    simple heuristic (no dependency on an external reference database).
    `source == "fred"`: macro series used as a direct target (Phase X5,
    baseline selection by asset class) -- distinct from "other" so it can be
    assigned the random-walk-with-drift baseline rather than the default,
    more conservative one."""
    if source == "fred":
        return "macro"
    if source != "yfinance":
        return "other"
    if symbol in _VOLATILITY_INDICES:
        return "volatility_index"
    if symbol in _INDEX_REGION:
        return _INDEX_REGION[symbol]
    if symbol.endswith("-USD") or symbol.endswith("-USDT") or symbol.endswith("-USDC"):
        return "crypto"
    if symbol.endswith("=X"):
        return "fx"
    if symbol.endswith("=F"):
        return "futures"
    if symbol.endswith(_EU_SUFFIXES):
        return "equities_europe"
    if symbol.endswith(_ASIA_SUFFIXES):
        return "equities_asia_pacific"
    if symbol.endswith(_AMERICAS_OTHER_SUFFIXES):
        return "equities_americas_other"
    if symbol.startswith("^"):
        return "other"
    if "." not in symbol:
        return "equities_us"
    return "other"


def session_lag_days(feature_symbol: str, feature_source: str,
                      target_symbol: str, target_source: str) -> int:
    """1 if the feature must be delayed by one bar before being joined to the
    target (its "same-day" close happens after the target's -> not yet known
    at decision time), 0 otherwise. Always 0 if the target itself is not
    yfinance (FRED: its own temporal correction is the subject of Phase 0.5,
    not this one — see module docstring)."""
    if target_source != "yfinance":
        return 0
    feature_class = classify_asset_class(feature_symbol, feature_source)
    target_class = classify_asset_class(target_symbol, target_source)
    return 1 if CLOSE_UTC_HOUR[feature_class] > CLOSE_UTC_HOUR[target_class] else 0
