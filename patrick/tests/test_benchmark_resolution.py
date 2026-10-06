"""Cible alpha, jalon 2a : benchmark déterminé automatiquement, choisissable à la main."""
from __future__ import annotations

import pytest

from patrick.features import benchmark as bm


@pytest.mark.parametrize("symbol, expected", [
    ("AAPL", "^GSPC"),            # action US
    ("MC.PA", "^STOXX50E"),       # zone euro
    ("SAP.DE", "^STOXX50E"),
    ("ASML.AS", "^STOXX50E"),
    ("VOD.L", "^FTSE"),           # Royaume-Uni
    ("NESN.SW", "^STOXX50E"),     # Europe hors zone euro : approximation documentée
    ("7203.T", "^N225"),
    ("0700.HK", "^HSI"),
    ("BHP.AX", "^AXJO"),
    ("SHOP.TO", "^GSPTSE"),
    ("PETR4.SA", "^BVSP"),
    ("ETH-USD", "BTC-USD"),       # crypto : le marché crypto
    ("GC=F", "DBC"),              # matières premières
    ("^FCHI", "^STOXX50E"),       # indice national vs zone euro
    ("^GSPC", "URTH"),            # indice US vs monde (et jamais contre lui-même)
    ("^STOXX50E", "URTH"),
])
def test_auto_benchmark_by_asset_class_and_region(symbol, expected):
    choice = bm.auto_benchmark(symbol)
    assert choice.symbol == expected and choice.source == "auto" and choice.reason


@pytest.mark.parametrize("symbol, source", [
    ("BTC-USD", "yfinance"),      # c'est lui-même la référence du marché crypto
    ("^VIX", "yfinance"),         # indice de volatilité : pas de rendement excédentaire sensé
    ("EURUSD=X", "yfinance"),     # change
    ("DGS10", "fred"),            # série macro
])
def test_no_automatic_benchmark_when_none_makes_sense(symbol, source):
    with pytest.raises(bm.BenchmarkError) as exc:
        bm.auto_benchmark(symbol, source)
    assert "manuel" in str(exc.value)                                 # le message dit comment s'en sortir


def test_a_benchmark_is_never_the_target_itself():
    assert bm.auto_benchmark("URTH").symbol != "URTH"
    for symbol in ("^GSPC", "^STOXX50E", "^FTSE", "^N225", "^HSI", "BTC-USD", "DBC"):
        try:
            assert bm.auto_benchmark(symbol).symbol != symbol
        except bm.BenchmarkError:
            pass                                                       # refus explicite accepté, jamais lui-même


def test_manual_choice_wins_and_is_normalised():
    choice = bm.resolve_benchmark("MC.PA", override="  ^fchi ")
    assert (choice.symbol, choice.source) == ("^FCHI", "manual") and "choisi" in choice.reason


@pytest.mark.parametrize("override", [None, "", "   "])
def test_no_override_means_automatic(override):
    assert bm.resolve_benchmark("AAPL", override=override).source == "auto"


def test_manual_choice_makes_an_otherwise_impossible_target_possible():
    assert bm.resolve_benchmark("BTC-USD", override="^GSPC").symbol == "^GSPC"
    assert bm.resolve_benchmark("EURUSD=X", override="DX-Y.NYB").source == "manual"


def test_manual_choice_equal_to_the_target_is_refused():
    with pytest.raises(bm.BenchmarkError, match="lui-même"):
        bm.resolve_benchmark("AAPL", override="aapl")


def test_manual_choice_must_look_like_a_ticker():
    for bad in ("^GSPC; DROP", "a b", "x" * 40):
        with pytest.raises(bm.BenchmarkError, match="invalide"):
            bm.resolve_benchmark("AAPL", override=bad)


def test_fallback_guard_protects_the_never_the_target_invariant():
    """Invariant de la table : si une règle donnait un jour la cible elle-même, on remonte au monde, puis on refuse."""
    assert bm._fallback("FOO", "FOO", "règle de test").symbol == bm.WORLD
    assert bm._fallback("FOO", "BAR", "règle de test").symbol == "BAR"
    with pytest.raises(bm.BenchmarkError, match="manuellement"):
        bm._fallback(bm.WORLD, bm.WORLD, "règle de test")
