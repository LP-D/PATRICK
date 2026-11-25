"""Exposition aux devises du patrimoine réel (FO22 du 25/11) : part de la valeur par devise de cotation, tous comptes réels confondus.

Un ETF « monde » coté à Paris reste exposé au dollar par ses titres ; ici on mesure la devise de COTATION de chaque ligne (déduite du suffixe
Yahoo : `.PA` euro, `.L` livre, sans suffixe dollar…), la part qu'un mouvement de change touche directement. Les liquidités et les fonds en
euros comptent en euro ; une ligne dont la devise ne se déduit pas est rangée à part (« ? ») plutôt que devinée.
"""
from __future__ import annotations

SUFFIX_CCY = {
    ".PA": "EUR", ".AS": "EUR", ".DE": "EUR", ".F": "EUR", ".MI": "EUR", ".MC": "EUR", ".BR": "EUR", ".LS": "EUR", ".HE": "EUR",
    ".VI": "EUR", ".IR": "EUR", ".L": "GBP", ".SW": "CHF", ".TO": "CAD", ".T": "JPY", ".HK": "HKD", ".AX": "AUD", ".ST": "SEK",
    ".OL": "NOK", ".CO": "DKK", ".SA": "BRL", ".KS": "KRW", ".NS": "INR",
}


def currency_of(symbol: str | None) -> str:
    s = (symbol or "").upper()
    if not s or s.startswith("DAT:") or s in ("CASH", "EUR"):
        return "EUR"
    if s.endswith("=X") and len(s) >= 8:
        return s[3:6]                                     # EURUSD=X : cotée en dollars
    if s.endswith("-USD"):
        return "USD"
    for suffix, ccy in SUFFIX_CCY.items():
        if s.endswith(suffix):
            return ccy
    if s.endswith("=F") or s.startswith("^"):
        return "?"
    if "." not in s and s.replace("-", "").isalnum():
        return "USD"
    return "?"


def exposure(holdings: list[dict], cash: float = 0.0) -> dict:
    """`{total, rows: [{currency, value, share}], foreign_share}` : `foreign_share` = part hors euro (devises inconnues exclues)."""
    by: dict[str, float] = {"EUR": float(cash or 0.0)} if cash else {}
    for h in holdings:
        value = float(h.get("value") or 0.0)
        if value:
            ccy = currency_of(h.get("symbol"))
            by[ccy] = by.get(ccy, 0.0) + value
    total = sum(by.values())
    rows = sorted(({"currency": c, "value": v, "share": v / total if total else None} for c, v in by.items()), key=lambda r: -r["value"])
    known = total - by.get("?", 0.0)
    foreign = sum(v for c, v in by.items() if c not in ("EUR", "?"))
    return {"total": total, "rows": rows, "foreign_share": foreign / known if known else None}
