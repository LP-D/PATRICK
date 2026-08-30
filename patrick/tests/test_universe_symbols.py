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


def test_the_two_historical_typos_never_reappear():
    """Non-régression sur deux corrections passées (L3HARRIS -> LHX,
    CBOT_W -> WEAT). Réduction d'univers (feature/universe-reduction) :
    "Actions individuelles" (portait LHX) et "Matières premières & devises
    (ETFs)" (portait WEAT) sont retirés en intégralité -- plus aucun des
    deux tickers, correct ou fautif, n'est dans l'univers aujourd'hui. La
    partie encore vérifiable et utile de ce garde-fou : si l'un de ces
    groupes est un jour réintroduit, la forme fautive ne doit pas y
    revenir. La présence de la forme correcte n'est plus un invariant --
    ce n'est plus l'un des groupes actuellement chargés."""
    symbols = {s for _, s, _ in _yfinance_symbols()}
    assert "L3HARRIS" not in symbols
    assert "CBOT_W" not in symbols


# Univers cible de la réduction (feature/universe-reduction) : commodités
# (futures) + macro (FRED) + 4 actifs conservés explicitement (VIX, EUR/USD,
# S&P500, BTC). Répété ici en dur (pas dérivé de D.DEFAULT_TARGET_GROUPS) —
# le point du test est justement de détecter un écart entre ce qui est
# CHARGÉ au runtime et ce qui était VOULU, une assertion qui se contente de
# relire la même source qu'elle vérifie ne détecterait rien.
_EXPECTED_INDICES = {"^GSPC", "^VIX"}
_EXPECTED_DEVISES = {"EURUSD=X"}
_EXPECTED_CRYPTO = {"BTC-USD"}
_EXPECTED_COMMODITIES_FUTURES = {
    "GC=F", "SI=F", "HG=F", "CL=F", "BZ=F", "NG=F", "ZC=F", "ZO=F", "KE=F",
    "ZR=F", "ZS=F", "GF=F", "HE=F", "LE=F", "CC=F", "KC=F", "CT=F", "LBS=F",
    "OJ=F", "SB=F",
}
_EXPECTED_MACRO_FRED = {
    "BAMLC0A0CM", "BAMLC0A4CBBB", "BAMLH0A0HYM2", "CPIAUCSL", "CPILFESL",
    "DCOILBRENTEU", "DCOILWTICO", "DFF", "DGS1", "DGS10", "DGS2", "DGS20",
    "DGS3", "DGS30", "DGS5", "DGS7", "DTB1", "DTB3", "DTB6", "EFFR",
    "FEDFUNDS", "GDP", "INDPRO", "NFCI", "OILPRICE", "PAYEMS", "PCE",
    "PCEPILFE", "RSAFS", "SOFR", "SP500", "STLFSI4", "T10Y2Y", "T10Y3M",
    "T10YIE", "T5YIE", "T5YIFR", "TEDRATE", "UMCSENT", "UNRATE", "VIXCLS",
    "VIXDVOL", "WILL5000IND",
}


def test_universe_matches_exactly_the_reduced_target_set():
    """Non-régression explicite (Phase 4, feature/universe-reduction) : la
    liste d'univers chargée au runtime doit correspondre EXACTEMENT à la
    liste attendue -- 67 cibles (20 commodités futures + 43 macro FRED + 2
    indices + 1 devise + 1 crypto), pas "à peu près" (un ticker en trop ou
    en moins passerait inaperçu avec une simple assertion de longueur)."""
    groups = D.DEFAULT_TARGET_GROUPS
    assert set(groups.keys()) == {"Indices", "Devises", "Matières premières (futures)", "Crypto", "Macro (FRED)"}

    actual_indices = {s for s, _ in groups["Indices"]}
    actual_devises = {s for s, _ in groups["Devises"]}
    actual_crypto = {s for s, _ in groups["Crypto"]}
    actual_commodities = {s for s, _ in groups["Matières premières (futures)"]}
    actual_macro = {s for s, _ in groups["Macro (FRED)"]}

    assert actual_indices == _EXPECTED_INDICES
    assert actual_devises == _EXPECTED_DEVISES
    assert actual_crypto == _EXPECTED_CRYPTO
    assert actual_commodities == _EXPECTED_COMMODITIES_FUTURES
    assert actual_macro == _EXPECTED_MACRO_FRED

    all_expected = (_EXPECTED_INDICES | _EXPECTED_DEVISES | _EXPECTED_CRYPTO
                    | _EXPECTED_COMMODITIES_FUTURES | _EXPECTED_MACRO_FRED)
    assert len(all_expected) == 67
    all_actual = {s for s, _, _ in D.DEFAULT_TARGET_CHOICES}
    assert all_actual == all_expected

    # Cohérence avec l'univers de features (dérivé de la même source,
    # config/schema.py::DEFAULT_UNIVERSE_YF_TICKERS/DEFAULT_UNIVERSE_FRED_SERIES).
    assert set(D.DEFAULT_UNIVERSE_YF_TICKERS) == (
        _EXPECTED_INDICES | _EXPECTED_DEVISES | _EXPECTED_CRYPTO | _EXPECTED_COMMODITIES_FUTURES
    )
    assert set(D.DEFAULT_UNIVERSE_FRED_SERIES.values()) == _EXPECTED_MACRO_FRED
