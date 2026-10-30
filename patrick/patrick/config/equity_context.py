"""Contexte de marché d'une action : l'indice de sa place de cotation et, pour l'Europe, un indice de la zone euro.

Une action reçoit, en plus du pipeline standard, des features de contexte (`features/equity_context.py`) : rendement relatif à son
marché, bêta, corrélation, volatilité propre. Ce module dit contre QUOI elle se compare et quelles séries Yahoo il faut donc ajouter
à l'univers de features de son run (`webapp/forms.py::universe_excluding`).

- **Indice de la place** : le suffixe Yahoo du symbole donne la place (`.PA` Paris, `.DE` Xetra, `.AS` Amsterdam, `.L` Londres...).
  Une action cotée aux États-Unis (pas de suffixe, ADR compris) se compare au S&P 500.
- **Zone euro** : pas d'indice Euro Stoxx 50 exploitable (Yahoo le sert depuis 2007 seulement, le filtre de couverture à 85 % depuis 2000 le
  retire), donc un indice composite en euros, construit dans `features/equity_context.py` à partir des indices nationaux
  ci-dessous (tous servis depuis 1997 au plus tard). Il sert aussi de référence « Europe » aux places hors zone euro sans indice
  utilisable (Danemark, Norvège, Suède : les indices OMX n'existent pas ou trop tard chez Yahoo).
- Les séries macro de la zone euro (rendements des emprunts d'État, HICP, PIB, taux de la BCE) sont des séries FRED d'entraînement
  (`config/defaults.py::MACRO_ONLY_FRED_SERIES`) : elles alimentent tous les runs, pas seulement ceux des actions.
"""
from __future__ import annotations

import re

GLOBAL_BENCHMARK = "^GSPC"

# Places de la zone euro (suffixes Yahoo) : Paris, Xetra, Amsterdam, Madrid, Milan, Bruxelles, Helsinki, Lisbonne, Vienne, Dublin.
EURO_AREA_SUFFIXES = frozenset({"PA", "DE", "AS", "MC", "MI", "BR", "HE", "LS", "VI", "IR"})
# Europe : la zone euro, plus Londres, Zurich, Copenhague, Oslo, Stockholm.
EUROPE_SUFFIXES = EURO_AREA_SUFFIXES | frozenset({"L", "SW", "CO", "OL", "ST"})

# Indices nationaux en euros dont la moyenne des rendements forme l'indice composite de la zone euro.
EURO_COMPOSITE = ("^FCHI", "^GDAXI", "^AEX", "^IBEX", "FTSEMIB.MI")
EURO_COMPOSITE_MIN_MEMBERS = 3

# Indice de la place de cotation. Absents volontairement : Danemark, Norvège, Suède, Finlande (indices servis trop tard ou pas du tout),
# Inde (^NSEI servi depuis 2007 : ^BSESN le remplace). Une place sans indice garde seulement la référence Europe / mondiale.
HOME_INDEX_BY_SUFFIX = {
    "PA": "^FCHI", "DE": "^GDAXI", "AS": "^AEX", "MC": "^IBEX", "MI": "FTSEMIB.MI", "BR": "^BFX",
    "L": "^FTSE", "SW": "^SSMI",
    "T": "^N225", "HK": "^HSI", "KS": "^KS11", "NS": "^BSESN",
}

_SUFFIX = re.compile(r"^[A-Z0-9\-]+\.([A-Z]{1,2})$")


def suffix_of(symbol: str) -> str | None:
    """Suffixe de place Yahoo (`PA` pour `MC.PA`) ; None pour un symbole sans suffixe (États-Unis) ou un indice, un future, une devise."""
    m = _SUFFIX.match(symbol or "")
    return m.group(1) if m else None


def region_of(symbol: str) -> str:
    """`euro`, `europe` (hors zone euro) ou `other` (États-Unis, Asie)."""
    suffix = suffix_of(symbol)
    if suffix in EURO_AREA_SUFFIXES:
        return "euro"
    return "europe" if suffix in EUROPE_SUFFIXES else "other"


def home_index(symbol: str) -> str | None:
    """Indice de la place de cotation ; le S&P 500 pour une action américaine ; None si la place n'a pas d'indice utilisable."""
    suffix = suffix_of(symbol)
    if suffix is None:
        return GLOBAL_BENCHMARK
    return HOME_INDEX_BY_SUFFIX.get(suffix)


def uses_euro_composite(symbol: str) -> bool:
    return region_of(symbol) in ("euro", "europe")


def context_tickers(symbol: str) -> list[str]:
    """Séries Yahoo à ajouter à l'univers de features d'un run dont la cible est cette action (liste vide pour tout autre actif)."""
    from patrick.config.equity_universe import is_equity_symbol

    if not is_equity_symbol(symbol):
        return []
    wanted = [home_index(symbol), *(EURO_COMPOSITE if uses_euro_composite(symbol) else ()), GLOBAL_BENCHMARK]
    out: list[str] = []
    for ticker in wanted:
        if ticker and ticker != symbol and ticker not in out:
            out.append(ticker)
    return out
