"""Extended FRED data (`config/defaults.py::MACRO_ONLY_FRED_SERIES`): series
used for training only -- never a target, never displayed, "macro" feature
family only, point-in-time aligned like every other FRED series."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.config import defaults as D
from patrick.config.schema import RunConfig
from patrick.data import freshness, publication_lag, quality
from patrick.pipeline import engine as engine_module

# Publication frequency of every extended series, as reported by the FRED API
# (`frequency_short`) when the list was built on 2026-10-07.
_FREQ = {
    "daily": {"DFII10", "DFII5", "DAAA", "DBAA", "AAA10Y", "BAA10Y", "T10YFF", "T5YFF", "DPRIME",
              "VXNCLS", "RVXCLS", "OVXCLS", "GVZCLS", "DEXJPUS", "DEXUSUK", "DEXCHUS", "DEXSZUS", "DEXCAUS"},
    "weekly": {"ICSA", "CCSA", "GASREGW", "WALCL", "WTREGEN", "WRESBAL", "TOTCI", "MORTGAGE30US",
               "MORTGAGE15US", "NFCIRISK", "NFCICREDIT", "NFCILEVERAGE"},
    "quarterly": {"GDPC1", "A191RL1Q225SBEA"},
}
_FREQ["monthly"] = set(D.MACRO_ONLY_FRED_SERIES.values()) - set().union(*_FREQ.values())


def test_extended_series_are_never_targets():
    ids = list(D.MACRO_ONLY_FRED_SERIES.values())
    assert len(ids) == len(set(ids)), "duplicate FRED id"
    displayed = {s for s, _, _ in D.DEFAULT_TARGET_CHOICES}
    displayed_labels = {label for _, label, _ in D.DEFAULT_TARGET_CHOICES}
    assert not set(ids) & displayed
    assert not set(D.MACRO_ONLY_FRED_SERIES) & displayed_labels
    assert not set(ids) & set(D.FEATURE_ONLY_FRED_SERIES.values())
    assert set(D.MACRO_ONLY_FRED_SERIES.items()) <= set(D.DEFAULT_UNIVERSE_FRED_SERIES.items())
    # The elementary indicators stay the only targetable ones.
    assert {"GDP", "UNRATE", "CPIAUCSL", "PAYEMS"} <= displayed
    from patrick.webapp import forms
    assert not set(ids) & set(forms.TARGET_SOURCE_BY_SYMBOL)


def test_macro_page_sections_cover_every_fred_series_exactly_once():
    listed = [sid for _, ids in D.MACRO_PAGE_SECTIONS for sid in ids]
    assert len(listed) == len(set(listed)), "a series appears in two sections"
    assert set(listed) == set(D.DEFAULT_UNIVERSE_FRED_SERIES.values())
    assert D.MACRO_DISPLAY_IDS == frozenset(listed)
    sections = D.macro_page_sections()
    assert sum(len(series) for _, series in sections) == len(D.DEFAULT_UNIVERSE_FRED_SERIES)


def test_macro_page_opens_with_the_headline_indicators():
    sections = D.macro_page_sections()
    assert sections[0][0] == "key"
    assert {"GDP", "UNRATE", "CPIAUCSL", "FEDFUNDS"} <= {sid for sid, _ in sections[0][1]}
    # Each section's title exists in both languages.
    from patrick.webapp import i18n
    for key, _ in sections:
        assert i18n.STRINGS[f"macro_section_{key}"]["fr"] and i18n.STRINGS[f"macro_section_{key}"]["en"]


def test_extended_labels_do_not_collide_with_other_columns():
    from patrick.data.sources.yfinance_source import clean_symbol

    labels = list(D.MACRO_ONLY_FRED_SERIES)
    others = {clean_symbol(t) for t in D.DEFAULT_UNIVERSE_YF_TICKERS} | {
        label for _, label, _ in D.DEFAULT_TARGET_CHOICES} | set(D.FEATURE_ONLY_FRED_SERIES)
    assert not set(labels) & others


@pytest.mark.parametrize("freq", ["daily", "weekly", "monthly", "quarterly"])
def test_publication_tables_agree_with_the_fred_frequency(freq):
    for sid in sorted(_FREQ[freq]):
        assert sid in publication_lag._KNOWN_IDS, f"{sid}: add it to publication_lag"
        assert freshness.fred_periodicity(sid) == freq, f"{sid}: freshness table says otherwise"


def test_every_monthly_and_quarterly_series_has_an_explicit_release_delay():
    """The default delay (45 / 95 days) is only a fallback for unknown ids."""
    for sid in sorted(_FREQ["monthly"] | _FREQ["quarterly"]):
        assert sid in publication_lag.PERIOD_END_LAG_DAYS, f"{sid}: no release delay"


def test_release_delays_never_precede_the_publication():
    def avail(sid, date):
        return publication_lag.availability_dates(pd.DatetimeIndex([date]), sid)[0]

    # Continued claims: week ending Sat 2026-09-19 is published 12 days later.
    assert avail("CCSA", "2026-09-19") >= pd.Timestamp("2026-10-01")
    # H.10 FX: the Monday fixing is only published the Monday after.
    assert avail("DEXJPUS", "2026-09-28") >= pd.Timestamp("2026-10-05")
    # Q2 GDP (dated 2026-04-01) is not out before the end of July.
    assert avail("GDPC1", "2026-04-01") >= pd.Timestamp("2026-07-30")
    # August CPI energy (dated 2026-08-01) comes in mid-September.
    assert avail("CPIENGSL", "2026-08-01") >= pd.Timestamp("2026-09-10")


def _weekly_series(spike: bool) -> pd.Series:
    idx = pd.date_range("2018-01-06", "2026-09-26", freq="7D")
    values = np.full(len(idx), 200_000.0) + np.arange(len(idx)) * 10
    if spike:
        values[130] *= 10     # a real, March-2020-like jump
    return pd.Series(values, index=idx, name="x")


def test_real_shocks_do_not_exclude_an_extended_series():
    end = pd.Timestamp("2026-10-05")
    spiky = _weekly_series(spike=True)
    assert quality.check_fred_series(spiky, "ICSA", end) is None
    # Any other FRED series keeps the aberrant-return gate.
    issue = quality.check_fred_series(spiky, "UNRATE_X", end)
    assert issue is not None and issue.reason == "rendement_aberrant"


def _config(families, fred_series) -> RunConfig:
    return RunConfig.model_validate({
        "name": "x", "objective": {"target_symbol": "^T", "horizons": [5]},
        "universe": {"yf_tickers": [], "fred_series": fred_series},
        "features": {"families": families, "vol_models": ["kalman"]},
    })


def _raw(cols, n=400, seed=1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame({c: 50 + np.cumsum(rng.normal(0, 0.5, n)) for c in cols},
                        index=pd.bdate_range("2020-01-01", periods=n))


def test_extended_series_get_the_macro_family_only(monkeypatch):
    monkeypatch.setattr(engine_module, "download_ohlc", lambda *a, **k: None)
    fred = {"NFCI": "NFCI", "Real_GDP": "GDPC1"}
    raw = _raw(["IDX_T", "NFCI", "Real_GDP"])
    pool = engine_module._build_base_feature_pool(
        raw, _config(["technical", "long_cycle", "macro"], fred), "IDX_T")

    extended = {c for c in pool.columns if c == "Real_GDP" or c.startswith("Real_GDP_")}
    assert extended == {"Real_GDP", "Real_GDP_level", "Real_GDP_ret_5d", "Real_GDP_vol_20d",
                        "Real_GDP_lag1", "Real_GDP_lag5", "Real_GDP_lag10"}
    ordinary = {c for c in pool.columns if c == "NFCI" or c.startswith("NFCI_")}
    assert len(ordinary) > len(extended)      # technical + long_cycle on top of macro


def test_extended_series_skip_the_parametric_models(monkeypatch):
    seen: list[str] = []

    def fake(series, prefix, **kwargs):
        seen.append(prefix)
        return pd.DataFrame(index=series.index)

    monkeypatch.setattr(engine_module.vol_models, "build_vol_model_features_parametric", fake)
    fred = {"NFCI": "NFCI", "Real_GDP": "GDPC1"}
    raw = _raw(["IDX_T", "NFCI", "Real_GDP"])
    engine_module._build_parametric_pool(raw, _config(["vol_models"], fred), None, None, None, None)
    assert seen == ["IDX_T", "NFCI"]
