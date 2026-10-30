"""Actions : historiques courts déclarés et reconnaissance d'un symbole d'action.

Il n'y a plus de groupe « Actions individuelles » : chaque action est dans son vrai groupe (`config/universe_extension.py` :
US, France, Allemagne, Royaume-Uni, Europe, Asie), traitée comme les autres. Reste ici ce qui ne tient pas dans un groupe :
les titres sans assez d'historique (introduction en bourse récente) et leur indice de substitution pour estimer le risque.

D.A.T.E (ALDAT.PA, Euronext Growth Paris) : cotée depuis le 2026-09-25 (Yahoo la sert depuis cette date). Aucun indice petites
valeurs n'existe chez Yahoo (^CACS, ^CACMS : 404) ; ^FCHI est le substitut disponible. Le multiplicateur de volatilité est un a priori
(petite capitalisation face à un grand indice), remplacé par l'estimation dès qu'il y a 20 séances communes
(`tracking/covariance.py::backfill_with_proxy`).
"""
from __future__ import annotations

HISTORY_PROXIES_DECLARED: dict[str, dict] = {
    "ALDAT.PA": {"proxy": "^FCHI", "proxy_vol_multiplier": 2.0},
}


def history_proxies() -> dict[str, tuple[str, float | None]]:
    """{symbol: (proxy symbol, prior vol multiplier)} for assets declared
    without enough history (roadmap bloc 4)."""
    return {sym: (meta["proxy"], meta.get("proxy_vol_multiplier")) for sym, meta in HISTORY_PROXIES_DECLARED.items()}


def equity_symbols() -> frozenset[str]:
    """Tous les symboles d'action de l'univers : ceux des groupes de la classe « equity » (`config/asset_classes.py`)."""
    from patrick.config import universe_extension as UX
    from patrick.config.asset_classes import BY_KEY

    groups = BY_KEY["equity"].groups
    return frozenset(sym for g in groups for sym, _label, _first in UX.EXTENDED_TARGET_GROUPS.get(g, ()))


def is_equity_symbol(symbol: str) -> bool:
    return symbol in equity_symbols()
