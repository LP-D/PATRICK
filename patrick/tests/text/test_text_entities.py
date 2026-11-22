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


def _universe_linker():
    groups = {
        "Actions US (grandes capitalisations)": [("BAC", "BankOfAmerica"), ("T", "ATT"), ("MCD", "McDonalds"), ("JNJ", "Johnson_Johnson"),
                                                ("GOOGL", "Alphabet"), ("JPM", "JPMorgan"), ("AAPL", "Apple")],
        "Indices mondiaux": [("^GDAXI", "DAX"), ("^N225", "Nikkei"), ("^FTSE", "FTSE")],
        "Devises (majeures)": [("USDJPY=X", "USDJPY"), ("GBPUSD=X", "GBPUSD"), ("DX-Y.NYB", "Dollar")],
        "Matières premières (futures)": [("CL=F", "WTI_Futures"), ("BZ=F", "Brent_Futures")],
        "Taux US (indices CBOE)": [("^TNX", "US10Y")],
    }
    return entities.universe_linker(groups)


def _universe_symbols(text):
    return {s for s, _ in _universe_linker().link(text)}


def test_press_spelling_of_a_company_links_even_when_the_universe_label_is_different():
    assert _universe_symbols("Bank of America and JPMorgan Chase beat estimates") == {"BAC", "JPM"}
    assert _universe_symbols("AT&T raises its dividend; McDonald's and Johnson & Johnson follow") == {"T", "MCD", "JNJ"}
    assert _universe_symbols("Google unveils a new model") == {"GOOGL"}
    assert _universe_symbols("bank of america") == set()                    # casse respectée comme pour tout nom


def test_a_ticker_after_its_exchange_links_but_a_bare_uppercase_word_does_not():
    assert _universe_linker().link("Shares of the maker (NASDAQ: AAPL) rose") == [("AAPL", "ticker")]
    assert _universe_symbols("NYSE: JPM and NYSE American: T") == {"JPM", "T"}
    assert _universe_symbols("The CEO said the IT team is AI ready (T) ") == set()
    assert _universe_symbols("NASDAQ: ZZZZ") == set()                       # hors univers


def test_indices_currencies_and_rates_are_linked_by_theme():
    assert _universe_symbols("Nikkei closes higher while the yen weakens") == {"^N225", "USDJPY=X"}
    assert _universe_symbols("Treasury yields climb as the dollar firms") == {"^TNX", "DX-Y.NYB"}
    assert _universe_symbols("Sterling slides after the FTSE 100 opens lower") == {"GBPUSD=X", "^FTSE"}
    assert _universe_symbols("OPEC+ meeting lifts crude") == {"CL=F", "BZ=F"}


def test_acronym_themes_need_their_capitals_but_words_do_not():
    assert _universe_symbols("The DAX gained 1%") == {"^GDAXI"}
    assert _universe_symbols("Dax Shepard joins the cast") == set()
    assert _universe_symbols("opec meets") == set()
    assert _universe_symbols("Brent and BRENT and brent") == {"BZ=F"}


def test_ambiguous_everyday_words_are_not_themes():
    assert _universe_symbols("Cable news ratings fall") == set()                            # « cable » seul ne désigne pas la livre
    assert _universe_symbols("The euro zone and the single currency") == set()
