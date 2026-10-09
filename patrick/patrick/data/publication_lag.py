"""F01 -- point-in-time alignment of FRED series: every observation enters
the feature frame on the date it was PUBLISHED, never on its reference date.

FRED dates an observation by the start of the period it describes (the
January 2020 CPI is dated 2020-01-01, released by the BLS on 2020-02-13).
Forward-filling on the reference date let every walk-forward row between the
start of a period and its release "know" a print that did not exist yet: ~6
weeks on monthly series, ~4 months on GDP, one business day on daily series
(which also breaks backtest/live parity -- live scoring only ever sees the
previous business day's FRED value).

Availability date = end of the reference period + publication delay, per
series, from the official release calendars (BLS Employment Situation /
CPI, BEA GDP / Personal Income and Outlays, Census retail sales, Fed H.15 /
G.17, EIA spot prices, Chicago Fed NFCI, St. Louis Fed STLFSI). Delays are
deliberately the LATE end of each release window: arriving a few days late
costs a little signal, arriving early is a look-ahead. They are
approximations of calendars that move (holidays, shutdowns -- e.g. the
October 2025 CPI was never published); the exact alternative is the ALFRED
path (`data/sources/fred_source.py::download_first_release`, FRED API key),
which indexes each first release on its true `realtime_start` and also
removes the revision look-ahead this table cannot (the value used remains
the latest revision).

Unknown series: frequency inferred from the observation spacing, then the
conservative default delay of that frequency.
"""
from __future__ import annotations

import pandas as pd

from patrick.data.freshness import fred_periodicity

# Bumped whenever the alignment rule changes: stored with every cached raw
# snapshot (`data/ingest.py`) -- a cache built under another rule (or before
# F01, with no version at all) is never served again.
PIT_VERSION = "pit-publication-lag-v1"

# Daily series: business days between the reference date and FRED
# availability. Market-derived rates/spreads (H.15, ICE BofA, breakevens,
# SOFR/EFFR published the next morning): 1. EIA spot oil prices are
# published weekly (Wednesday, through the previous week): up to 7.
DAILY_LAG_BDAYS: dict[str, int] = {
    "DCOILWTICO": 7, "DCOILBRENTEU": 7,
    # Fed H.10 exchange rates: the daily fixings are released in one batch
    # every Monday for the previous week (Friday's rate waits 1 business day,
    # Monday's waits 5 -- the late end is used).
    "DEXJPUS": 5, "DEXUSUK": 5, "DEXCHUS": 5, "DEXSZUS": 5, "DEXCAUS": 5,
}
DEFAULT_DAILY_LAG_BDAYS = 1

# Weekly series are dated on the week's last day (NFCI/STLFSI4: Friday) and
# released the following Wednesday/Thursday: +7 calendar days.
DEFAULT_WEEKLY_LAG_DAYS = 7
WEEKLY_LAG_DAYS: dict[str, int] = {
    "CCSA": 14,     # continued claims: released 12 days after the week ending Saturday
    "TOTCI": 10,    # H.8: Friday release for the week ending the Wednesday before
}

# Monthly/quarterly: calendar days after the END of the reference period.
PERIOD_END_LAG_DAYS: dict[str, int] = {
    "CPIAUCSL": 20, "CPILFESL": 20,   # BLS CPI: 10th-15th of the following month
    "PAYEMS": 10, "UNRATE": 10,       # BLS Employment Situation: first Friday
    "PCE": 35, "PCEPILFE": 35,        # BEA Personal Income and Outlays: last week of M+1
    "RSAFS": 20,                      # Census advance retail sales: ~15th
    "INDPRO": 20,                     # Fed G.17: ~15th-17th
    "FEDFUNDS": 3,                    # monthly average of daily EFFR
    "UMCSENT": 3,                     # UMich final: last Friday of the same month
    "OILPRICE": 5,
    "GDP": 30,                        # BEA advance estimate: ~30 days after quarter end
    # Extended FRED data (config/defaults.py::MACRO_ONLY_FRED_SERIES)
    "GDPC1": 30, "A191RL1Q225SBEA": 30,   # same BEA advance release as GDP
    "CIVPART": 10, "EMRATIO": 10, "U6RATE": 10, "AHETPI": 10, "AWHMAN": 10,
    "UEMPMEAN": 10,                   # BLS Employment Situation, like PAYEMS/UNRATE
    "JTSJOL": 45,                     # JOLTS: ~5-6 weeks after month end
    "CPIENGSL": 20, "CPIUFDSL": 20, "CPIMEDSL": 20, "CUSR0000SAH1": 20,   # BLS CPI detail
    "STICKCPIM159SFRBATL": 25,        # Atlanta Fed, computed once the CPI is out
    "PPIACO": 20,                     # BLS PPI: ~13th-15th of the following month
    "PCEPI": 35, "PSAVERT": 35, "DSPIC96": 35,   # BEA Personal Income and Outlays
    "MICH": 3,                        # UMich final, like UMCSENT
    "HOUST": 20, "PERMIT": 20,        # Census new residential construction
    "DGORDER": 30,                    # Census advance durable goods: ~26th
    "AMTMNO": 40,                     # Census full manufacturers' shipments/orders
    "TCU": 20, "IPMAN": 20,           # Fed G.17, like INDPRO
    "TOTALSA": 10,                    # BEA unit vehicle sales: first days of M+1
    "CSUSHPINSA": 60,                 # S&P Case-Shiller: last Tuesday of M+2
    "CFNAI": 30,                      # Chicago Fed: ~4th week of M+1
    "M2SL": 30,                       # Fed H.6
    "IRLTLT01DEM156N": 45, "IRLTLT01JPM156N": 45, "IRLTLT01GBM156N": 45,   # OECD monthly yields
}
DEFAULT_MONTHLY_LAG_DAYS = 45
DEFAULT_QUARTERLY_LAG_DAYS = 95

_KNOWN_IDS = set(DAILY_LAG_BDAYS) | set(PERIOD_END_LAG_DAYS) | set(WEEKLY_LAG_DAYS) | {
    "NFCI", "STLFSI4", "DGS1", "DGS2", "DGS3", "DGS5", "DGS7", "DGS10", "DGS20", "DGS30",
    "DTB1", "DTB4WK", "DTB3", "DTB6", "DFF", "EFFR", "SOFR", "SP500", "VIXCLS", "TEDRATE",
    "T10Y2Y", "T10Y3M", "T10YIE", "T5YIE", "T5YIFR", "BAMLC0A0CM", "BAMLC0A4CBBB", "BAMLH0A0HYM2",
    # Extended FRED data: weekly (ICSA, WALCL, WTREGEN, WRESBAL, GASREGW, mortgage rates,
    # NFCI sub-indices) and daily (real yields, Moody's, spreads, prime, Cboe indices)
    "ICSA", "WALCL", "WTREGEN", "WRESBAL", "GASREGW", "MORTGAGE30US", "MORTGAGE15US",
    "NFCIRISK", "NFCICREDIT", "NFCILEVERAGE",
    "DFII10", "DFII5", "DAAA", "DBAA", "AAA10Y", "BAA10Y", "T10YFF", "T5YFF", "DPRIME",
    "VXNCLS", "RVXCLS", "OVXCLS", "GVZCLS",
}


def _infer_frequency(index: pd.DatetimeIndex) -> str:
    if len(index) < 3:
        return "monthly"
    spacing = pd.Series(index).diff().dt.days.median()
    if spacing <= 4:
        return "daily"
    if spacing <= 10:
        return "weekly"
    if spacing <= 45:
        return "monthly"
    return "quarterly"


def frequency_of(series_id: str, index: pd.DatetimeIndex) -> str:
    """Known id -> documented publication frequency; unknown id -> inferred
    from the observation spacing (never the "monthly" default blindly: a
    daily series lagged like a monthly one would lose a month of signal, a
    monthly one lagged like a daily one would leak)."""
    if series_id in _KNOWN_IDS:
        return fred_periodicity(series_id)
    return _infer_frequency(pd.DatetimeIndex(index))


def availability_dates(index: pd.DatetimeIndex, series_id: str) -> pd.DatetimeIndex:
    """Date on which each observation of `index` became publicly available."""
    idx = pd.DatetimeIndex(index)
    freq = frequency_of(series_id, idx)
    if freq == "daily":
        return idx + pd.offsets.BDay(DAILY_LAG_BDAYS.get(series_id, DEFAULT_DAILY_LAG_BDAYS))
    if freq == "weekly":
        return idx + pd.Timedelta(days=WEEKLY_LAG_DAYS.get(series_id, DEFAULT_WEEKLY_LAG_DAYS))
    if freq == "monthly":
        lag = PERIOD_END_LAG_DAYS.get(series_id, DEFAULT_MONTHLY_LAG_DAYS)
        return idx + pd.offsets.MonthEnd(0) + pd.Timedelta(days=lag)
    lag = PERIOD_END_LAG_DAYS.get(series_id, DEFAULT_QUARTERLY_LAG_DAYS)
    return idx + pd.offsets.QuarterEnd(0) + pd.Timedelta(days=lag)


def publication_delay_bars(series_id: str, index: pd.DatetimeIndex) -> int:
    """Publication delay of a FRED series in BUSINESS-DAY bars: how long after the end of the
    period an observation describes it becomes public (1 for a daily H.15 rate, 5 for a weekly
    NFCI, ~14 for a monthly CPI...). Same tables as `availability_dates`, expressed in the
    daily bars of the feature frame.

    Used by `data/alignment.py`: a FRED target sits on its availability dates (F01), so its next
    label covers the period that ends one delay before the row's date. Market data observed on
    that row's date already contains that period -- the label would be a nowcast of numbers the
    features have seen (SP500 vs ^GSPC: correlation 1.0)."""
    idx = pd.DatetimeIndex(index)
    freq = frequency_of(series_id, idx)
    if freq == "daily":
        return DAILY_LAG_BDAYS.get(series_id, DEFAULT_DAILY_LAG_BDAYS)
    if freq == "weekly":
        days = WEEKLY_LAG_DAYS.get(series_id, DEFAULT_WEEKLY_LAG_DAYS)
    elif freq == "monthly":
        days = PERIOD_END_LAG_DAYS.get(series_id, DEFAULT_MONTHLY_LAG_DAYS)
    else:
        days = PERIOD_END_LAG_DAYS.get(series_id, DEFAULT_QUARTERLY_LAG_DAYS)
    return max(1, round(days * 5 / 7))


def to_availability_index(s: pd.Series, series_id: str) -> pd.Series:
    """`s` re-indexed on its availability dates (sorted; when two
    observations become available the same day, the later reference period
    wins)."""
    s = s.dropna()
    if s.empty:
        return s
    out = pd.Series(s.values, index=availability_dates(s.index, series_id), name=s.name)
    out = out[~out.index.duplicated(keep="last")]
    return out.sort_index()


def align_to_calendar(s: pd.Series, calendar: pd.DatetimeIndex) -> pd.Series:
    """Last value AVAILABLE on or before each date of `calendar`, series by
    series. Aligning a concatenation of series with different calendars in
    one `reindex(method="ffill")` can skip a value entirely: when it becomes
    available on a non-business day and another series' date falls before
    the next business day, the forward fill lands on a row that is NaN for
    this series."""
    union = calendar.union(s.index)
    return s.reindex(union).ffill().reindex(calendar)


def align_fred_frame(fred_df: pd.DataFrame, series_map: dict[str, str],
                     calendar: pd.DatetimeIndex, already_point_in_time: bool = False) -> pd.DataFrame:
    """Every column of `fred_df` (named as in `series_map`, {column: FRED
    id}) moved to its availability dates -- unless `already_point_in_time`
    (ALFRED first releases, already indexed on `realtime_start`) -- then
    aligned on `calendar`."""
    cols = {}
    for col in fred_df.columns:
        s = fred_df[col].dropna()
        if not already_point_in_time:
            s = to_availability_index(s, series_map.get(col, col))
        cols[col] = align_to_calendar(s, calendar)
    return pd.DataFrame(cols, index=calendar)
