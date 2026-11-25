"""A20 : probabilité de sur-apprentissage de la grille de réglages du laboratoire de stratégies."""
from __future__ import annotations

import numpy as np
import pandas as pd

from patrick.strategylab import robustness


def _grid(edges, n=2000, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2018-01-01", periods=n)
    return pd.DataFrame({f"r{i}": rng.normal(e, 0.01, n) for i, e in enumerate(edges)}, index=idx)


def test_a_grid_of_pure_noise_has_a_high_pbo():
    out = robustness.pbo_of(_grid([0.0] * 12))
    assert out["pbo"] > 0.3 and out["n_trials"] == 12 and out["n_blocks"] == 8 and out["n_combinations"] == 70


def test_a_setting_with_a_lasting_edge_has_a_low_pbo():
    out = robustness.pbo_of(_grid([0.0] * 11 + [0.002]))
    assert out["pbo"] < 0.1


def test_too_short_or_single_setting_gives_none():
    assert robustness.pbo_of(_grid([0.0, 0.0], n=100)) is None
    assert robustness.pbo_of(_grid([0.0])) is None
