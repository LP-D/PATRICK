"""Phase 8 (feature/portfolio-view) -- TDD tests for the PURE aggregation /
contradiction-detection logic behind `/portfolio`, written BEFORE
`patrick.tracking.portfolio` exists.

Deliberately DB-free: both functions under test operate on plain Python
structures (the dict already returned by
`tracking.history.latest_predictions_by_target_and_horizon`, and a
`DEFAULT_TARGET_GROUPS`-shaped dict) -- no sqlite fixture needed, unlike most
of `test_history.py`. The route-level wiring (`portfolio_overview`, calling
the real `latest_predictions_by_target_and_horizon` against a seeded DB) is
covered separately by `test_portfolio_page.py`.
"""
from __future__ import annotations

from patrick.tracking import portfolio as trackportfolio


# ---------------------------------------------------------------------------
# aggregate_signals_by_group
# ---------------------------------------------------------------------------

def test_aggregate_signals_by_group_counts_bullish_bearish_and_missing():
    predictions = {
        ("A", 1): {"direction": "UP"},
        ("A", 2): {"direction": "DOWN"},
        ("B", 1): {"direction": "UP"},
        # ("B", 2) absent -> no signal
        ("C", 1): {"direction": "DOWN"},
        ("C", 2): {"direction": "DOWN"},
    }
    target_groups = {
        "G1": [("A", "labelA"), ("B", "labelB")],
        "G2": [("C", "labelC")],
    }
    horizons = [1, 2]

    result = trackportfolio.aggregate_signals_by_group(predictions, target_groups, horizons)

    by_group = {r["group"]: r for r in result}
    assert by_group["G1"]["n_pairs"] == 4
    assert by_group["G1"]["n_bullish"] == 2
    assert by_group["G1"]["n_bearish"] == 1
    assert by_group["G1"]["n_signals"] == 3
    assert by_group["G1"]["n_no_signal"] == 1

    assert by_group["G2"]["n_pairs"] == 2
    assert by_group["G2"]["n_bullish"] == 0
    assert by_group["G2"]["n_bearish"] == 2
    assert by_group["G2"]["n_signals"] == 2
    assert by_group["G2"]["n_no_signal"] == 0


def test_aggregate_signals_by_group_preserves_group_order():
    target_groups = {"Zeta": [("Z", "z")], "Alpha": [("A", "a")]}
    result = trackportfolio.aggregate_signals_by_group({}, target_groups, [1])
    assert [r["group"] for r in result] == ["Zeta", "Alpha"]


def test_aggregate_signals_by_group_empty_predictions_is_all_no_signal():
    target_groups = {"G1": [("A", "a"), ("B", "b")]}
    result = trackportfolio.aggregate_signals_by_group({}, target_groups, [1, 2])
    row = result[0]
    assert row["n_pairs"] == 4
    assert row["n_bullish"] == 0
    assert row["n_bearish"] == 0
    assert row["n_no_signal"] == 4


def test_aggregate_signals_by_group_group_with_no_symbols_is_all_zero():
    target_groups = {"Empty": []}
    result = trackportfolio.aggregate_signals_by_group({}, target_groups, [1, 2, 3])
    row = result[0]
    assert row["n_pairs"] == 0
    assert row["n_bullish"] == 0
    assert row["n_bearish"] == 0
    assert row["n_no_signal"] == 0


def test_aggregate_signals_by_group_no_horizons_is_all_zero():
    target_groups = {"G1": [("A", "a")]}
    result = trackportfolio.aggregate_signals_by_group(
        {("A", 1): {"direction": "UP"}}, target_groups, [],
    )
    row = result[0]
    assert row["n_pairs"] == 0
    assert row["n_signals"] == 0


# ---------------------------------------------------------------------------
# CORRELATED_PAIRS -- documented list, must contain the mandated DXY/EUR-USD
# pair with the correct (negative) correlation sign.
# ---------------------------------------------------------------------------

def test_correlated_pairs_includes_dxy_eurusd_as_negative():
    match = [p for p in trackportfolio.CORRELATED_PAIRS
              if {p["symbol_a"], p["symbol_b"]} == {"DX-Y.NYB", "EURUSD=X"}]
    assert len(match) == 1
    assert match[0]["correlation"] == "negative"
    assert match[0]["rationale"]  # documented, not just a bare pair of symbols


def test_correlated_pairs_each_entry_documents_symbols_and_sign():
    for pair in trackportfolio.CORRELATED_PAIRS:
        assert pair["symbol_a"] != pair["symbol_b"]
        assert pair["correlation"] in ("positive", "negative")
        assert isinstance(pair["rationale"], str) and pair["rationale"].strip()


# ---------------------------------------------------------------------------
# detect_contradictions
# ---------------------------------------------------------------------------

def test_detect_contradictions_flags_dxy_and_eurusd_both_bullish():
    """Negative correlation pair: DXY up AND EUR/USD up on the same horizon
    is the textbook contradiction -- the dollar cannot simultaneously
    strengthen (DXY up) and weaken against the euro (EUR/USD up)."""
    predictions = {
        ("DX-Y.NYB", 5): {"direction": "UP"},
        ("EURUSD=X", 5): {"direction": "UP"},
    }
    hits = trackportfolio.detect_contradictions(predictions)
    assert len(hits) == 1
    hit = hits[0]
    assert {hit["symbol_a"], hit["symbol_b"]} == {"DX-Y.NYB", "EURUSD=X"}
    assert hit["horizon"] == 5
    assert hit["correlation"] == "negative"


def test_detect_contradictions_flags_dxy_and_eurusd_both_bearish():
    predictions = {
        ("DX-Y.NYB", 10): {"direction": "DOWN"},
        ("EURUSD=X", 10): {"direction": "DOWN"},
    }
    hits = trackportfolio.detect_contradictions(predictions)
    assert len(hits) == 1
    assert hits[0]["horizon"] == 10


def test_detect_contradictions_does_not_flag_expected_negative_correlation():
    """DXY up / EUR-USD down (or the reverse) is exactly what a negative
    correlation predicts -- must NOT be reported as a contradiction."""
    predictions = {
        ("DX-Y.NYB", 5): {"direction": "UP"},
        ("EURUSD=X", 5): {"direction": "DOWN"},
    }
    assert trackportfolio.detect_contradictions(predictions) == []


def test_detect_contradictions_skips_pair_with_only_one_side_present():
    predictions = {("DX-Y.NYB", 5): {"direction": "UP"}}
    assert trackportfolio.detect_contradictions(predictions) == []


def test_detect_contradictions_is_independent_per_horizon():
    """Same target pair, two horizons: one contradictory, one consistent --
    each horizon is judged on its own, not conflated."""
    predictions = {
        ("DX-Y.NYB", 5): {"direction": "UP"},
        ("EURUSD=X", 5): {"direction": "UP"},   # contradictory
        ("DX-Y.NYB", 10): {"direction": "UP"},
        ("EURUSD=X", 10): {"direction": "DOWN"},  # consistent
    }
    hits = trackportfolio.detect_contradictions(predictions)
    assert [h["horizon"] for h in hits] == [5]


def test_detect_contradictions_flags_positive_correlation_pair_diverging():
    """WTI/Brent (positive correlation, both crude-oil benchmarks): opposite
    directions on the same horizon is the contradiction here."""
    predictions = {
        ("CL=F", 5): {"direction": "UP"},
        ("BZ=F", 5): {"direction": "DOWN"},
    }
    hits = trackportfolio.detect_contradictions(predictions)
    assert len(hits) == 1
    assert hits[0]["correlation"] == "positive"


def test_detect_contradictions_does_not_flag_positive_correlation_pair_agreeing():
    predictions = {
        ("CL=F", 5): {"direction": "UP"},
        ("BZ=F", 5): {"direction": "UP"},
    }
    assert trackportfolio.detect_contradictions(predictions) == []


def test_detect_contradictions_ignores_predictions_missing_direction():
    """A pred dict with a falsy/None direction (no prediction resolved for
    that pair yet) must never crash the comparison nor be treated as a
    signal."""
    predictions = {
        ("DX-Y.NYB", 5): {"direction": None},
        ("EURUSD=X", 5): {"direction": "UP"},
    }
    assert trackportfolio.detect_contradictions(predictions) == []


def test_detect_contradictions_empty_predictions_returns_empty_list():
    assert trackportfolio.detect_contradictions({}) == []
