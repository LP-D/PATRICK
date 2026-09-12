"""Per-asset stats panel for `/commodities` and `/macro` (reduced-universe
pages, config/defaults.py::DEFAULT_TARGET_GROUPS "Matières premières
(futures)" and "Macro (FRED)"): returns, rolling z-score, rolling moving
averages, volatility -- computed directly from the asset's own price/level
series, as a DISPLAY stat (simple pct-change/rolling window over N bars),
never by invoking the ML pipeline.

Reuse, not reinvention: `features/technical.py::returns/zscore/ma_ratio`
already compute exactly these primitives (and already use
`safe_pct_change`, which matters here -- some Macro (FRED) series, e.g.
T10Y2Y, cross zero, see `_utils.py` docstring) for the walk-forward feature
pool; this module calls them on demand for a single symbol instead of
duplicating the rolling-window math. Volatility alone comes from
`features/vol_models.py::heston_proxy_features` rather than
`technical.rolling_vol` -- see `_VOL_MIN_HISTORY` below for why that
specific estimator.

BARS, NOT CALENDAR TIME: every window below (horizons, long-window returns,
z-score, moving averages) counts BARS of the series' own native frequency,
never calendar days. This page mixes daily series (commodity futures) with
monthly/quarterly ones (several Macro (FRED) series: CPI, GDP, PAYEMS,
RSAFS, UMCSENT, UNRATE...) -- a "252-day" label would be honest for Gold
and silently wrong for GDP (252 quarters = 63 years). Bar counts are always
correct; only their calendar meaning varies by asset, exactly like
`DEFAULT_HORIZONS` already does everywhere else in this pipeline (a
`RunConfig.objective.horizons` of 5 means "5 bars ahead" whether the target
is `^VIX` or `CPIAUCSL`)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from patrick.config.defaults import DEFAULT_HORIZONS
from patrick.features.technical import ma_ratio as tech_ma_ratio
from patrick.features.technical import returns as tech_returns
from patrick.features.technical import zscore as tech_zscore
from patrick.features.vol_models import heston_proxy_features

# "Longer-window view" required in addition to DEFAULT_HORIZONS's short
# 1-10 bar reads -- 21/63/252 bars, the conventional "month/quarter/year"
# trio for a DAILY series (kept as plain bar counts in the API/labels, see
# module docstring, rather than mislabeled "1m"/"3m"/"1y").
LONG_WINDOWS_BARS = [21, 63, 252]

# Rolling z-score lookback: 60 bars (~1 quarter for a daily series) --
# matches the `_zscore_60d` naming already used by the feature pipeline
# (e.g. `IDX_GSPC_zscore_60d`, `features/technical.py::zscore`'s own
# default windows include 60), so the same window means the same thing
# here and in the model's own features.
ZSCORE_WINDOW = 60

# Moving-average windows: 20/50/200 bars -- the three conventional MA
# windows in technical analysis (short/medium/long), already the shape
# `technical.ma_ratio` exposes as `vs_ma{w}` (price vs its own MA, not the
# raw MA level: a single normalized "how far above/below its trend" number
# reads faster than an absolute price the viewer must mentally compare).
MA_WINDOWS = [20, 50, 200]

# Below this many observations, any of the above is noise, not signal --
# the panel shows its empty state rather than a number computed on close
# to nothing.
MIN_HISTORY_FOR_STATS = 30

# `heston_proxy_features` (short_window=20, long_window=252, min_periods=60
# on the long window) needs roughly 20 + 60 = 80 observations before its
# long-run `heston_theta` stops being NaN -- 90 is that plus a safety
# margin, not a re-derivation of the estimator's own internals.
_VOL_MIN_HISTORY = 90

# flexibility-gaps Gap 1: `ZSCORE_WINDOW`/`MA_WINDOWS`/`LONG_WINDOWS_BARS`
# above are display defaults, not hard limits -- PATRICK is an exploratory
# research platform (see session brief), so `/api/asset-stats/{symbol}`
# accepts `?zscore_window=`/`?ma_windows=`/`?long_windows_bars=` overrides
# (`webapp/app.py::asset_stats_api`) rather than forcing every viewer to the
# same three windows. This cap is the only hard limit: a sanity bound
# against a window so large it would be silently meaningless (more bars
# than any series this app ever loads -- `period="5y"` on daily data is
# ~1260 bars) or expensive to compute, not a re-derivation of any
# statistical constraint.
MAX_WINDOW_BARS = 5000


class InvalidWindowError(ValueError):
    """Raised by `validate_window`/`parse_window_list` for a user-supplied
    window that fails validation -- message is safe to surface verbatim as
    an HTTP 400 `detail` (`webapp/app.py::asset_stats_api`)."""


def validate_window(value: int, *, name: str = "window") -> int:
    """Positive-integer, sane-upper-bound guard for a single user-supplied
    bar-count window. `name` is only used to make the error message point
    at the right query parameter."""
    if value <= 0:
        raise InvalidWindowError(
            f"{name} doit être un entier positif (reçu {value})."
        )
    if value > MAX_WINDOW_BARS:
        raise InvalidWindowError(
            f"{name} ne peut pas dépasser {MAX_WINDOW_BARS} barres (reçu {value})."
        )
    return value


def parse_window_list(raw: str | None, default: list[int], *, name: str = "windows") -> list[int]:
    """Parses a comma-separated list of bar-count windows, e.g.
    `?ma_windows=20,50,100`. `None` or blank keeps `default` (the module's
    own `MA_WINDOWS`/`LONG_WINDOWS_BARS`) unchanged -- the "default
    unchanged if unspecified" rule from the session brief. Each entry is
    validated with `validate_window`."""
    if raw is None or not raw.strip():
        return list(default)
    out: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            value = int(part)
        except ValueError as exc:
            raise InvalidWindowError(
                f"{name} doit être une liste d'entiers séparés par des virgules (valeur invalide : {part!r})."
            ) from exc
        out.append(validate_window(value, name=name))
    if not out:
        raise InvalidWindowError(f"{name} ne peut pas être une liste vide.")
    return out


def compute_stats(
    series: dict,
    *,
    zscore_window: int = ZSCORE_WINDOW,
    ma_windows: list[int] | None = None,
    long_windows_bars: list[int] | None = None,
) -> dict:
    """`series` is exactly the dict `market_data.price_history()` returns
    (the same data-access path already used by `/api/preview/{symbol}` --
    no second fetch mechanism here): `{"dates": [...], "closes": [...]}`,
    optionally `{"error": "..."}` when the upstream fetch itself failed.

    Returns a JSON-serializable dict for `/api/asset-stats/{symbol}` and
    `asset_stats.js`. Every stat is `None` (never a crash, never a
    silently-omitted key) when history is insufficient for THAT stat
    specifically -- the frontend renders the explicit empty state per
    field, matching the rest of the product's "no number without its
    reliability" rule (`_components.html::metric`).

    `zscore_window`/`ma_windows`/`long_windows_bars` default to this
    module's `ZSCORE_WINDOW`/`MA_WINDOWS`/`LONG_WINDOWS_BARS` -- callers
    (`webapp/app.py::asset_stats_api`) pass overrides validated via
    `validate_window`/`parse_window_list`. The response's `zscore_60d` key
    name is kept stable (matches `asset_stats.js`) even when a non-default
    `zscore_window` is used -- its VALUE reflects whichever window was
    requested, only the JSON key stays fixed."""
    ma_windows = list(MA_WINDOWS) if ma_windows is None else list(ma_windows)
    long_windows_bars = list(LONG_WINDOWS_BARS) if long_windows_bars is None else list(long_windows_bars)
    dates = series.get("dates") or []
    closes = series.get("closes") or []
    out: dict = {
        "n_obs": len(closes),
        "error": series.get("error"),
        "insufficient_history": len(closes) < MIN_HISTORY_FOR_STATS,
        "dates": dates,
        "closes": closes,
        "returns": {},
        "long_window_returns": {},
        "zscore_60d": None,
        "moving_averages": {},
        "volatility": None,
    }
    if out["insufficient_history"] or out["error"]:
        return out

    s = pd.Series(closes, index=pd.to_datetime(dates))

    ret_h = tech_returns(s, windows=list(DEFAULT_HORIZONS))
    for h in DEFAULT_HORIZONS:
        out["returns"][str(h)] = _last_or_none(ret_h[f"ret_{h}d"])

    ret_long = tech_returns(s, windows=long_windows_bars)
    for w in long_windows_bars:
        out["long_window_returns"][str(w)] = _last_or_none(ret_long[f"ret_{w}d"])

    z = tech_zscore(s, windows=[zscore_window])
    out["zscore_60d"] = _last_or_none(z[f"zscore_{zscore_window}d"])

    ma = tech_ma_ratio(s, windows=ma_windows)
    for w in ma_windows:
        out["moving_averages"][str(w)] = _last_or_none(ma[f"vs_ma{w}"])

    if len(s) >= _VOL_MIN_HISTORY:
        heston = heston_proxy_features(s)
        theta = heston["heston_theta"].iloc[-1]
        spread = heston["heston_spread"].iloc[-1]
        if not pd.isna(theta) and not pd.isna(spread):
            rv_current = theta + spread  # heston_spread = rv - heston_theta
            out["volatility"] = {
                # heston_theta/rv are annualized realized VARIANCE
                # (ret**2-based, see vol_models.py) -- sqrt() turns them
                # into the annualized realized vol level actually shown.
                "annualized_long_run": float(np.sqrt(max(theta, 0.0))),
                "annualized_current": float(np.sqrt(max(rv_current, 0.0))),
            }

    return out


def _last_or_none(col: pd.Series) -> float | None:
    if col.empty:
        return None
    v = col.iloc[-1]
    return None if pd.isna(v) else float(v)
