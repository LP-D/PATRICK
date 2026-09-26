"""Generic event study (MacKinlay 1997): abnormal returns around dated events
-- product announcements (Apple keynotes), streaming subscriber releases,
macro prints, any timestamped news.

Pipeline per event:
1. **Point-in-time day 0** (`event_day_zero`): an event published AFTER the
   market close (or on a non-trading day) can only move prices on the NEXT
   session; using its calendar date would credit the pre-announcement
   session with information it did not have. Same guard NLP / alternative
   data must go through (publication timestamp, never the story's date).
2. **Normal-return model** fit on an estimation window strictly before the
   event window (default [-250, -21] sessions): `market` (OLS alpha + beta
   on a benchmark), `market_adjusted` (beta = 1, alpha = 0) or
   `constant_mean`.
3. **Abnormal returns** AR_t = R_t - E[R_t] on the event window (default
   [-5, +20]), cumulated (CAR).

Aggregation and tests over N events:
- cross-sectional t-test of CAR (sensitive to event-induced variance);
- Patell (1976) standardized test (CARs scaled by their estimation-window
  standard deviation, with the market-model forecast-error correction);
- Boehmer-Musumeci-Poulsen (1991): cross-sectional variance of the
  standardized CARs -- robust to event-induced variance increases, the
  default verdict;
- sign test (share of positive CARs vs 0.5).

Clustering: events whose event windows overlap (same asset) are not
independent -- flagged (`overlapping_events`), and the cross-sectional tests
then overstate significance; a calendar-time portfolio is the remedy
(not implemented here).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import stats

MODELS = ("market", "market_adjusted", "constant_mean")


def event_day_zero(event_ts, trading_days: pd.DatetimeIndex, market_close: str = "16:00",
                   market_tz: str = "America/New_York") -> pd.Timestamp | None:
    """First trading session whose close is strictly after the event's
    publication. `event_ts`: a date (assumed pre-open, same day is day 0) or
    a timestamp (naive = market timezone). After-close or non-trading-day
    events move to the next session. `None` if beyond the calendar."""
    ts = pd.Timestamp(event_ts)
    days = pd.DatetimeIndex(trading_days).normalize()
    has_time = ts.hour or ts.minute or ts.second
    if ts.tzinfo is not None:
        ts = ts.tz_convert(market_tz).tz_localize(None)
    day = ts.normalize()
    if has_time:
        close = pd.Timestamp(f"{day.date()} {market_close}")
        if ts >= close:  # a 16:00:00 stamp (Yahoo's after-close earnings convention) is not in the close
            day = day + pd.Timedelta(days=1)
    pos = days.searchsorted(day)
    return days[pos] if pos < len(days) else None


@dataclass
class EventResult:
    event: pd.Timestamp
    day_zero: pd.Timestamp
    label: str | None
    ar: pd.Series                   # abnormal returns indexed by relative day
    car: float
    sigma_est: float                # std of estimation-window residuals
    scar: float                     # standardized CAR (Patell)
    n_est: int
    resid_est: pd.Series | None = None   # estimation-window abnormal returns (placebo distribution)


@dataclass
class EventStudy:
    results: list[EventResult]
    window: tuple[int, int]
    model: str
    skipped: list[dict] = field(default_factory=list)
    overlapping_events: list[tuple[str, str]] = field(default_factory=list)

    @property
    def n_events(self) -> int:
        return len(self.results)

    def aar(self) -> pd.Series:
        """Average abnormal return per relative day."""
        return pd.concat([r.ar for r in self.results], axis=1).mean(axis=1)

    def caar(self) -> pd.Series:
        return self.aar().cumsum()

    def abnormal_variance(self, window: tuple[int, int] = (0, 1)) -> dict:
        """Does the price move MORE than usual around the event, whatever
        the direction? For events whose sign is unknown ex ante (keynotes,
        earnings without the surprise), where positive and negative
        reactions cancel in the CAAR.
        - chi2: z_i = CAR_i[window] / (sigma_i sqrt(L)), sum z_i^2 ~ chi2(n)
          under H0 -- assumes Gaussian abnormal returns, over-rejects under
          fat tails;
        - rank (default verdict): percentile of |CAR_i[window]| among the
          |L-day sums| of its own estimation-window abnormal returns,
          U(0, 1) under H0 whatever the tails; mean percentile tested
          one-sided (Normal approximation, variance 1/(12 n)). Volatility
          clustering around events still breaks exchangeability -- read with
          the estimation window's calm/stress context in mind."""
        a, b = window
        length = b - a + 1
        z2, pct = [], []
        for r in self.results:
            s = float(r.ar.loc[a:b].sum())
            if r.sigma_est > 0:
                z2.append(s ** 2 / (length * r.sigma_est ** 2))
            if r.resid_est is not None and len(r.resid_est) > length:
                placebo = np.abs(r.resid_est.rolling(length).sum().dropna().to_numpy())
                pct.append(float((placebo < abs(s)).mean() + 0.5 * (placebo == abs(s)).mean()))
        n, m = len(z2), len(pct)
        mean_pct = float(np.mean(pct)) if m else np.nan
        z_rank = (mean_pct - 0.5) / np.sqrt(1 / (12 * m)) if m else np.nan
        return {
            "window": window, "n_events": n,
            "mean_z2": float(np.mean(z2)) if n else np.nan,
            "p_chi2": float(stats.chi2.sf(float(np.sum(z2)), n)) if n else np.nan,
            "mean_percentile": mean_pct,
            "p_rank": float(stats.norm.sf(z_rank)) if m else np.nan,
        }

    def tests(self, window: tuple[int, int] | None = None) -> dict:
        """Signed tests on the full event window, or on a sub-window
        (e.g. the [0, +1] reaction): CAR summed over it, standardized by
        sigma sqrt(L) -- the market-model estimation correction (O(L / n_est),
        ~1 % here) is dropped on sub-windows."""
        if window is None:
            cars = np.array([r.car for r in self.results])
            scars = np.array([r.scar for r in self.results])
        else:
            a, b = window
            length = b - a + 1
            cars = np.array([float(r.ar.loc[a:b].sum()) for r in self.results])
            sig = np.array([r.sigma_est for r in self.results])
            scars = np.where(sig > 0, cars / (sig * np.sqrt(length)), np.nan)
        n = len(cars)
        if n < 2:
            return {"n_events": n, "caar": float(cars.mean()) if n else np.nan}
        t_cs = cars.mean() / (cars.std(ddof=1) / np.sqrt(n))
        z_patell = scars.sum() / np.sqrt(n)
        t_bmp = scars.mean() / (scars.std(ddof=1) / np.sqrt(n))
        n_pos = int((cars > 0).sum())
        return {
            "n_events": n,
            "caar": float(cars.mean()),
            "t_cross_sectional": float(t_cs),
            "p_cross_sectional": float(2 * stats.t.sf(abs(t_cs), n - 1)),
            "z_patell": float(z_patell),
            "p_patell": float(2 * stats.norm.sf(abs(z_patell))),
            "t_bmp": float(t_bmp),
            "p_bmp": float(2 * stats.t.sf(abs(t_bmp), n - 1)),
            "share_positive": n_pos / n,
            "p_sign": float(stats.binomtest(n_pos, n, 0.5).pvalue),
            "overlapping_events": len(self.overlapping_events),
        }


def _returns(prices: pd.Series) -> pd.Series:
    return np.log(prices.astype(float)).diff()


def run_event_study(prices: pd.Series, events, benchmark: pd.Series | None = None,
                    model: str = "market", estimation_window: tuple[int, int] = (-250, -21),
                    event_window: tuple[int, int] = (-5, 20), labels: list[str] | None = None,
                    market_close: str = "16:00", market_tz: str = "America/New_York",
                    min_estimation_obs: int = 60) -> EventStudy:
    """`prices`: asset price series (trading-day index). `events`: dates or
    publication timestamps. `benchmark`: required for `market` /
    `market_adjusted`. Windows in trading sessions relative to day 0."""
    if model not in MODELS:
        raise ValueError(f"unknown model {model!r} (expected one of {MODELS})")
    if model != "constant_mean" and benchmark is None:
        raise ValueError(f"model {model!r} needs a benchmark series")
    if not estimation_window[1] < event_window[0]:
        raise ValueError("the estimation window must end before the event window starts")

    r = _returns(prices).dropna()
    rm = _returns(benchmark).reindex(r.index) if benchmark is not None else None
    days = r.index
    results: list[EventResult] = []
    skipped: list[dict] = []
    labels = labels or [None] * len(list(events))
    windows: list[tuple[pd.Timestamp, int, int, str]] = []

    for ev, label in zip(events, labels):
        d0 = event_day_zero(ev, days, market_close, market_tz)
        if d0 is None:
            skipped.append({"event": str(ev), "reason": "after the price history"})
            continue
        i0 = days.get_loc(d0)
        e0, e1 = i0 + estimation_window[0], i0 + estimation_window[1]
        w0, w1 = i0 + event_window[0], i0 + event_window[1]
        if e0 < 0 or w1 >= len(days):
            skipped.append({"event": str(ev), "reason": "windows outside the price history"})
            continue
        est = slice(e0, e1 + 1)
        y_est = r.iloc[est]
        if model == "market":
            x_est = rm.iloc[est]
            ok = y_est.notna() & x_est.notna()
            if ok.sum() < min_estimation_obs:
                skipped.append({"event": str(ev), "reason": "too few estimation observations"})
                continue
            beta, alpha = np.polyfit(x_est[ok].values, y_est[ok].values, 1)
            resid = y_est[ok] - (alpha + beta * x_est[ok])
            x_bar, sxx = x_est[ok].mean(), ((x_est[ok] - x_est[ok].mean()) ** 2).sum()
        else:
            resid = y_est - (rm.iloc[est] if model == "market_adjusted" else y_est.mean())
            resid = resid.dropna()
            if len(resid) < min_estimation_obs:
                skipped.append({"event": str(ev), "reason": "too few estimation observations"})
                continue
        n_est = len(resid)
        dof = n_est - (2 if model == "market" else 1 if model == "constant_mean" else 0)
        sigma = float(np.sqrt((resid ** 2).sum() / max(dof, 1)))

        win = slice(w0, w1 + 1)
        y_win = r.iloc[win]
        if model == "market":
            expected = alpha + beta * rm.iloc[win]
        elif model == "market_adjusted":
            expected = rm.iloc[win]
        else:
            expected = pd.Series(y_est.mean(), index=y_win.index)
        ar = (y_win - expected)
        ar.index = range(event_window[0], event_window[1] + 1)
        car = float(ar.sum())
        length = event_window[1] - event_window[0] + 1
        if model == "market":
            x_win = rm.iloc[win]
            correction = length / n_est + ((x_win.sum() - length * x_bar) ** 2) / (length * sxx) if sxx > 0 else 0.0
            var_car = sigma ** 2 * (length + length * correction)
        else:
            var_car = sigma ** 2 * length
        scar = car / np.sqrt(var_car) if var_car > 0 else np.nan
        results.append(EventResult(pd.Timestamp(ev), d0, label, ar, car, sigma, float(scar), n_est,
                                   resid_est=resid.reset_index(drop=True)))
        windows.append((d0, w0, w1, label or str(d0.date())))

    overlaps = []
    for a in range(len(windows)):
        for b in range(a + 1, len(windows)):
            if windows[a][1] <= windows[b][2] and windows[b][1] <= windows[a][2]:
                overlaps.append((windows[a][3], windows[b][3]))
    return EventStudy(results, event_window, model, skipped, overlaps)


def _fmt(x: float, pct: bool = False) -> str:
    if x is None or not np.isfinite(x):
        return "—"
    return f"{x * 100:+.2f} %" if pct else f"{x:.3f}"


def render_markdown(groups: dict[str, EventStudy], title: str, reaction_window: tuple[int, int] = (0, 1)) -> str:
    """One summary row per group (all events, or e.g. beat / miss), then the
    per-event table. Signed tests answer "which direction on average", the
    variance tests "does the price move more than usual"."""
    a, b = reaction_window
    lines = [f"# {title}", "",
             (f"Réaction mesurée sur [{a}, +{b}] séances autour de J0 (J0 = première séance dont la clôture "
              "suit strictement la publication). Rendements anormaux LOGARITHMIQUES (-43 % log = -35 % simple). "
              "Verdict signé : BMP ; verdict non signé : test de rang (robuste aux queues épaisses, le χ² "
              "est indicatif)."), "",
             "| Groupe | N | CAAR réaction | p BMP | p signe | CAAR fenêtre | p BMP fenêtre | z² moyen | p rang | p χ² |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name, study in groups.items():
        if not study.n_events:
            lines.append(f"| {name} | 0 | — | — | — | — | — | — | — | — |")
            continue
        full = study.tests()
        react = study.tests(reaction_window)
        v = study.abnormal_variance(reaction_window)
        lines.append(f"| {name} | {study.n_events} | {_fmt(react['caar'], True)} | "
                     f"{_fmt(react.get('p_bmp', np.nan))} | {_fmt(react.get('p_sign', np.nan))} | "
                     f"{_fmt(full['caar'], True)} | {_fmt(full.get('p_bmp', np.nan))} | "
                     f"{_fmt(v['mean_z2'])} | {_fmt(v['p_rank'])} | {_fmt(v['p_chi2'])} |")
    lines += ["", "| Événement | Publication | J0 | AR J0 | CAR réaction | CAR fenêtre | σ estim. |",
              "|---|---|---|---:|---:|---:|---:|"]
    rows = sorted((r for s in groups.values() for r in s.results), key=lambda r: r.day_zero)
    seen = set()
    for r in rows:
        if (r.event, r.label) in seen:
            continue
        seen.add((r.event, r.label))
        lines.append(f"| {r.label or '—'} | {r.event:%Y-%m-%d %H:%M} | {r.day_zero:%Y-%m-%d} | "
                     f"{_fmt(float(r.ar.loc[0]), True)} | {_fmt(float(r.ar.loc[a:b].sum()), True)} | "
                     f"{_fmt(r.car, True)} | {r.sigma_est * 100:.2f} % |")
    skipped = [s for st in groups.values() for s in st.skipped]
    overlaps = [o for st in groups.values() for o in st.overlapping_events]
    if skipped:
        lines += ["", f"Événements écartés : {len(skipped)} — " +
                  "; ".join(f"{s['event']} ({s['reason']})" for s in skipped[:10])]
    if overlaps:
        lines += ["", (f"Fenêtres qui se chevauchent : {len(overlaps)} paire(s) — les tests en coupe "
                       "surestiment alors la significativité.")]
    return "\n".join(lines)
