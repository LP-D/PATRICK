"""Rattachement news -> actif (entity linking) : précision d'abord, un faux lien vaut pire qu'un lien manqué."""
from __future__ import annotations

from patrick.text import entities


def _linker():
    return entities.EntityLinker(
        names={"AAPL": "Apple", "AD.AS": "AholdDelhaize", "ING": "ING", "ORA.PA": "Orange", "MC.PA": "LVMH"},
        themes={"GC=F": ["gold"], "CL=F": ["WTI", "crude oil", "oil prices"], "BZ=F": ["Brent", "oil prices"],
                "BTC-USD": ["Bitcoin", "BTC"], "^GSPC": ["S&P 500", "S&P500"]},
    )


def _symbols(text):
    return {s for s, _ in _linker().link(text)}


def test_cashtag_links_whatever_the_case_of_the_text():
    assert ("AAPL", "cashtag") in _linker().link("$AAPL jumps after earnings")
    assert _symbols("buying $aapl and $mc.pa today") == {"AAPL", "MC.PA"}


def test_company_name_must_be_capitalised_to_avoid_common_words():
    assert _symbols("Apple unveils a new phone") == {"AAPL"}
    assert _symbols("grandma's apple pie recipe") == set()


def test_camel_case_labels_become_words():
    assert _symbols("Ahold Delhaize reports quarterly results") == {"AD.AS"}
    assert _symbols("AholdDelhaize reports quarterly results") == {"AD.AS"}


def test_short_names_need_exact_uppercase():
    assert _symbols("ING raises its dividend") == {"ING"}
    assert _symbols("the king is dying and singing") == set()


def test_themes_match_case_insensitively_on_whole_words():
    assert _symbols("Gold hits a record as bitcoin slides") == {"GC=F", "BTC-USD"}
    assert _symbols("a goldfish and a golden retriever") == set()
    assert _symbols("The S&P 500 closes higher") == {"^GSPC"}


def test_an_ambiguous_theme_links_every_asset_it_names():
    assert _symbols("Oil prices fall") == {"CL=F", "BZ=F"}
    assert _symbols("Brent settles at $80") == {"BZ=F"}


def test_text_about_nothing_links_nothing():
    assert _linker().link("The committee will meet next week") == []


def test_labels_are_split_and_suffixes_dropped():
    assert entities.label_variants("AholdDelhaize") == ["AholdDelhaize", "Ahold Delhaize"]
    assert entities.label_variants("Gold_Futures") == ["Gold"]
    assert entities.label_variants("UST_10Y_Yield") == []


def test_universe_linker_knows_the_tracked_equities_and_commodities():
    linker = entities.universe_linker()
    syms = {s for s, _ in linker.link("Nvidia and LVMH rally while Brent and gold rise")}
    assert {"NVDA", "MC.PA", "BZ=F", "GC=F"} <= syms
