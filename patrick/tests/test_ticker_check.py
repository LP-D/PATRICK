"""Live ticker verification (roadmap bloc 2/4) -- statuses on synthetic
fetchers, no network."""
from __future__ import annotations

import pandas as pd
import pytest

from patrick.data import ticker_check as tc

TODAY = "2026-09-25"


def _series(end, n):
    idx = pd.bdate_range(end=end, periods=n)
    return pd.Series(range(1, n + 1), index=idx, dtype=float)


@pytest.mark.parametrize("series, status", [
    (_series("2026-09-24", 1000), "ok"),
    (_series("2026-09-24", 100), "short"),
    (_series("2026-06-30", 1000), "stale"),
    (pd.Series(dtype=float), "empty"),
    (None, "empty"),
])
def test_statuses(series, status):
    r = tc.check_ticker("X", fetch=lambda s: series, today=TODAY)
    assert r["status"] == status
    assert (r["reason"] is None) == (status == "ok")


def test_provider_errors_are_reported_not_raised():
    def boom(symbol):
        raise ConnectionError("proxy said no")
    r = tc.check_ticker("X", fetch=boom, today=TODAY)
    assert r["status"] == "error" and "ConnectionError" in r["reason"]


def test_many_and_report():
    data = {"A": _series("2026-09-24", 1000), "B": None}
    results = tc.check_many(["A", "B"], fetch=data.get, today=TODAY)
    assert [r["status"] for r in results] == ["ok", "empty"]
    md = tc.render_markdown(results)
    assert md.index("| A |") < md.index("| B |") and "1/2 ticker(s) acceptés" in md
