"""Benchmark d'une cible alpha : déterminé automatiquement d'après la classe
d'actif et la région du symbole, ou choisi à la main (le choix manuel l'emporte
toujours).

La classification est celle du pipeline (`data.session_calendar.classify_asset_class`) :
pas de seconde table à maintenir. Le résultat porte sa raison (affichable) et
sa provenance (`auto` | `manual`), à enregistrer avec le run pour qu'il reste
reproductible même si cette table évolue.

Règles (benchmark = ce qu'un investisseur passif de la même classe et région
détiendrait) :

| classe / région                                   | benchmark    |
|---------------------------------------------------|--------------|
| actions États-Unis                                | ^GSPC        |
| actions zone euro, Suisse, Nordiques              | ^STOXX50E    |
| actions Royaume-Uni                               | ^FTSE        |
| actions Japon / Hong Kong / Australie / Corée ... | ^N225 / ^HSI / ^AXJO / ^KS11 ... |
| actions Canada / Brésil / Mexique / Argentine     | ^GSPTSE / ^BVSP / ^MXX / ^MERV |
| crypto                                            | BTC-USD      |
| matières premières (contrats `=F`)                | DBC          |
| autre                                             | URTH (monde) |

Quand le benchmark calculé serait la cible elle-même, on remonte d'un cran
(monde, `URTH`) ; si c'est encore elle-même, ou si aucun benchmark n'a de sens
(change, indice de volatilité, série macro, bitcoin lui-même), l'erreur
l'explique et propose le choix manuel.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from patrick.data.session_calendar import _INDEX_REGION, classify_asset_class

WORLD = "URTH"

_TICKER_RE = re.compile(r"^[A-Z0-9^][A-Z0-9.=^_-]{0,29}$")

# Suffixe de place -> (benchmark, région affichée)
_SUFFIX_BENCHMARK: tuple[tuple[tuple[str, ...], str, str], ...] = (
    ((".PA", ".DE", ".AS", ".BR", ".MI", ".MC", ".LS", ".VI", ".IR", ".HE"), "^STOXX50E", "zone euro"),
    ((".L",), "^FTSE", "Royaume-Uni"),
    ((".SW", ".ST", ".CO", ".OL"), "^STOXX50E", "Europe hors zone euro (approximation : grandes valeurs de la zone euro)"),
    ((".T",), "^N225", "Japon"),
    ((".HK",), "^HSI", "Hong Kong"),
    ((".AX", ".NZ"), "^AXJO", "Australie / Nouvelle-Zélande"),
    ((".KS",), "^KS11", "Corée du Sud"),
    ((".SS", ".SZ"), "000001.SS", "Chine continentale"),
    ((".TW",), "^TWII", "Taïwan"),
    ((".BO", ".NS"), "^NSEI", "Inde"),
    ((".SI",), "^STI", "Singapour"),
    ((".TO",), "^GSPTSE", "Canada"),
    ((".SA",), "^BVSP", "Brésil"),
    ((".MX",), "^MXX", "Mexique"),
    ((".BA",), "^MERV", "Argentine"),
)

# Indices : région de l'indice (on ne se base pas sur un suffixe)
_INDEX_BENCHMARK = {
    "equities_us": ("^GSPC", "actions américaines"),
    "equities_europe": ("^STOXX50E", "actions de la zone euro"),
}


class BenchmarkError(ValueError):
    """Aucun benchmark possible, ou choix manuel invalide (message affichable)."""


@dataclass(frozen=True)
class Benchmark:
    symbol: str
    source: str            # "auto" | "manual"
    reason: str


def _norm(symbol: str) -> str:
    return (symbol or "").strip().upper()


def _fallback(target: str, candidate: str, why: str) -> Benchmark:
    """`candidate`, ou le monde quand ce serait la cible elle-même."""
    if candidate.upper() != target:
        return Benchmark(candidate, "auto", why)
    if target != WORLD:
        return Benchmark(WORLD, "auto", f"{why}, mais c'est la cible elle-même : repli sur le monde ({WORLD})")
    raise BenchmarkError(f"{target} : benchmark automatique impossible (c'est le benchmark mondial) ; "
                         "choisir un benchmark manuellement.")


def auto_benchmark(target_symbol: str, source: str = "yfinance") -> Benchmark:
    target = _norm(target_symbol)
    none_msg = "choisir un benchmark manuellement ou garder la cible brute"
    if source != "yfinance":
        raise BenchmarkError(f"{target} : série macro, pas de benchmark automatique ; {none_msg}.")
    klass = classify_asset_class(target, source)
    if klass == "volatility_index":
        raise BenchmarkError(f"{target} : indice de volatilité, un rendement excédentaire n'a pas de sens ; {none_msg}.")
    if klass == "fx":
        raise BenchmarkError(f"{target} : change, pas de benchmark naturel ; {none_msg}.")
    if klass == "crypto":
        if target == "BTC-USD":
            raise BenchmarkError(f"{target} : c'est la référence du marché crypto ; {none_msg}.")
        return _fallback(target, "BTC-USD", "crypto : référence du marché crypto")
    if klass == "futures":
        return _fallback(target, "DBC", "matière première : indice large de matières premières")
    if target.startswith("^") or target in _INDEX_REGION:
        symbol, label = _INDEX_BENCHMARK.get(klass, (None, None))
        if symbol and symbol != target:
            return Benchmark(symbol, "auto", f"indice : {label}")
        return _fallback(target, WORLD, "indice : marché mondial")
    for suffixes, symbol, region in _SUFFIX_BENCHMARK:
        if target.endswith(suffixes):
            return _fallback(target, symbol, f"action cotée en {region}")
    if klass == "equities_us":
        return _fallback(target, "^GSPC", "action américaine")
    return _fallback(target, WORLD, "classe d'actif non reconnue : marché mondial")


def resolve_benchmark(target_symbol: str, override: str | None = None, source: str = "yfinance") -> Benchmark:
    """Choix manuel s'il est donné (et valide), sinon détermination automatique."""
    target = _norm(target_symbol)
    chosen = _norm(override or "")
    if not chosen:
        return auto_benchmark(target, source)
    if not _TICKER_RE.fullmatch(chosen):
        raise BenchmarkError(f"benchmark invalide : {override!r}")
    if chosen == target:
        raise BenchmarkError(f"{chosen} : le benchmark ne peut pas être la cible lui-même.")
    return Benchmark(chosen, "manual", f"benchmark choisi à la main : {chosen}")
