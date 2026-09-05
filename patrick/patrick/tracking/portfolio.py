"""Phase 8 (feature/portfolio-view) -- `/portfolio`: cross-asset aggregated
view over the WHOLE universe. Two pieces of PURE Python logic, deliberately
kept DB-free and unit-tested without a sqlite fixture (`tests/test_portfolio.py`):

1. `aggregate_signals_by_group` -- counts bullish (UP) / bearish (DOWN)
   signals per `DEFAULT_TARGET_GROUPS` category, from an already-fetched
   prediction dict. No new query: `portfolio_overview()` below sources that
   dict from the EXISTING
   `tracking.history.latest_predictions_by_target_and_horizon` (same one
   `/predictions` already uses) and aggregates its result in Python, per the
   phase's explicit instruction not to duplicate that query.

2. `detect_contradictions` -- flags target pairs whose latest signals
   disagree with their historically expected co-movement (see
   `CORRELATED_PAIRS`), for the same horizon.

`portfolio_overview()` is the only function here that touches the database,
and it does so by calling the existing history-layer function, not a new
one -- same read-only-on-every-request philosophy as `history.synthesis_overview`.
"""
from __future__ import annotations

import sqlite3

from patrick.config import defaults as D
from patrick.tracking import history as trackhistory

# ---------------------------------------------------------------------------
# CORRELATED_PAIRS -- explicit, documented list of asset pairs considered for
# contradiction detection, and the sign of co-movement expected of each.
#
# "negative": the two assets are expected to move in OPPOSITE directions --
#             a signal predicting the SAME direction (both UP or both DOWN)
#             for the same horizon is flagged as contradictory.
# "positive": the two assets are expected to move in the SAME direction --
#             a signal predicting OPPOSITE directions for the same horizon
#             is flagged as contradictory.
#
# Chosen from `patrick.config.defaults.DEFAULT_TARGET_GROUPS` (the reduced
# universe: commodities + macro + 4 kept assets) -- not an exhaustive
# correlation study, three textbook, well-documented relationships that are
# both intuitive to a reader of the dashboard and actually present as two
# distinct targets in this universe:
#
#   - DX-Y.NYB (US Dollar Index) / EURUSD=X (EUR/USD): required by the phase
#     spec. EUR/USD is priced as "dollars per euro" -- when the dollar
#     strengthens broadly (DXY up), EUR/USD mechanically tends to fall, and
#     vice versa. Negative correlation, historically strong (EUR/USD is
#     DXY's single largest component by weight in the index basket).
#   - CL=F (WTI) / BZ=F (Brent): the two dominant crude-oil benchmark
#     futures. Both track the same underlying global oil-supply/demand
#     shocks and are cointegrated in practice (the WTI-Brent spread moves
#     within a comparatively narrow band) -- positive correlation.
#   - ^GSPC (S&P 500) / ^VIX (VIX): the VIX is priced off S&P 500 option
#     implied volatility and is the textbook "fear gauge" -- realized
#     equity selloffs (S&P down) come with volatility spikes (VIX up), and
#     calm/rising markets come with a falling VIX. Negative correlation.
#
# Gold (GC=F) / Silver (SI=F) was considered (both precious metals, usually
# positively correlated) but left out: the correlation is real but looser
# and more regime-dependent (industrial-demand-driven silver decouples from
# gold's safe-haven role often enough that flagging every divergence as a
# "contradiction" would be noisy) -- the three pairs above are the ones with
# an unambiguous, structurally-grounded direction of co-movement.
CORRELATED_PAIRS: list[dict] = [
    {
        "symbol_a": "DX-Y.NYB", "label_a": "USD_Index",
        "symbol_b": "EURUSD=X", "label_b": "EUR_USD",
        "correlation": "negative",
        "rationale": (
            "EUR/USD se lit \"dollars par euro\" : un dollar plus fort (DXY en hausse) "
            "fait mécaniquement baisser EUR/USD, et inversement -- corrélation négative "
            "historiquement forte (l'euro pèse le plus dans le panier du DXY)."
        ),
    },
    {
        "symbol_a": "CL=F", "label_a": "WTI_Futures",
        "symbol_b": "BZ=F", "label_b": "Brent_Futures",
        "correlation": "positive",
        "rationale": (
            "WTI et Brent sont les deux références majeures du pétrole brut : mêmes chocs "
            "d'offre/demande globaux, spread WTI-Brent historiquement contenu -- "
            "corrélation positive."
        ),
    },
    {
        "symbol_a": "^GSPC", "label_a": "SP500_Price",
        "symbol_b": "^VIX", "label_b": "VIX_Price",
        "correlation": "negative",
        "rationale": (
            "Le VIX est calculé à partir de la volatilité implicite des options du S&P 500 "
            "(\"jauge de la peur\") : une baisse du S&P s'accompagne typiquement d'un VIX en "
            "hausse, et inversement -- corrélation négative structurelle."
        ),
    },
]


def aggregate_signals_by_group(
    predictions: dict[tuple[str, int], dict],
    target_groups: dict[str, list[tuple[str, str]]],
    horizons: list[int],
) -> list[dict]:
    """Counts bullish (UP) / bearish (DOWN) signals per category, from a
    prediction dict already keyed `(symbol, horizon) -> {"direction": ...}`
    (the exact shape `latest_predictions_by_target_and_horizon` returns).

    Every `(symbol, horizon)` combination in `target_groups` x `horizons` is
    one "pair" -- present with a resolved direction (bullish/bearish
    signal) or absent (`n_no_signal`, no prediction recorded yet for that
    combination). Groups are returned in `target_groups`' own iteration
    order (a plain dict preserves insertion order in Python -- same
    convention `DEFAULT_TARGET_GROUPS` and `universe_overview()` rely on).

    A resolved prediction whose `direction` is neither `"UP"` nor `"DOWN"`
    (defensive only -- `_CLASS_DIRECTION` in `history.py` only ever
    produces those two, "?" would mean an out-of-range class id) counts
    towards neither bucket and is NOT counted as `n_no_signal` either: it is
    a resolved-but-uninterpretable case, distinct from "no prediction at
    all" -- rare enough in practice that a dedicated counter would be noise,
    but silently double-counting it as either would be wrong."""
    out = []
    for group_name, items in target_groups.items():
        n_bullish = n_bearish = 0
        for symbol, _label in items:
            for h in horizons:
                pred = predictions.get((symbol, h))
                if not pred:
                    continue
                direction = pred.get("direction")
                if direction == "UP":
                    n_bullish += 1
                elif direction == "DOWN":
                    n_bearish += 1
        n_pairs = len(items) * len(horizons)
        n_signals = n_bullish + n_bearish
        out.append({
            "group": group_name,
            "n_pairs": n_pairs,
            "n_bullish": n_bullish,
            "n_bearish": n_bearish,
            "n_signals": n_signals,
            "n_no_signal": n_pairs - n_signals,
        })
    return out


def detect_contradictions(
    predictions: dict[tuple[str, int], dict],
    pairs: list[dict] | None = None,
) -> list[dict]:
    """Flags `(pair, horizon)` combinations whose latest signals disagree
    with the expected co-movement documented in `CORRELATED_PAIRS`.

    For each pair and each horizon where BOTH symbols have a resolved
    `direction` in `{"UP", "DOWN"}`: a `"negative"`-correlation pair is
    contradictory when both sides agree (same direction); a
    `"positive"`-correlation pair is contradictory when they disagree.
    A horizon where either side has no prediction yet (or an unresolved
    direction) is simply skipped -- nothing to compare, not a
    contradiction.

    Horizons considered for a pair are derived directly from `predictions`'
    own keys (every horizon for which either symbol has an entry), not from
    `config.defaults.DEFAULT_HORIZONS` -- keeps this function usable on any
    subset of horizons the caller happens to have fetched.

    Returns a list of hit dicts (one per contradictory `(pair, horizon)`),
    each carrying both symbols/labels, their directions, the horizon, and
    the pair's documented correlation sign + rationale (so the template can
    render the "why" without re-deriving it)."""
    pairs = CORRELATED_PAIRS if pairs is None else pairs
    hits = []
    for pair in pairs:
        a, b = pair["symbol_a"], pair["symbol_b"]
        horizons = sorted({h for (target, h) in predictions if target in (a, b)})
        for h in horizons:
            pred_a = predictions.get((a, h))
            pred_b = predictions.get((b, h))
            if not pred_a or not pred_b:
                continue
            dir_a, dir_b = pred_a.get("direction"), pred_b.get("direction")
            if dir_a not in ("UP", "DOWN") or dir_b not in ("UP", "DOWN"):
                continue
            correlation = pair["correlation"]
            contradictory = (dir_a == dir_b) if correlation == "negative" else (dir_a != dir_b)
            if not contradictory:
                continue
            hits.append({
                "symbol_a": a, "label_a": pair["label_a"], "direction_a": dir_a,
                "symbol_b": b, "label_b": pair["label_b"], "direction_b": dir_b,
                "horizon": h,
                "correlation": correlation,
                "rationale": pair["rationale"],
            })
    return hits


def portfolio_overview(
    conn: sqlite3.Connection,
    target_groups: dict[str, list[tuple[str, str]]] | None = None,
    horizons: list[int] | None = None,
) -> dict:
    """`/portfolio` -- assembles the cross-asset synthesis from the SAME
    grouped query `/predictions` already uses
    (`history.latest_predictions_by_target_and_horizon`, no new DB access
    written for this phase), then aggregates it in Python via the two pure
    functions above. Read-only, recomputed on every request -- same
    philosophy as every other page in this module family (`synthesis_overview`,
    `_predictions_overview`)."""
    target_groups = D.DEFAULT_TARGET_GROUPS if target_groups is None else target_groups
    horizons = list(D.DEFAULT_HORIZONS) if horizons is None else horizons
    all_symbols = [sym for items in target_groups.values() for sym, _ in items]

    predictions = trackhistory.latest_predictions_by_target_and_horizon(conn, all_symbols, horizons)

    return {
        "groups": aggregate_signals_by_group(predictions, target_groups, horizons),
        "contradictions": detect_contradictions(predictions),
        "horizons": horizons,
    }
