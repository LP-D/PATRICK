"""Alignement temporel par classe d'actif (Phase 0.4) : les DataFrames de ce
projet sont indexés par DATE CALENDAIRE (barres quotidiennes yfinance), sans
horodatage de clôture — une jointure "même date" traite implicitement une
clôture Tokyo (~08:00 UTC) et une clôture New York (~20:00-21:00 UTC) du même
jour calendaire comme simultanées. C'est correct dans un sens (Tokyo clôture
avant New York le même jour, l'utiliser en feature "du jour" pour une cible US
est légitime) mais faux dans l'autre : une feature dont la clôture "du jour"
arrive APRÈS la clôture de la cible contient de l'information non encore
disponible au moment de la décision.

Sans horodatages intrajournaliers réels (hors de portée avec des barres
quotidiennes yfinance — les obtenir demanderait de migrer toute l'ingestion sur
des données horaires, hors périmètre ici), la correction appliquée est un
décalage d'un jour ouvré : toute feature dont la classe d'actif clôture
(heure UTC approximative) APRÈS celle de la cible est retardée d'une barre
avant d'être jointe — c'est-à-dire qu'à la date D, la feature utilisée est sa
valeur connue à D-1 (déjà entièrement écoulée avant la clôture de la cible),
pas sa valeur "du jour" (pas encore connue). Approximation documentée,
meilleure que l'absence totale d'alignement, pas équivalente à un vrai as-of
join intrajournalier.
"""
from __future__ import annotations

# Heure de clôture UTC approximative par classe d'actif (échelle 0-24, valeur la
# plus tardive de la classe — conservateur : en cas de doute, on suppose une
# clôture tardive, ce qui décale PLUS de features plutôt que moins, quitte à
# perdre un peu de fraîcheur, jamais à laisser fuiter de l'information).
CLOSE_UTC_HOUR = {
    "crypto": 24.0,           # 24/7, la barre "du jour" n'est complète qu'en fin de journée UTC
    "fx": 22.0,                # convention clôture NY ~17h ET
    "futures": 21.0,           # règlement CME/ICE, fin d'après-midi US
    "equities_us": 20.0,       # NYSE/NASDAQ ~16h ET
    "equities_americas_other": 21.0,
    "equities_europe": 16.5,   # Paris/Francfort/Londres ~16h30-17h30 UTC
    "equities_asia_pacific": 8.0,   # Tokyo/HK/Shanghai/Sydney, la plus précoce
    "other": 24.0,              # inconnu -> traité comme le plus tardif (conservateur)
}

_EU_SUFFIXES = (".PA", ".DE", ".AS", ".BR", ".MI", ".MC", ".LS", ".VI", ".L",
                ".IR", ".SW", ".ST", ".HE", ".CO", ".OL")
_ASIA_SUFFIXES = (".HK", ".T", ".SS", ".SZ", ".KS", ".TW", ".SI", ".JK", ".KL",
                   ".BO", ".NS", ".AX", ".NZ")
_AMERICAS_OTHER_SUFFIXES = (".SA", ".MX", ".TO", ".BA")

# Indices ("^"-préfixés) classés individuellement (le suffixe seul ne suffit
# pas à distinguer leur région) — non exhaustif : tout indice absent retombe
# sur "other" (traitement conservateur, cf. CLOSE_UTC_HOUR["other"]).
_INDEX_REGION = {
    "^GSPC": "equities_us", "^DJI": "equities_us", "^IXIC": "equities_us",
    "^RUT": "equities_us", "^NYA": "equities_us", "^XAX": "equities_us",
    "^VIX": "equities_us", "^VXN": "equities_us", "^OVX": "equities_us",
    "^GVZ": "equities_us", "^EVZ": "equities_us",
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
    """Classe d'actif d'un symbole yfinance, par motif de ticker — heuristique
    volontairement simple (pas de dépendance à un référentiel externe)."""
    if source != "yfinance":
        return "other"
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
    """1 si la feature doit être retardée d'une barre avant d'être jointe à la
    cible (sa clôture "du jour" arrive après celle de la cible -> pas encore
    connue au moment de la décision), 0 sinon. Toujours 0 si la cible elle-même
    n'est pas yfinance (FRED : sa propre correction temporelle est le sujet de
    la Phase 0.5, pas de celle-ci — cf. docstring de module)."""
    if target_source != "yfinance":
        return 0
    feature_class = classify_asset_class(feature_symbol, feature_source)
    target_class = classify_asset_class(target_symbol, target_source)
    return 1 if CLOSE_UTC_HOUR[feature_class] > CLOSE_UTC_HOUR[target_class] else 0
