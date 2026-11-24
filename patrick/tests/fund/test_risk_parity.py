"""A30 : parité de risque -- contributions au risque égales, corrélations comprises."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.fund import autopilot, risk_parity, store


def test_erc_equalises_risk_contributions_and_down_weights_correlated_assets():
    # trois actifs de même volatilité, A et B corrélés à 0,9, C indépendant : C doit peser plus que A et B
    vol = np.array([0.01, 0.01, 0.01])
    corr = np.array([[1, 0.9, 0], [0.9, 1, 0], [0, 0, 1]])
    cov = np.outer(vol, vol) * corr
    w = risk_parity.erc_weights(cov)
    assert w.sum() == pytest.approx(1) and (w > 0).all()
    assert risk_parity.risk_contributions(w, cov) == pytest.approx(np.full(3, 1 / 3), abs=1e-6)
    assert w[2] > w[0] == pytest.approx(w[1])


def test_with_no_correlation_erc_is_inverse_volatility():
    cov = np.diag(np.array([0.01, 0.02, 0.04]) ** 2)
    w = risk_parity.erc_weights(cov)
    inv = 1 / np.array([0.01, 0.02, 0.04])
    assert w == pytest.approx(inv / inv.sum(), abs=1e-6)


def test_the_shrunk_covariance_needs_enough_common_days():
    rng = np.random.default_rng(0)
    df = pd.DataFrame(rng.normal(0, 0.01, (200, 3)), columns=list("ABC"))
    assert risk_parity.shrunk_cov(df).shape == (3, 3)
    assert risk_parity.shrunk_cov(df.iloc[:50]) is None


def test_the_autopilot_weights_targets_by_risk_parity_when_asked():
    rng = np.random.default_rng(1)
    common = rng.normal(0, 0.01, 300)
    returns = pd.DataFrame({"SPY": common + rng.normal(0, 0.002, 300), "QQQ": common + rng.normal(0, 0.002, 300),
                            "GLD": rng.normal(0, 0.01, 300)})
    priced = [{"target": t, "vol": 0.01} for t in returns.columns]
    inv = autopilot._weights(priced, autopilot.Settings())
    erc = autopilot._weights(priced, autopilot.Settings(weighting="risk_parity"), returns)
    by = {m["target"]: erc[id(m)] for m in priced}
    assert all(v == pytest.approx(1 / 3) for v in inv.values())               # volatilité inverse : même vol, mêmes poids
    assert by["GLD"] > by["SPY"] and by["GLD"] > by["QQQ"]                       # parité de risque : l'actif décorrélé pèse plus
    assert autopilot.Settings.from_dict({"weighting": "risk_parity"}).weighting == "risk_parity"
    with pytest.raises(store.FundError, match="weighting"):
        autopilot.Settings.from_dict({"weighting": "egal"})
