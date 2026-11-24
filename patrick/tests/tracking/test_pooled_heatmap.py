"""D10 : grille cible x horizon de l'AUC regroupée -- cibles significatives d'abord, au plus N, rangées par classe d'actifs."""
from __future__ import annotations

from patrick.tracking import pooled_signal


def _row(target, horizon, auc, sig=False):
    return {"target": target, "horizon": horizon, "auc": auc, "significant": sig, "q_value": 0.05 if sig else 0.6, "n_runs": 3}


def test_significant_targets_come_first_then_the_strongest_and_the_grid_is_capped():
    rows = [_row("AAPL", 1, 0.52), _row("AAPL", 5, 0.53), _row("^N225", 1, 0.61, sig=True), _row("MSFT", 1, 0.58),
            _row("GC=F", 1, 0.50), _row("^VIX", 5, 0.66, sig=True)]

    grid = pooled_signal.heatmap(rows, max_targets=3)

    assert {r["target"] for r in grid["rows"]} == {"^N225", "^VIX", "MSFT"}            # 2 significatives + la plus forte AUC
    assert grid["horizons"] == [1, 5] and grid["n_targets"] == 5
    classes = [r["class"] for r in grid["rows"]]
    assert classes == sorted(classes)                                                 # rangées par classe d'actifs
    vix = next(r for r in grid["rows"] if r["target"] == "^VIX")
    assert set(vix["cells"]) == {5} and vix["cells"][5]["significant"] is True


def test_no_pooled_signal_gives_an_empty_grid():
    assert pooled_signal.heatmap([]) == {"horizons": [], "rows": [], "n_targets": 0}
