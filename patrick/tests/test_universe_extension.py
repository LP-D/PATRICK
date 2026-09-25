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
