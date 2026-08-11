"""Shared pytest fixtures/helpers across `patrick/tests/`."""
from __future__ import annotations

import pandas as pd

# Relative, not absolute: `data/ingest.py` requires >= 20 years of history
# (`min_history = today - 20*365.25 days`). An absolute date drifts under
# that threshold as real time passes -- 30 years back keeps a decade of
# margin regardless of when the suite runs. Shared here (was duplicated in
# `test_data_quality.py` and `test_audit_degradation.py`, both hitting the
# same drift once their absolute `2015-01-01`/`2018-01-01` fixtures aged
# past the 20-year threshold -- see KNOWN_ISSUES.md).
OLD_ENOUGH_START = (pd.Timestamp.today() - pd.Timedelta(days=30 * 365.25)).strftime("%Y-%m-%d")
