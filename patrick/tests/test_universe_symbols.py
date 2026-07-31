"""Garde-fou sur la FORME des symboles de l'univers (`config/defaults.py::
DEFAULT_TARGET_GROUPS`).

Motivation réelle : un run local a échoué avec
`HTTP Error 404: Quote not found for symbol: L3HARRIS` — le nom de la société
(« L3Harris ») avait été saisi à la place de son ticker (`LHX`). Même classe
d'erreur pour `CBOT_W` (désignation de contrat CBOT) au lieu de l'ETF blé
`WEAT`, cohérent avec ses voisins `CORN`/`SOYB` du même groupe.

Un ticker mort n'est pas silencieux côté features (`yf_coverage` l'écarte, et
les portes de qualité P6.5 le consignent avec un motif), mais il reste
**sélectionnable comme cible** dans le formulaire — et un run lancé sur une
cible sans données échoue. D'où ce test.

Aucun accès réseau : on vérifie la FORME, pas l'existence. Une forme valide
ne garantit pas que le ticker existe ; une forme invalide garantit qu'il
n'existe pas. C'est le seul des deux qui soit vérifiable hors ligne, et c'est
celui qui a mordu.
"""
from __future__ import annotations

import re

from patrick.config import defaults as D

# Marqueurs qui autorisent un symbole long, parce qu'ils désignent autre chose
# qu'une action/ETF : `^` indice (^STOXX50E), `=` paire FX ou future
# (EURUSD=X, ZW=F), `.` place de cotation étrangère (000001.SS).
_LONG_FORM_MARKERS = ("^", "=", ".")
_MAX_PLAIN_TICKER_LEN = 5  # actions/ETF américains : 1 à 5 caractères


def _yfinance_symbols() -> list[tuple[str, str, str]]:
    out = []
    for group, items in D.DEFAULT_TARGET_GROUPS.items():
        if group == D.FRED_TARGET_GROUP:
            continue  # les codes FRED (NFCI, T10Y2Y, DGS10...) suivent d'autres règles
        for symbol, label in items:
            out.append((group, symbol, label))
    return out


def test_no_symbol_contains_an_underscore():
    """Un underscore n'apparaît dans aucun ticker yfinance valide — c'est la
    signature d'un identifiant interne saisi par erreur (`CBOT_W`)."""
    bad = [(g, s) for g, s, _ in _yfinance_symbols() if "_" in s]
    assert not bad, f"symbole(s) avec underscore, jamais valide chez yfinance : {bad}"


def test_plain_tickers_are_not_company_names():
    """Sans marqueur d'indice/FX/place étrangère, un symbole de plus de 5
    caractères est un nom de société, pas un ticker (`L3HARRIS`)."""
    bad = []
    for group, symbol, label in _yfinance_symbols():
        if any(m in symbol for m in _LONG_FORM_MARKERS):
            continue
        base = re.split(r"-", symbol)[0]  # BRK-B, BTC-USD : la base seule compte
        if len(base) > _MAX_PLAIN_TICKER_LEN:
            bad.append((group, symbol, label))
    assert not bad, (
        "symbole(s) trop long(s) pour un ticker action/ETF — nom de société "
        f"saisi à la place du ticker ? {bad}"
    )


def test_symbols_use_only_characters_yfinance_accepts():
    allowed = re.compile(r"^[A-Z0-9.=^-]+$")
    bad = [(g, s) for g, s, _ in _yfinance_symbols() if not allowed.match(s)]
    assert not bad, f"caractère(s) inattendu(s) dans un symbole : {bad}"


def test_no_duplicate_symbol_across_groups():
    """Un même symbole dans deux groupes fausserait `DEFAULT_TARGET_CHOICES`
    (aplatissement) et le sélecteur de cible."""
    seen: dict[str, str] = {}
    dupes = []
    for group, symbol, _ in _yfinance_symbols():
        if symbol in seen:
            dupes.append((symbol, seen[symbol], group))
        seen[symbol] = group
    assert not dupes, f"symbole(s) en double : {dupes}"


def test_the_two_fixed_symbols_are_correct():
    """Non-régression explicite sur les deux corrections."""
    symbols = {s for _, s, _ in _yfinance_symbols()}
    assert "L3HARRIS" not in symbols and "LHX" in symbols
    assert "CBOT_W" not in symbols and "WEAT" in symbols
