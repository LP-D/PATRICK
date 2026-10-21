"""Rattachement d'une news à un ou plusieurs actifs de l'univers (entity linking).

Choix de **précision** : un faux lien contamine le sentiment d'un actif, un lien manqué ne fait que lui retirer une
observation. Trois mécanismes, du plus sûr au plus ambigu :
- `cashtag` : `$AAPL`, quelle que soit la casse ;
- `name` : nom de l'entreprise (libellé de l'univers), **respectant la casse** — « Apple » oui, « apple pie » non ;
  « ING » exige les trois majuscules ;
- `theme` : mots-clés des matières premières, indices, devises et cryptos (« gold », « Brent », « S&P 500 »), insensibles à
  la casse, mots entiers. Une expression ambiguë (« oil prices ») rattache tous les actifs qu'elle désigne.

Limite : pas de désambiguïsation par le contexte (« Orange » la couleur contre l'opérateur). La page /news affiche la
méthode du lien pour que l'utilisateur juge.
"""
from __future__ import annotations

import re

_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])")
_SUFFIX_WORDS = frozenset({"Futures", "ETF", "Price", "Spot", "Yield", "Rate", "Index"})
_CASHTAG = re.compile(r"\$([A-Za-z][A-Za-z0-9.\-=^]{0,9})")

THEME_ALIASES: dict[str, list[str]] = {
    "^GSPC": ["S&P 500", "S&P500"],
    "^VIX": ["VIX", "Cboe Volatility Index", "fear gauge"],
    "EURUSD=X": ["EUR/USD", "EURUSD", "euro-dollar"],
    "DX-Y.NYB": ["dollar index", "DXY"],
    "GBPUSD=X": ["GBP/USD", "cable"],
    "USDJPY=X": ["USD/JPY"],
    "GC=F": ["gold"],
    "SI=F": ["silver"],
    "HG=F": ["copper"],
    "PL=F": ["platinum"],
    "PA=F": ["palladium"],
    "CL=F": ["WTI", "West Texas Intermediate", "crude oil", "oil prices"],
    "BZ=F": ["Brent", "oil prices"],
    "NG=F": ["natural gas"],
    "ZC=F": ["corn"],
    "KE=F": ["wheat"],
    "ZS=F": ["soybeans", "soybean"],
    "ZR=F": ["rough rice"],
    "CC=F": ["cocoa"],
    "KC=F": ["coffee"],
    "CT=F": ["cotton"],
    "SB=F": ["sugar"],
    "OJ=F": ["orange juice"],
    "LE=F": ["live cattle"],
    "GF=F": ["feeder cattle"],
    "HE=F": ["lean hogs"],
    "BTC-USD": ["Bitcoin", "BTC"],
    "ETH-USD": ["Ethereum", "Ether"],
    "SOL-USD": ["Solana"],
    "XRP-USD": ["XRP", "Ripple"],
}


def label_variants(label: str) -> list[str]:
    """Façons d'écrire un libellé d'univers dans un texte : `AholdDelhaize` -> `Ahold Delhaize`. Un identifiant à
    underscores n'est pas un nom d'entreprise : seul le motif `Mot_Suffixe` (« Gold_Futures ») donne un mot."""
    if "_" in label:
        tokens = [t for t in label.split("_") if t not in _SUFFIX_WORDS]
        if len(tokens) == 1 and not any(c.isdigit() for c in tokens[0]):
            return [tokens[0]]
        return []
    spaced = _CAMEL.sub(" ", label)
    return [label] if spaced == label else [label, spaced]


def _boundary(pattern: str, flags: int = 0) -> re.Pattern:
    body = r"\s+".join(re.escape(part) for part in pattern.split())
    return re.compile(rf"(?<![\w$]){body}(?!\w)", flags)


class EntityLinker:
    def __init__(self, names: dict[str, str] | None = None, themes: dict[str, list[str]] | None = None):
        self._symbols = set(names or {}) | set(themes or {})
        self._by_cashtag = {s.upper(): s for s in self._symbols}
        self._names: list[tuple[str, re.Pattern]] = []
        for symbol, label in (names or {}).items():
            for variant in label_variants(label):
                self._names.append((symbol, _boundary(variant)))
        self._themes: list[tuple[str, re.Pattern]] = []
        for symbol, aliases in (themes or {}).items():
            for alias in aliases:
                self._themes.append((symbol, _boundary(alias, re.IGNORECASE)))

    def link(self, text: str) -> list[tuple[str, str]]:
        """[(symbole, méthode)], un seul lien par symbole (la méthode la plus sûre l'emporte), triés par symbole."""
        text = text or ""
        found: dict[str, str] = {}
        for raw in _CASHTAG.findall(text):
            symbol = self._by_cashtag.get(raw.rstrip(".-").upper())
            if symbol:
                found[symbol] = "cashtag"
        for symbol, rx in self._names:
            if symbol not in found and rx.search(text):
                found[symbol] = "name"
        for symbol, rx in self._themes:
            if symbol not in found and rx.search(text):
                found[symbol] = "theme"
        return sorted(found.items())


def universe_linker(groups: dict[str, list[tuple[str, str]]] | None = None) -> EntityLinker:
    """Linker de l'univers suivi : noms des actions et cryptos (libellés de `all_target_groups`) + thèmes curatés,
    limités aux actifs réellement présents dans l'univers."""
    if groups is None:
        from patrick.config.universe_extension import all_target_groups

        groups = all_target_groups()
    known = {sym for items in groups.values() for sym, _ in items}
    names = {sym: label for group, items in groups.items() if group.startswith(("Actions", "Crypto"))
             for sym, label in items}
    themes = {sym: aliases for sym, aliases in THEME_ALIASES.items() if sym in known}
    return EntityLinker(names=names, themes=themes)
