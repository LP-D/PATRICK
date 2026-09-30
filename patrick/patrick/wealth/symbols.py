"""Yahoo symbol of an imported line, so every position gets a price.

Brokers export identifiers Yahoo does not quote as such, or quotes as
something else:
- a crypto-asset under its bare code: `AXS` (Axie Infinity) is, on Yahoo,
  AXIS Capital Holdings, a US insurer quoted ~100 USD -- the crypto is
  `AXS-EUR`. A line flagged crypto (`asset_class` CRYPTO, or Trade
  Republic's pseudo-ISIN `XF000<code><digits>`) becomes `<code>-<ccy>`;
- an ISIN (`FR0000121329`): resolved by a Yahoo search, preferring a listing
  in the account currency (EUR venues below, Paris first). The ISIN search
  alone may only return the home listing (US0231351067 -> AMZN, in USD):
  the name is searched next (`Amazon.com` -> AMZ.DE, in EUR). A quote in
  another currency is kept as the last resort, with a warning -- the P&L
  would compare a USD close with a EUR purchase price.
A plain ticker (`MC.PA`, `AAPL`) is trusted as given.

Offline (`search=None`), crypto codes are still mapped; ISINs are kept as
they are, with a warning.
"""
from __future__ import annotations

import re

ISIN_RE = re.compile(r"\b([A-Z]{2}[A-Z0-9]{9}\d)\b")
# Trade Republic's pseudo-ISIN of a crypto-asset: XF000BTC0017, XF000AXS0014.
_CRYPTO_ISIN_RE = re.compile(r"\bXF000([A-Z0-9]*?[A-Z])\d+\b")
# Yahoo suffixes of EUR-denominated venues, in order of preference.
EUR_SUFFIXES = (".PA", ".AS", ".DE", ".F", ".MI", ".MC", ".BR", ".LS", ".VI", ".HE", ".IR", ".AT")
_QUOTABLE = {"EQUITY", "ETF", "MUTUALFUND", "INDEX", "CRYPTOCURRENCY"}

_SEARCH_CACHE: dict[str, list[dict]] = {}


def yahoo_search(query: str) -> list[dict]:
    """Yahoo quotes matching `query` (ISIN, name, ticker). Cached for the
    life of the process; an empty answer (offline, rate limit) never."""
    if query in _SEARCH_CACHE:
        return _SEARCH_CACHE[query]
    try:
        import yfinance as yf
        quotes = list(yf.Search(query, max_results=15).quotes or [])
    except Exception as exc:  # noqa: BLE001 -- provider boundary: a failed lookup never breaks an import
        print(f"  [WARN] recherche Yahoo {query!r} : {str(exc)[:100]}")
        return []
    if quotes:
        _SEARCH_CACHE[query] = quotes
    return quotes


def is_crypto(asset_class: str | None, *texts: str | None) -> bool:
    if "CRYPTO" in (asset_class or "").upper():
        return True
    return any(_CRYPTO_ISIN_RE.search((t or "").upper()) for t in texts)


def _crypto_code(symbol: str, *texts: str | None) -> str | None:
    for t in (symbol, *texts):
        m = _CRYPTO_ISIN_RE.search((t or "").upper())
        if m:
            return m.group(1)
    return symbol if symbol and not ISIN_RE.fullmatch(symbol) else None


def _pick(quotes: list[dict], currency: str) -> tuple[str | None, bool]:
    """(symbol, in_currency) of the best quote: a listing in `currency`
    first (EUR only: the venue suffix tells it), else the first quotable."""
    usable = [q["symbol"] for q in quotes if q.get("symbol") and (q.get("quoteType") or "").upper() in _QUOTABLE]
    if currency == "EUR":
        for suffix in EUR_SUFFIXES:
            for sym in usable:
                if sym.upper().endswith(suffix):
                    return sym, True
    return (usable[0], currency != "EUR") if usable else (None, False)


def make_resolver(currency: str = "EUR", search=yahoo_search):
    """`resolve(symbol, name=None, asset_class=None, text="")` ->
    (yahoo_symbol | None, warning | None). `text` is the rest of the line
    (description), searched for an ISIN or a crypto pseudo-ISIN."""
    currency = (currency or "EUR").upper()
    memo: dict[tuple, tuple[str | None, str | None]] = {}

    def resolve(symbol: str | None, name: str | None = None, asset_class: str | None = None,
                text: str | None = "") -> tuple[str | None, str | None]:
        sym = (symbol or "").strip().upper()
        name = (name or "").strip()
        key = (sym, name, (asset_class or "").upper(), text or "")
        if key not in memo:
            memo[key] = _resolve(sym, name, asset_class, text or "")
        return memo[key]

    def _resolve(sym, name, asset_class, text):
        if is_crypto(asset_class, sym, text):
            code = _crypto_code(sym, text)
            if code:
                return (code if "-" in code else f"{code}-{currency}"), None
        if not sym:
            m = ISIN_RE.search(text.upper())
            sym = m.group(1) if m else ""
        if sym and not ISIN_RE.fullmatch(sym):
            return sym, None
        label = sym or name
        if not label:
            return None, None
        if search is None:
            return label.upper()[:40], f"{label} : identifiant non résolu (hors ligne) -- position sans cours"
        fallback = None
        for query in (sym, name):
            if not query:
                continue
            found, in_ccy = _pick(search(query), currency)
            if found and in_ccy:
                return found, None
            fallback = fallback or found
        if fallback:
            return fallback, f"{label} -> {fallback} : cotation hors {currency}, plus-value faussée par le change"
        return label.upper()[:40], f"{label} : introuvable sur Yahoo -- position sans cours"

    return resolve
