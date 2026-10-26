"""Noms d'affichage des instruments : la règle (société et ETF = nom seul ; futures, CFD, indices, devises, cryptos, taux, séries macro =
genre puis nom), la couverture du registre, l'échappement et le pendant navigateur (`static/names.js`, testé sous Node)."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from patrick.config import defaults as D
from patrick.config.instrument_names import INSTRUMENTS
from patrick.config.universe_extension import all_target_groups
from patrick.webapp import instruments
from patrick.webapp.app import app

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "patrick" / "webapp" / "static"
KINDS = {"stock", "etf", "future", "index", "vol", "fx", "crypto", "rate", "macro"}


# ---------------------------------------------------------------------------------------------------------------- registre
def test_every_target_and_macro_series_has_a_name():
    symbols = {s for items in all_target_groups().values() for s, _ in items}
    symbols |= set(D.DEFAULT_UNIVERSE_FRED_SERIES.values()) | set(D.MACRO_ONLY_FRED_SERIES.values())
    assert [s for s in sorted(symbols) if s not in INSTRUMENTS] == []


def test_registry_rows_are_well_formed():
    for symbol, (kind, fr, en) in INSTRUMENTS.items():
        assert kind in KINDS, symbol
        assert fr.strip() and en.strip(), symbol
        assert " · " not in fr and " · " not in en, symbol            # le genre est ajouté à l'affichage, jamais écrit dans le nom


# ---------------------------------------------------------------------------------------------------------------- la règle
@pytest.mark.parametrize("symbol, expected", [
    ("AAPL", "Apple"), ("MC.PA", "LVMH"), ("XLK", "Technology Select Sector SPDR Fund"), ("CW8.PA", "Amundi MSCI World UCITS ETF"),
])
def test_companies_and_etfs_show_their_name_only(symbol, expected):
    assert instruments.display(symbol, "fr") == expected == instruments.display(symbol, "en")


@pytest.mark.parametrize("symbol, fr, en", [
    ("GC=F", "Future · Or", "Future · Gold"),
    ("^GSPC", "Indice · S&P 500", "Index · S&P 500"),
    ("^VIX", "Volatilité · VIX (S&P 500)", "Volatility · VIX (S&P 500)"),
    ("EURUSD=X", "Devise · EUR/USD", "FX · EUR/USD"),
    ("BTC-USD", "Crypto · Bitcoin", "Crypto · Bitcoin"),
    ("^TNX", "Taux · Trésor US 10 ans", "Rate · US Treasury 10-year"),
    ("DGS10", "Macro · Rendement du Trésor US 10 ans", "Macro · US Treasury 10-year yield"),
])
def test_other_instruments_put_the_genre_first(symbol, fr, en):
    assert instruments.display(symbol, "fr") == fr
    assert instruments.display(symbol, "en") == en


def test_an_alpha_target_reads_as_name_versus_benchmark():
    assert instruments.display("AAPL__alpha_^GSPC", "fr") == "Apple · α vs S&P 500"
    assert instruments.display("GC=F__alpha_^GSPC", "fr") == "Future · Or · α vs S&P 500"


def test_a_futures_contract_shows_its_product_and_month():
    assert instruments.display("ESZ26.CME", "fr") == "Future · E-mini S&P 500 · déc. 2026"
    assert instruments.display("ESZ26.CME", "en") == "Future · E-mini S&P 500 · Dec 2026"
    assert instruments.display_instrument({"kind": "future", "spec": {"root": "ES"}}, "fr") == "Future · E-mini S&P 500"


def test_a_fund_position_can_force_its_kind():
    assert instruments.display("AAPL", "fr", "cfd") == "CFD · Apple"
    assert instruments.display("^GSPC", "fr", "cfd") == "CFD · S&P 500"                  # pas de « CFD · Indice · … »
    assert instruments.display_instrument({"kind": "cfd", "symbol": "AAPL"}, "en") == "CFD · Apple"


def test_unknown_symbols_are_guessed_from_their_shape_or_left_alone():
    assert instruments.display("ZZZ.UNKNOWN", "fr") == "ZZZ.UNKNOWN"
    assert instruments.display("FOO=F", "fr") == "Future · FOO=F"
    assert instruments.display("ABC-USD", "fr") == "Crypto · ABC"
    assert instruments.display("EURGBP=X", "fr") == "Devise · EUR/GBP"
    assert instruments.display("", "fr") == "" and instruments.display(None, "fr") == ""


def test_the_browser_receives_the_whole_registry_in_the_page_language():
    fr, en = instruments.names_for_browser("fr"), instruments.names_for_browser("en")
    assert set(INSTRUMENTS) <= set(fr) and set(INSTRUMENTS) <= set(en)
    assert fr["^VIX"] == "Volatilité · VIX (S&P 500)" and en["^VIX"] == "Volatility · VIX (S&P 500)"
    assert fr["AAPL"] == "Apple"


# ---------------------------------------------------------------------------------------------------------------- échappement
def test_names_are_html_escaped_exactly_once():
    assert instruments.display_html("^GSPC", "fr") == "Indice · S&amp;P 500"
    assert instruments.display_html("<b>", "fr") == "&lt;b&gt;"
    # `list_all_runs` livre des cibles déjà échappées : pas de double échappement
    assert instruments.display_html("&lt;img src=x onerror=alert(1)&gt;", "fr") == "&lt;img src=x onerror=alert(1)&gt;"


def test_the_tooltip_variant_keeps_the_symbol_and_escapes_everything():
    html = str(instruments.display_with_tip("^GSPC", "fr"))
    assert html == '<span class="instr" title="^GSPC">Indice · S&amp;P 500</span>'
    assert str(instruments.display_with_tip("ZZZ.UNKNOWN", "fr")) == "ZZZ.UNKNOWN"          # nom = symbole : pas de bulle
    assert "<" not in str(instruments.display_with_tip('<script>"x"</script>', "fr")).replace("<span", "").replace("</span", "")


@pytest.mark.parametrize("text, ok", [("AAPL", True), ("^GSPC", True), ("GC=F", True), ("BTC-USD", True), ("MC.PA", True),
                                      ("<img src=x onerror=alert(1)>", False), ("a b", False), ("x" * 30, False), ("", False)])
def test_only_symbol_shaped_strings_are_looked_up_online(text, ok):
    assert bool(instruments._SYMBOL_SHAPE.match(text)) is ok


# ---------------------------------------------------------------------------------------------------------------- pages
def test_pages_ship_the_names_before_any_page_script():
    html = TestClient(app).get("/ml").text
    block = re.search(r'<script id="instrument-names" type="application/json">(.*?)</script>', html, re.DOTALL)
    assert block is not None
    names = json.loads(block.group(1))
    assert names["^VIX"] == "Volatilité · VIX (S&P 500)" and names["AAPL"] == "Apple"
    # les récapitulatifs calculés au chargement de app.js ont besoin des noms déjà présents
    assert block.start() < html.index("/static/app.js")
    assert html.index("/static/names.js") < html.index("/static/ticker.js")


def test_the_launch_list_shows_names_and_keeps_the_symbol_as_identifier():
    html = TestClient(app).get("/ml").text
    assert re.search(r'<option value="\^GSPC" title="\^GSPC"[^>]*>Indice · S&amp;P 500</option>', html)
    assert re.search(r'<option value="AAPL" title="AAPL"[^>]*>Apple</option>', html)
    assert re.search(r'<option value="GC=F" title="GC=F"[^>]*>Future · Or</option>', html)


# ---------------------------------------------------------------------------------------------------------------- navigateur
@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js absent")
def test_names_js_under_node():
    done = subprocess.run(["node", str(ROOT / "tests" / "js" / "names.test.js")], capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, f"{done.stdout}\n{done.stderr}"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js absent")
@pytest.mark.parametrize("name", [
    "names.js", "analysis_kit.js", "ticker.js", "exploration.js", "rl.js", "model_registry.js", "journal.js", "drift_monitor.js",
    "variables.js", "guardrails.js", "carnet.js", "analyses_hub.js", "analyses_compare.js", "run_analysis.js", "rl_analysis.js",
    "risque.js", "donnees.js", "simulate.js", "wealth.js", "app.js",
])
def test_scripts_touched_by_the_naming_change_parse(name):
    done = subprocess.run(["node", "--check", str(STATIC / name)], capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
