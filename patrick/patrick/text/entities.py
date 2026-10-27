"""Rattachement d'une news à un ou plusieurs actifs de l'univers (entity linking).

Choix de **précision** : un faux lien contamine le sentiment d'un actif, un lien manqué ne fait que lui retirer une
observation. Quatre mécanismes, du plus sûr au plus ambigu :
- `cashtag` : `$AAPL`, quelle que soit la casse ;
- `ticker` : symbole précédé de sa place de cotation américaine, « NASDAQ: AAPL », « (NYSE: JPM) » ;
- `name` : nom de l'entreprise (libellé de l'univers) ou son orthographe de presse (`NAME_ALIASES` : « Bank of America »,
  « AT&T », « McDonald's »), **respectant la casse** — « Apple » oui, « apple pie » non ; « ING » exige les trois majuscules ;
- `theme` : mots-clés des matières premières, indices, devises, taux et cryptos (« gold », « Brent », « S&P 500 », « Nikkei »,
  « the yen », « Treasury yields »), mots entiers. Insensibles à la casse, sauf les sigles écrits en majuscules (« DAX », « OPEC »,
  « WTI » : « Dax Shepard » n'est pas l'indice). Une expression ambiguë (« oil prices ») rattache tous les actifs qu'elle désigne.

Limite : pas de désambiguïsation par le contexte (« Orange » la couleur contre l'opérateur). La page /news affiche la
méthode du lien pour que l'utilisateur juge.
"""
from __future__ import annotations

import re

_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])")
_SUFFIX_WORDS = frozenset({"Futures", "ETF", "Price", "Spot", "Yield", "Rate", "Index"})
_CASHTAG = re.compile(r"\$([A-Za-z][A-Za-z0-9.\-=^]{0,9})")
_EXCHANGE_TICKER = re.compile(
    r"\b(?:NYSE(?:\s+American|\s?ARCA)?|NASDAQ|AMEX|OTC(?:QX|QB)?)\s*:\s*([A-Z]{1,5}(?:[.\-][A-Z])?)\b")

THEME_ALIASES: dict[str, list[str]] = {
    # Indices actions
    "^GSPC": ["S&P 500", "S&P500", "Wall Street", "US stocks", "U.S. stocks"],
    "^VIX": ["VIX", "Cboe Volatility Index", "fear gauge"],
    "^IXIC": ["Nasdaq Composite"],
    "^NDX": ["Nasdaq 100", "Nasdaq-100"],
    "^DJI": ["Dow Jones Industrial Average", "the Dow"],
    "^RUT": ["Russell 2000"],
    "^FTSE": ["FTSE 100", "FTSE100", "Footsie"],
    "^FCHI": ["CAC 40", "CAC40"],
    "^GDAXI": ["DAX"],
    "^STOXX50E": ["Euro Stoxx 50", "EURO STOXX 50"],
    "^IBEX": ["IBEX 35"],
    "^N225": ["Nikkei"],
    "^HSI": ["Hang Seng"],
    "^KS11": ["KOSPI"],
    "^BSESN": ["Sensex"],
    "^NSEI": ["Nifty 50", "Nifty"],
    "^AXJO": ["ASX 200"],
    "^BVSP": ["Bovespa", "Ibovespa"],
    "^GSPTSE": ["TSX Composite", "S&P/TSX"],
    "^SSMI": ["Swiss Market Index"],
    "^AEX": ["AEX"],
    "^TWII": ["Taiex"],
    "000001.SS": ["Shanghai Composite"],
    "^SOX": ["Philadelphia Semiconductor"],
    "SMH": ["chipmakers", "chip stocks", "semiconductor stocks"],
    # Devises
    "EURUSD=X": ["EUR/USD", "EURUSD", "euro-dollar", "euro/dollar"],
    "DX-Y.NYB": ["dollar index", "DXY", "greenback", "the dollar", "US dollar", "U.S. dollar"],
    "GBPUSD=X": ["GBP/USD", "pound sterling", "sterling", "the pound"],
    "USDJPY=X": ["USD/JPY", "the yen", "Japanese yen"],
    "USDCHF=X": ["USD/CHF", "Swiss franc"],
    "AUDUSD=X": ["AUD/USD", "Australian dollar", "Aussie dollar"],
    "NZDUSD=X": ["NZD/USD", "New Zealand dollar"],
    "USDCAD=X": ["USD/CAD", "Canadian dollar", "loonie"],
    "CNY=X": ["USD/CNY", "yuan", "renminbi"],
    "INR=X": ["Indian rupee"],
    "MXN=X": ["Mexican peso"],
    "BRL=X": ["Brazilian real"],
    "ZAR=X": ["South African rand"],
    "KRW=X": ["South Korean won"],
    "SGD=X": ["Singapore dollar"],
    # Taux
    "^TNX": ["10-year Treasury", "Treasury yield", "Treasury yields"],
    "^TYX": ["30-year Treasury"],
    "^FVX": ["5-year Treasury"],
    # Matières premières
    "GC=F": ["gold"],
    "SI=F": ["silver"],
    "HG=F": ["copper"],
    "PL=F": ["platinum"],
    "PA=F": ["palladium"],
    "CL=F": ["WTI", "West Texas Intermediate", "crude oil", "oil prices", "oil price", "crude", "OPEC"],
    "BZ=F": ["Brent", "oil prices", "oil price", "crude", "OPEC"],
    "NG=F": ["natural gas"],
    "TTF=F": ["TTF", "Dutch gas", "European gas"],
    "HO=F": ["heating oil"],
    "RB=F": ["gasoline", "RBOB"],
    "ALI=F": ["aluminium", "aluminum"],
    "HRC=F": ["hot-rolled coil", "steel prices"],
    "ZC=F": ["corn"],
    "ZO=F": ["oats"],
    "KE=F": ["wheat"],
    "ZW=F": ["wheat"],
    "ZS=F": ["soybeans", "soybean"],
    "ZL=F": ["soybean oil"],
    "ZM=F": ["soybean meal"],
    "ZR=F": ["rough rice"],
    "CC=F": ["cocoa"],
    "KC=F": ["coffee"],
    "CT=F": ["cotton"],
    "SB=F": ["sugar"],
    "OJ=F": ["orange juice"],
    "LE=F": ["live cattle"],
    "GF=F": ["feeder cattle"],
    "HE=F": ["lean hogs"],
    "GLD": ["gold"],
    "SLV": ["silver"],
    "GDX": ["gold miners"],
    "USO": ["oil prices", "crude oil"],
    "UNG": ["natural gas"],
    "URA": ["uranium"],
    # Cryptos
    "BTC-USD": ["Bitcoin", "BTC"],
    "ETH-USD": ["Ethereum", "Ether"],
    "SOL-USD": ["Solana"],
    "XRP-USD": ["XRP", "Ripple"],
}

# Orthographe de presse quand elle diffère du libellé de l'univers (« BankOfAmerica » s'écrit « Bank of America », « ATT » s'écrit
# « AT&T »). Casse respectée comme pour les noms ; limité aux actifs réellement présents dans l'univers.
NAME_ALIASES: dict[str, list[str]] = {
    "JNJ": ["Johnson & Johnson", "J&J"],
    "PG": ["Procter & Gamble", "P&G"],
    "BRK-B": ["Berkshire Hathaway"],
    "BAC": ["Bank of America"],
    "T": ["AT&T"],
    "MCD": ["McDonald's", "McDonald’s"],
    "LOW": ["Lowe's", "Lowe’s"],
    "KO": ["Coca-Cola", "Coca Cola"],
    "OR.PA": ["L'Oréal", "L’Oréal", "L'Oreal"],
    "RMS.PA": ["Hermès"],
    "BNP.PA": ["BNP Paribas"],
    "GE": ["GE Aerospace", "General Electric"],
    "GOOGL": ["Google"],
    "GOOG": ["Google"],
    "XOM": ["Exxon Mobil", "Exxon"],
    "JPM": ["JPMorgan Chase"],
    "TTE.PA": ["Total Energies"],
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


def _is_acronym(alias: str) -> bool:
    """Sigle écrit en majuscules (« DAX », « OPEC », « S&P 500 ») : à reconnaître avec sa casse."""
    letters = [c for c in alias if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)


class EntityLinker:
    def __init__(self, names: dict[str, str] | None = None, themes: dict[str, list[str]] | None = None,
                 aliases: dict[str, list[str]] | None = None):
        self._symbols = set(names or {}) | set(themes or {}) | set(aliases or {})
        self._by_cashtag = {s.upper(): s for s in self._symbols}
        self._stocks = {s.upper(): s for s in set(names or {}) | set(aliases or {})}
        self._names: list[tuple[str, re.Pattern]] = []
        for symbol, label in (names or {}).items():
            for variant in label_variants(label):
                self._names.append((symbol, _boundary(variant)))
        for symbol, spellings in (aliases or {}).items():
            for spelling in spellings:
                self._names.append((symbol, _boundary(spelling)))
        self._themes: list[tuple[str, re.Pattern]] = []
        for symbol, words in (themes or {}).items():
            for alias in words:
                self._themes.append((symbol, _boundary(alias, 0 if _is_acronym(alias) else re.IGNORECASE)))

    def link(self, text: str) -> list[tuple[str, str]]:
        """[(symbole, méthode)], un seul lien par symbole (la méthode la plus sûre l'emporte), triés par symbole."""
        text = text or ""
        found: dict[str, str] = {}
        for raw in _CASHTAG.findall(text):
            symbol = self._by_cashtag.get(raw.rstrip(".-").upper())
            if symbol:
                found[symbol] = "cashtag"
        for raw in _EXCHANGE_TICKER.findall(text):
            symbol = self._stocks.get(raw.upper())
            if symbol and symbol not in found:
                found[symbol] = "ticker"
        for symbol, rx in self._names:
            if symbol not in found and rx.search(text):
                found[symbol] = "name"
        for symbol, rx in self._themes:
            if symbol not in found and rx.search(text):
                found[symbol] = "theme"
        return sorted(found.items())


def universe_linker(groups: dict[str, list[tuple[str, str]]] | None = None) -> EntityLinker:
    """Linker de l'univers suivi : noms des actions et cryptos (libellés de `all_target_groups`) + orthographes de presse + thèmes
    curatés, limités aux actifs réellement présents dans l'univers."""
    if groups is None:
        from patrick.config.universe_extension import all_target_groups

        groups = all_target_groups()
    known = {sym for items in groups.values() for sym, _ in items}
    names = {sym: label for group, items in groups.items() if group.startswith(("Actions", "Crypto"))
             for sym, label in items}
    themes = {sym: aliases for sym, aliases in THEME_ALIASES.items() if sym in known}
    aliases = {sym: spellings for sym, spellings in NAME_ALIASES.items() if sym in names}
    return EntityLinker(names=names, themes=themes, aliases=aliases)
