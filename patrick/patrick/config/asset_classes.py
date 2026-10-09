"""Classes d'actifs de l'application : UNE table qui dit, pour chaque groupe de cibles (`config/defaults.py`,
`config/equity_universe.py`, `config/universe_extension.py`), à quelle page de la navigation il appartient.

Avant la refonte du 2026-10-09 seules trois classes avaient une page (matières premières, macro, « Actions
individuelles »), alors que le sélecteur de cibles en propose 474 réparties en 22 groupes : indices, cryptos, devises, taux
et ETF n'avaient aucune page. Chaque groupe appartient maintenant à une classe, et un test vérifie qu'aucun groupe n'est
oublié (`tests/test_asset_classes.py`) : un groupe ajouté demain sans classe fait échouer la suite.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AssetClass:
    key: str
    url: str
    groups: tuple[str, ...]          # noms internes des groupes (clés de `forms.TARGET_GROUPS`)
    nav_order: int
    glossary_term: str               # entrée du vocabulaire qui définit la classe


ASSET_CLASSES: tuple[AssetClass, ...] = (
    AssetClass("equity", "/equity", (
        "Actions individuelles", "Actions US (méga-capitalisations)", "Actions France (CAC 40)",
        "Actions US (grandes capitalisations)", "Actions France (autres valeurs)", "Actions Allemagne",
        "Actions Royaume-Uni", "Actions Europe (autres pays)", "Actions Asie (locales & ADR)"), 20, "asset_equity"),
    AssetClass("indices", "/indices", ("Indices", "Indices mondiaux", "Volatilité"), 30, "asset_index"),
    AssetClass("crypto", "/crypto", ("Crypto", "Crypto (majeures)"), 40, "asset_crypto"),
    AssetClass("fx", "/fx", ("Devises", "Devises (majeures)"), 50, "asset_fx"),
    AssetClass("rates", "/rates", ("Taux US (indices CBOE)", "Obligataire & taux (ETFs)"), 60, "asset_rates"),
    AssetClass("commodities", "/commodities", ("Matières premières (futures)", "Matières premières (compléments)"), 70,
               "asset_commodity"),
    AssetClass("etfs", "/etfs", ("ETFs sectoriels & thématiques", "International (ETFs pays)", "ETFs larges & style"), 80,
               "asset_etf"),
    AssetClass("macro", "/macro", ("Macro (FRED)",), 90, "training_only"),
)

BY_KEY: dict[str, AssetClass] = {c.key: c for c in ASSET_CLASSES}
CLASS_OF_GROUP: dict[str, str] = {g: c.key for c in ASSET_CLASSES for g in c.groups}


def class_of_group(group: str) -> str | None:
    return CLASS_OF_GROUP.get(group)
