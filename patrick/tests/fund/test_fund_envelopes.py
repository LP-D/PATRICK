"""Fonds, enveloppes : ce qu'un PEA peut détenir (ADR 0026). Calcul pur, aucun réseau."""
from __future__ import annotations

import pytest

from patrick.config import universe_extension as UX
from patrick.fund import envelopes
from patrick.wealth.ledger import PEA_LIKELY_ELIGIBLE_SUFFIXES

GROUPS = {"SPY": "ETFs sectoriels & thématiques", "EWG": "International (ETFs pays)", "MC.PA": "Actions France (CAC 40)"}


@pytest.mark.parametrize("symbol", ["MC.PA", "TTE.PA", "SAP.DE", "ASML.AS", "SAN.MC", "ENEL.MI", "NOKIA.HE", "ABI.BR", "EDP.LS", "VER.VI"])
def test_a_euro_share_of_an_eu_venue_is_eligible(symbol):
    assert envelopes.pea_eligibility(symbol) is None


@pytest.mark.parametrize("symbol, code", [
    ("AAPL", "pea_zone"), ("MSFT", "pea_zone"),                       # États-Unis
    ("HSBA.L", "pea_zone"), ("VOD.L", "pea_zone"),                    # Royaume-Uni : hors UE
    ("NESN.SW", "pea_zone"), ("NOVN.SW", "pea_zone"),                 # Suisse : hors UE/EEE
    ("7203.T", "pea_zone"), ("0700.HK", "pea_zone"),                  # Asie
    ("VOLV-B.ST", "pea_devise"), ("NOVO-B.CO", "pea_devise"), ("EQNR.OL", "pea_devise"),    # UE/EEE, mais pas en euro
])
def test_a_share_outside_the_euro_area_is_excluded_with_its_reason(symbol, code):
    assert envelopes.pea_eligibility(symbol) == code


@pytest.mark.parametrize("symbol", ["^GSPC", "^FCHI", "EURUSD=X", "GC=F", "CL=F", "BTC-USD", "ETH-USD", "DX-Y.NYB"])
def test_indices_currencies_commodities_and_crypto_are_never_eligible(symbol):
    assert envelopes.pea_eligibility(symbol) == envelopes.PEA_NOT_A_SHARE


def test_etfs_are_excluded_even_when_their_venue_is_european():
    assert envelopes.pea_eligibility("SPY", GROUPS) == envelopes.PEA_ETF
    assert envelopes.pea_eligibility("EWG", GROUPS) == envelopes.PEA_ETF
    assert envelopes.pea_eligibility("MC.PA", GROUPS) is None


def test_the_suffix_lists_come_from_the_ledger_and_split_it_by_currency():
    assert set(envelopes.PEA_EURO_SUFFIXES) | set(envelopes.PEA_NON_EURO_SUFFIXES) == set(PEA_LIKELY_ELIGIBLE_SUFFIXES)
    assert not set(envelopes.PEA_EURO_SUFFIXES) & set(envelopes.PEA_NON_EURO_SUFFIXES)
    assert ".L" not in PEA_LIKELY_ELIGIBLE_SUFFIXES and ".SW" not in PEA_LIKELY_ELIGIBLE_SUFFIXES


def test_the_pea_groups_exist_in_the_universe_and_leave_out_the_uk():
    universe = UX.all_target_groups()

    assert all(group in universe for group in envelopes.PEA_GROUPS)
    assert "Actions Royaume-Uni" not in envelopes.PEA_GROUPS


def test_what_the_pea_universe_keeps_and_drops_is_explained_for_every_symbol():
    """Dans les groupes du PEA : France et Allemagne passent toutes, les valeurs suisses et nordiques sont écartées une à une avec leur motif."""
    universe = UX.all_target_groups()
    verdicts = {sym: envelopes.pea_eligibility(sym) for group in envelopes.PEA_GROUPS for sym, _ in universe[group]}

    assert all(verdicts[sym] is None for group in ("Actions France (CAC 40)", "Actions France (autres valeurs)", "Actions Allemagne")
               for sym, _ in universe[group])
    assert {sym: code for sym, code in verdicts.items() if code} and set(verdicts.values()) <= {None, "pea_zone", "pea_devise"}
    assert verdicts["NESN.SW"] == "pea_zone" and verdicts["VOLV-B.ST"] == "pea_devise" and verdicts["ASML.AS"] is None
    assert sum(1 for code in verdicts.values() if code is None) >= 100
