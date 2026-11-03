"""Panel d'événements : le tableau (un événement par ligne) sur lequel travaillent toutes les études.

Toute colonne « historique » d'un titre (moyenne passée de ses réactions, surprise standardisée, série de dépassements...) est
calculée sur ses événements STRICTEMENT antérieurs : la statistique d'un événement ne contient jamais l'événement testé (fuite
d'information) et ne regarde jamais le futur. Les colonnes `sector_hist_*` suivent la même règle sur tous les titres du secteur.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from patrick.clock import local_now
from patrick.earnings import engine, exchanges, store
from patrick.earnings.config import EarningsConfig
from patrick.earnings.engine import arr, bhar, rel_index, window_sum


@dataclass(frozen=True)
class Scope:
    """Périmètre d'une étude : tout, un titre, un secteur, un pays, la semaine collée (lot) ou une semaine de calendrier."""
    kind: str = "all"
    value: str = ""

    @property
    def key(self) -> str:
        return self.kind if self.kind == "all" else f"{self.kind}:{self.value}"

    @classmethod
    def parse(cls, text: str | None) -> Scope:
        if not text or text == "all":
            return cls()
        kind, _, value = text.partition(":")
        if kind not in ("symbol", "sector", "country", "batch", "week"):
            raise ValueError(f"périmètre inconnu : {text!r}")
        return cls(kind, value)


def _fiscal_period(ann: date, fye_month: int | None) -> tuple[date | None, bool]:
    """Fin de la période que l'annonce commente (dernier trimestre clos au moins 10 jours avant elle) et indicateur annuel."""
    if not fye_month:
        return None, False
    quarter_months = {((fye_month - 1 + 3 * k) % 12) + 1 for k in range(4)}
    probe = pd.Timestamp(ann) - pd.Timedelta(days=10)
    month_end = probe + pd.offsets.MonthEnd(0)                    # fin du mois de `probe` (lui-même s'il l'est déjà)
    if month_end > probe:
        month_end = month_end - pd.offsets.MonthEnd(1)            # dernière fin de mois qui ne dépasse pas `probe`
    for _ in range(12):
        if month_end.month in quarter_months:
            return month_end.date(), month_end.month == fye_month
        month_end = month_end - pd.offsets.MonthEnd(1)
    return None, False


def _frame(rows: list[dict], instruments: dict[str, dict], cfg: EarningsConfig) -> pd.DataFrame:
    recs = []
    r0, r1 = rel_index(0), rel_index(1)
    for i, r in enumerate(rows):
        ins = instruments.get(r["symbol"], {})
        venue = exchanges.venue_for(r["symbol"])
        react = engine.reaction_stats(r, cfg)
        ar = arr(r, "ar")
        on, idr, vr = arr(r, "on"), arr(r, "id"), arr(r, "vol_ratio")
        am, cs = arr(r, "amihud"), arr(r, "cs")
        fye = ins.get("lastFiscalYearEnd")
        fye_month = int(pd.Timestamp(fye, unit="s").month) if fye else None
        period_end, is_annual = _fiscal_period(pd.Timestamp(r["ann_date"]).date(), fye_month)
        rec = {
            "i": i, "symbol": r["symbol"], "ann_date": r["ann_date"], "day0": r["day0"],
            "weekday": int(pd.Timestamp(r["ann_date"]).weekday()), "week": pd.Timestamp(r["day0"]).strftime("%G-W%V"),
            "year": int(pd.Timestamp(r["day0"]).year), "timing": r["timing"], "uncertain": bool(r["uncertain"]),
            "timing_source": r.get("timing_source", ""), "react_lo": react["window"][0], "react_hi": react["window"][1],
            "car": react["car"], "raw": react["raw"], "abs_car": react["abs"], "z": react["z"], "z_abs": react["z_abs_sigma"],
            "sigma": r["sigma"], "ar0": ar[r0], "car01": window_sum(ar, 0, 1),
            "run_up": window_sum(ar, *cfg.run_up), "post_short": window_sum(ar, *cfg.short_post),
            "on0": on[r0], "id0": idr[r0], "on1": on[r1], "id1": idr[r1],
            "vol0": vr[r0], "vol_pre": float(np.nanmean(vr[rel_index(-5):r0])) if np.isfinite(vr[rel_index(-5):r0]).any() else np.nan,
            "vol_max01": float(np.nanmax(vr[r0:r1 + 1])) if np.isfinite(vr[r0:r1 + 1]).any() else np.nan,
            "am_pre": float(np.nanmean(am[rel_index(-5):r0])) if np.isfinite(am[rel_index(-5):r0]).any() else np.nan,
            "am_ev": float(np.nanmean(am[r0:r1 + 1])) if np.isfinite(am[r0:r1 + 1]).any() else np.nan,
            "am_est": r["amihud_est"], "cs_pre": float(np.nanmean(cs[rel_index(-5):r0])) if np.isfinite(cs[rel_index(-5):r0]).any() else np.nan,
            "cs_ev": float(np.nanmean(cs[r0:r1 + 1])) if np.isfinite(cs[r0:r1 + 1]).any() else np.nan, "cs_est": r["cs_est"],
            "beta": r["beta_mkt"], "mom_pre": r["mom_pre"], "dollar_vol": r["dollar_vol_est"], "vol_est": r["ret_vol_est"],
            "eps_estimate": r.get("eps_estimate"), "eps_actual": r.get("eps_actual"), "surprise_pct": r.get("surprise_pct"),
            "timing_suspect": bool(r.get("timing_suspect")), "split_flag": bool(r.get("split_flag")),
            "ex_div_flag": bool(r.get("ex_div_flag")), "n_post": int(r.get("n_post", 0)), "model_used": r["model_used"],
            "sector": ins.get("sector") or "—", "industry": ins.get("industry") or "—",
            "country": venue.country if venue.key != "us" else (ins.get("country") or "États-Unis"),
            "region": venue.region, "currency": ins.get("currency") or venue.currency, "mcap": ins.get("marketCap"),
            "first_trade": (pd.Timestamp(ins["firstTradeDateMilliseconds"], unit="ms") if ins.get("firstTradeDateMilliseconds") else pd.NaT),
            "period_end": pd.Timestamp(period_end) if period_end else pd.NaT, "is_annual": is_annual,
            "lag_days": (pd.Timestamp(r["ann_date"]) - pd.Timestamp(period_end)).days if period_end else np.nan,
        }
        for a, b in cfg.drift_windows:
            rec[f"drift_{a}_{b}"] = window_sum(ar, a, b)
            rec[f"bhar_{a}_{b}"] = bhar(r, a, b)
        recs.append(rec)
    df = pd.DataFrame(recs)
    if df.empty:
        return df
    for col in ("day0", "ann_date"):
        df[col] = pd.to_datetime(df[col])
    df = df.sort_values(["symbol", "day0"]).reset_index(drop=True)
    df = _add_history(df)
    return df.sort_values("day0").reset_index(drop=True)


def _expanding_past(series: pd.Series, func) -> pd.Series:
    """Statistique sur les valeurs STRICTEMENT passées d'une série ordonnée (décalée d'un cran)."""
    return func(series.shift(1).expanding(min_periods=1))


def _add_history(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("symbol", group_keys=False)
    df["event_no"] = g.cumcount() + 1
    df["hist_n"] = df["event_no"] - 1
    df["days_since_prev"] = g["ann_date"].diff().dt.days
    df["prev_car"] = g["car"].shift(1)
    df["hist_mean_abs_z"] = g["z_abs"].transform(lambda s: _expanding_past(s, lambda e: e.mean()))
    df["hist_mean_abs_car"] = g["abs_car"].transform(lambda s: _expanding_past(s, lambda e: e.mean()))
    df["beat"] = np.where(df["surprise_pct"].notna(), (df["surprise_pct"] > 0).astype(float), np.nan)
    df["prev_surprise"] = g["surprise_pct"].shift(1)
    mean_prev = g["surprise_pct"].transform(lambda s: _expanding_past(s, lambda e: e.mean()))
    sd_prev = g["surprise_pct"].transform(lambda s: s.shift(1).expanding(min_periods=4).std())
    n_prev = g["surprise_pct"].transform(lambda s: s.shift(1).expanding(min_periods=1).count())
    df["sue"] = np.where((n_prev >= 4) & (sd_prev > 0), (df["surprise_pct"] - mean_prev) / sd_prev, np.nan)
    df["beat_rate_past"] = g["beat"].transform(lambda s: _expanding_past(s, lambda e: e.mean()))

    def streak(s: pd.Series) -> pd.Series:
        out, run = [], 0
        prev = s.shift(1)
        for v in prev:
            run = run + 1 if v == 1.0 else 0
            out.append(run)
        return pd.Series(out, index=s.index)

    df["beat_streak"] = g["beat"].transform(streak)
    # moyenne passée des réactions du secteur (tous titres, événements dont J0 est strictement antérieur)
    df["sector_hist_abs_z"] = np.nan
    for sector, part in df.groupby("sector"):
        part = part.sort_values("day0")
        days = part["day0"].to_numpy()
        vals = part["z_abs"].to_numpy(dtype=float)
        csum = np.concatenate([[0.0], np.cumsum(np.nan_to_num(vals))])
        ccnt = np.concatenate([[0], np.cumsum(np.isfinite(vals))])
        cut = np.searchsorted(days, days, side="left")
        with np.errstate(invalid="ignore", divide="ignore"):
            df.loc[part.index, "sector_hist_abs_z"] = np.where(ccnt[cut] >= 5, csum[cut] / np.maximum(ccnt[cut], 1), np.nan)
    return df


@dataclass
class Panel:
    cfg: EarningsConfig
    rows: list[dict]
    instruments: dict[str, dict]
    calendar: list[dict]
    signature: str
    frame: pd.DataFrame = field(default_factory=pd.DataFrame)
    scope: Scope = field(default_factory=Scope)

    @property
    def n(self) -> int:
        return len(self.frame)

    def payloads(self, frame: pd.DataFrame | None = None) -> list[dict]:
        sel = self.frame if frame is None else frame
        return [self.rows[int(i)] for i in sel["i"]]

    def with_scope(self, scope: Scope, batch_symbols: list[str] | None = None) -> Panel:
        df = self.frame
        if scope.kind == "symbol":
            df = df[df["symbol"] == scope.value]
        elif scope.kind == "sector":
            df = df[df["sector"] == scope.value]
        elif scope.kind == "country":
            df = df[df["country"] == scope.value]
        elif scope.kind == "batch":
            df = df[df["symbol"].isin(batch_symbols or [])]
        elif scope.kind == "week":
            monday = pd.Timestamp(scope.value)
            df = df[(df["day0"] >= monday) & (df["day0"] < monday + pd.Timedelta(days=7))]
        return Panel(self.cfg, self.rows, self.instruments, self.calendar, self.signature, df.reset_index(drop=True), scope)

    def upcoming(self, symbols: list[str] | None = None, today: date | None = None) -> list[dict]:
        """Annonces pas encore publiées (BPA publié absent), à partir de la veille."""
        cutoff = str((pd.Timestamp(today or local_now().date()) - pd.Timedelta(days=1)).date())
        out = [c for c in self.calendar if c["ann_date"] >= cutoff and c.get("eps_actual") is None]
        return [c for c in out if symbols is None or c["symbol"] in symbols]


_CACHE: dict[tuple, Panel] = {}


def load_panel(conn, cfg: EarningsConfig, symbols: list[str] | None = None) -> Panel:
    h = cfg.measure_hash()
    sig = store.results_signature(conn, h, symbols)
    key = (h, tuple(sorted(symbols)) if symbols else None, json.dumps(cfg.to_dict(), sort_keys=True))
    hit = _CACHE.get(key)
    if hit is not None and hit.signature == sig and hit.cfg == cfg:
        return hit
    rows = store.load_results(conn, h, symbols)
    syms = sorted({r["symbol"] for r in rows})
    instruments = store.all_instruments(conn, syms)
    panel = Panel(cfg, rows, instruments, store.all_calendar(conn, symbols), sig)
    panel.frame = _frame(rows, instruments, cfg)
    if len(_CACHE) > 6:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[key] = panel
    return panel


def clear_cache() -> None:
    _CACHE.clear()
