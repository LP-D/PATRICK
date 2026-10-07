"""Roadmap bloc 4 -- verified extended universe: targets only, never the
default feature pool of every run."""
from __future__ import annotations

from fastapi.testclient import TestClient

from patrick.config import defaults as D
from patrick.config import equity_universe as EQ
from patrick.config import universe_extension as UX
from patrick.webapp import forms
from patrick.webapp.app import app


def test_extension_is_selectable_but_not_a_feature():
    ext = {s for s, _, _ in UX.extended_target_choices()}
    assert len(ext) >= 100
    assert all(forms.TARGET_SOURCE_BY_SYMBOL[s] == "yfinance" for s in ext)
    assert not ext & set(D.DEFAULT_UNIVERSE_YF_TICKERS)
    yf, _fred = forms.universe_excluding("XLK")
    assert sorted(yf) == sorted(D.DEFAULT_UNIVERSE_YF_TICKERS)
    assert not ext & set(EQ.EQUITY_UNIVERSE)


def test_group_names_never_overwrite_an_existing_group():
    assert not set(UX.EXTENDED_TARGET_GROUPS) & set(D.DEFAULT_TARGET_GROUPS)
    assert EQ.EQUITY_TARGET_GROUP not in UX.EXTENDED_TARGET_GROUPS
    merged = UX.all_target_groups()
    assert merged["Crypto"] == D.DEFAULT_TARGET_GROUPS["Crypto"]


def test_rejected_tickers_are_not_in_the_extension():
    ext = {s for s, _, _ in UX.extended_target_choices()}
    assert not ext & set(UX.EXCLUDED_AT_VERIFICATION)


def test_launch_and_universe_pages_list_the_extension(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "p.db"))
    client = TestClient(app)
    assert 'value="MC.PA"' in client.get("/launch").text
    universe = client.get("/universe").text
    assert "XLK" in universe and "Actions France (CAC 40)" in universe


def test_extended_candidates_are_verified_extension_symbols_outside_the_default_pool():
    """The branch's 39 candidates and main's verified extension, merged:
    one source of truth. Still never part of the DEFAULT feature pool."""
    extension = {s for s, _, _ in UX.extended_target_choices()}
    assert len(UX.EXTENDED_FEATURE_CANDIDATES) == 39 == len(set(UX.EXTENDED_FEATURE_CANDIDATES))
    assert set(UX.EXTENDED_FEATURE_CANDIDATES) <= extension
    assert set(UX.ADDED_ON_2026_09_27) <= extension
    assert not set(UX.EXTENDED_FEATURE_CANDIDATES) & set(D.DEFAULT_UNIVERSE_YF_TICKERS)
    assert not set(UX.extended_candidate_yf_tickers()) & D.BAD_TICKERS
    assert UX.extended_candidate_yf_tickers()[:len(D.DEFAULT_UNIVERSE_YF_TICKERS)] == D.DEFAULT_UNIVERSE_YF_TICKERS
    assert len(D.DEFAULT_TARGET_CHOICES) == 64


def test_individual_equity_groups_added_on_2026_10_07_are_selectable_translated_and_unique():
    """Actions individuelles de l'extension : ciblables au lancement,
    traduites, sans doublon ni cotation double, jamais dans le pool de features."""
    from patrick.webapp import i18n

    groups = {g: items for g, items in UX.EXTENDED_TARGET_GROUPS.items() if g in UX.ADDED_ON_2026_10_07_GROUPS}
    assert set(groups) == set(UX.ADDED_ON_2026_10_07_GROUPS)
    symbols = [s for items in groups.values() for s, _, _ in items]
    assert len(symbols) >= 250 and len(symbols) == len(set(symbols))
    assert {"TSLA", "SAP.DE", "SHEL.L", "ASML.AS", "NESN.SW", "ACA.PA", "7203.T"} <= set(symbols)
    # une seule ligne par société (pas de cotation double Unilever / Stellantis / TSMC)
    assert not {"UNA.AS", "STLAM.MI", "2330.TW"} & set(symbols)
    every = [s for items in UX.EXTENDED_TARGET_GROUPS.values() for s, _, _ in items]
    assert len(every) == len(set(every)), "symbole en double dans l'extension"
    assert not set(symbols) & (set(D.DEFAULT_UNIVERSE_YF_TICKERS) | set(EQ.EQUITY_UNIVERSE) | D.BAD_TICKERS)
    assert all(g in i18n.TARGET_GROUP_LABEL_KEYS for g in UX.all_target_groups())
    for g in groups:
        key = i18n.TARGET_GROUP_LABEL_KEYS[g]
        assert i18n.STRINGS[key]["fr"] == g and i18n.STRINGS[key]["en"]
    for _, label, first in (row for items in groups.values() for row in items):
        assert label.replace("_", "").isalnum() and first[:4].isdigit()
