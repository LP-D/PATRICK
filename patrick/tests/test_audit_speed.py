"""`patrick audit speed`: feature -> family classification on the REAL
names the builders produce (sampled from the ^GSPC full pool, 2026-09-25),
usage read from the database, cost measurement."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick import audit_speed
from patrick.tracking import db as trackdb


@pytest.mark.parametrize("name, family", [
    ("US1Y_Rate_egarch_vol", "egarch"),
    ("GDP_kalman_filtered", "kalman"),
    ("HE=F_hmm_filtered_stress_prob", "hmm"),
    ("WTI_Oil_FRED_particle_vol", "particle_filter"),
    ("HG=F_heston_spread", "heston_proxy"),
    ("SP500_Level_heston_theta", "heston_proxy"),
    ("KE=F_hurst_100d", "spike_rolling"),
    ("SOFR_SecuredOIS_skew_20d", "spike_rolling"),
    ("IDX_GSPC_rs_20d", "ohlc_vol"),
    ("IDX_GSPC_yz_10d", "ohlc_vol"),
    ("BBB_OAS_lag5", "macro"),
    ("Core_PCE_level", "macro"),
    ("US1M_Rate_ret_20d", "technical"),
    ("DFF_vs_ma10", "technical"),
    ("GC=F_rsi_14d", "technical"),
    ("IDX_GSPC_rsi_14d__minus__US1M_Rate_skew_20d", "interactions"),
    ("EURUSD=X", "raw_level"),
])
def test_real_feature_names_are_classified(name, family):
    assert audit_speed.classify_feature(name) == family


def test_usage_counts_exported_features_and_selection_frequencies(conn):
    for f in ("IDX_GSPC_egarch_vol", "NFCI_egarch_vol", "IDX_GSPC_zscore_10d"):
        trackdb.save_drift_reference(conn, "^GSPC", 5, f, [0.0] * 11)
    usage = audit_speed.usage_from_db(conn)
    assert usage["egarch"].exported == 2
    assert usage["technical"].exported == 1
    audit_speed.add_pool(usage, ["A_egarch_vol", "A_ret_5d", "B_ret_5d"])
    assert usage["technical"].pool_columns == 2
    table = audit_speed.render_markdown(usage)
    assert "| egarch | oui |" in table


def test_family_costs_are_measured():
    idx = pd.bdate_range("2015-01-01", periods=400)
    raw = pd.DataFrame({"X": 100 + np.cumsum(np.random.default_rng(0).normal(0, 1, 400))}, index=idx)
    costs = audit_speed.measure_family_costs(raw)
    assert {"technical", "egarch", "particle_filter"} <= set(costs)
    assert all(v >= 0 for v in costs.values())


def test_a_family_absent_from_the_pool_is_reported_as_not_enabled():
    """ARIMA was measured (cost *if* enabled) but is off by default: its
    cost must not be counted in the run's cost shares, nor read as waste."""
    usage = {
        "hmm": audit_speed.FamilyUsage("hmm", pool_columns=42, cost_s=10.0),
        "arima_family": audit_speed.FamilyUsage("arima_family", pool_columns=0, cost_s=10.0),
    }
    table = audit_speed.render_markdown(usage, n_folds=5)
    arima_row = next(line for line in table.splitlines() if line.startswith("| arima_family"))
    hmm_row = next(line for line in table.splitlines() if line.startswith("| hmm"))
    assert "non activée" in arima_row and "50.0 s si activée" in arima_row
    assert hmm_row.endswith("| 100% |")
