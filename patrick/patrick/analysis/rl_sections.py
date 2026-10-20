"""Analyse d'un run de reinforcement learning (table `job`, `kind: rl`) : plis, courbes d'équité hors échantillon contre les références,
drawdowns, positions, rendements, Sharpe glissant, statistiques de comparaison, graines, variables.

Source : le résultat du job (`result_json`) et, pour le détail quotidien, `rl_oos.csv` (une ligne par date hors échantillon : position,
rendement net, coût, rendements de acheter-garder et de momentum). Sans le CSV (supprimé, autre poste), les courbes amincies du résultat
servent de repli. Tout est en lecture seule."""
from __future__ import annotations

import contextlib
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from patrick.analysis import stats_core as sc
from patrick.analysis.context import iso

APP_ROOT = Path(__file__).resolve().parents[2]
SECTIONS = ("overview", "folds", "equity", "returns", "stats", "features")
MAX_POINTS = 1500


class RLRun:
    def __init__(self, row: dict, result: dict | None, config: dict):
        self.row, self.result, self.config = row, result, config
        self._daily: pd.DataFrame | None = None
        self.notes: list[str] = []

    @property
    def job_id(self) -> str:
        return self.row["job_id"]

    @property
    def ready(self) -> bool:
        return bool(self.result)

    def _find_csv(self) -> Path | None:
        art = ((self.result or {}).get("artifacts") or {}).get("oos_csv")
        out_dir = ((self.config.get("output") or {}).get("dir")) or ""
        cands = []
        if art:
            p = Path(art)
            cands += [p, APP_ROOT / p, Path(out_dir) / p.name, APP_ROOT / out_dir / p.name]
        for c in cands:
            if c.is_file():
                return c
        return None

    def daily(self) -> pd.DataFrame | None:
        """Une ligne par date hors échantillon : position, net, cost, buy_hold, momentum ; repli sur les courbes du résultat."""
        if self._daily is not None:
            return self._daily
        path = self._find_csv()
        if path is not None:
            with contextlib.suppress(OSError, ValueError, pd.errors.ParserError):
                df = pd.read_csv(path, parse_dates=["date"]).rename(columns={
                    "net_return": "net", "buy_hold_return": "buy_hold", "momentum_return": "momentum"})
                if len(df):
                    self._daily = df.set_index("date").sort_index()
                    return self._daily
        cur = (self.result or {}).get("curves") or {}
        if cur.get("dates"):
            eq = pd.DataFrame({k: cur[k] for k in ("strategy", "buy_hold", "momentum", "position") if k in cur},
                              index=pd.to_datetime(cur["dates"]))
            out = pd.DataFrame(index=eq.index)
            for name, col in (("net", "strategy"), ("buy_hold", "buy_hold"), ("momentum", "momentum")):
                if col in eq:
                    out[name] = eq[col].pct_change().fillna(eq[col].iloc[0] - 1.0)
            out["position"] = eq.get("position", 0.0)
            out["cost"] = 0.0
            self.notes.append("thinned_curves")
            self._daily = out
            return out
        return None


def load_run(conn: sqlite3.Connection, job_id: str) -> RLRun | None:
    row = conn.execute(
        "SELECT job_id, status, phase, created_at, started_at, finished_at, error, result_json, config_json FROM job "
        "WHERE job_id = ? AND config_json LIKE '%\"kind\":\"rl\"%'", (job_id,)).fetchone()
    if row is None:
        return None
    keys = ("job_id", "status", "phase", "created_at", "started_at", "finished_at", "error", "result_json", "config_json")
    r = dict(zip(keys, row, strict=True))
    result = None
    with contextlib.suppress(TypeError, ValueError):
        result = json.loads(r["result_json"]) if r["result_json"] else None
    config: dict = {}
    with contextlib.suppress(TypeError, ValueError):
        config = json.loads(r["config_json"]) or {}
    run = RLRun(r, result, config)
    return run


def _summ(net, pos, cost, dates) -> dict:
    from patrick.rl import metrics as rlm
    return rlm.summarize(np.asarray(net, dtype=float), np.asarray(pos, dtype=float), np.asarray(cost, dtype=float), pd.DatetimeIndex(dates))


# ----------------------------------------------------------------------------------------------------------- sections
def overview(run: RLRun) -> dict:
    res, cfg = run.result or {}, run.config
    rl = cfg.get("rl") or {}
    obj = cfg.get("objective") or {}
    return {"available": run.ready, "reason": None if run.ready else "not_ready",
            "run": {"job_id": run.job_id, "name": res.get("name") or cfg.get("name"), "target": res.get("target") or obj.get("target_symbol"),
                    "algo": res.get("algo") or rl.get("algo"), "status": run.row["status"], "phase": run.row["phase"],
                    "started_at": run.row["started_at"], "finished_at": run.row["finished_at"], "error": run.row["error"]},
            "period": [res.get("start"), res.get("end")], "n_rows": res.get("n_rows"), "n_pool": res.get("n_features_pool"),
            "n_folds": res.get("n_folds"), "elapsed_s": res.get("elapsed_s"), "warnings": res.get("warnings") or [],
            "strategy": res.get("strategy"), "baselines": res.get("baselines"), "seeds": res.get("seeds") or [],
            "stats": res.get("stats"),
            "settings": {k: rl.get(k) for k in ("algo", "action_space", "n_levels", "allow_short", "max_leverage", "cost_bps", "slippage_bps",
                                                "reward", "risk_aversion", "obs_lookback", "episode_length", "max_features",
                                                "feature_selection", "total_timesteps", "learning_rate", "gamma")}}


def folds(run: RLRun) -> dict:
    res = run.result or {}
    items = []
    for f in res.get("folds") or []:
        s, b = f.get("strategy") or {}, f.get("buy_hold") or {}
        items.append({"fold": f.get("fold"), "train_start": f.get("train_start"), "train_end": f.get("train_end"),
                      "test_start": f.get("test_start"), "test_end": f.get("test_end"), "n_train": f.get("n_train"),
                      "n_test": f.get("n_test"), "strategy": s, "buy_hold": b, "momentum": f.get("momentum"),
                      "n_features": len(f.get("features") or []), "features": f.get("features") or []})
    if not items:
        return {"available": False, "reason": "no_folds"}
    wins = sum(1 for i in items if (i["strategy"].get("sharpe") or -9) > (i["buy_hold"].get("sharpe") or -9))
    return {"available": True, "folds": items, "wins_vs_buy_hold": wins, "n": len(items),
            "range": [min(i["train_start"] or i["test_start"] for i in items), max(i["test_end"] for i in items)]}


def equity(run: RLRun) -> dict:
    """Courbes d'équité (départ 1) de l'agent, d'acheter-garder, de momentum et de « à plat », drawdowns, Sharpe glissant (252 jours),
    positions, rendements mensuels. Les coûts de transaction sont déjà déduits du rendement net de l'agent."""
    d = run.daily()
    if d is None or d.empty:
        return {"available": False, "reason": "no_daily"}
    from patrick.rl import metrics as rlm
    dates = d.index
    net = d["net"].to_numpy(dtype=float)
    pos = d["position"].to_numpy(dtype=float) if "position" in d else np.zeros(len(d))
    cost = d["cost"].to_numpy(dtype=float) if "cost" in d else np.zeros(len(d))
    series = {"agent": net}
    for k in ("buy_hold", "momentum"):
        if k in d:
            series[k] = d[k].to_numpy(dtype=float)
    series["flat"] = np.zeros(len(d))
    curves = {k: rlm.equity_curve(v) for k, v in series.items()}
    dd = {k: sc.drawdown_series(v) for k, v in curves.items()}
    roll = {}
    for k in ("agent", "buy_hold"):
        if k in series:
            r = pd.Series(series[k])
            sd = r.rolling(252, min_periods=126).std()
            roll[k] = (r.rolling(252, min_periods=126).mean() / sd.where(sd > 1e-12) * np.sqrt(252)).to_numpy()
    idx = sc.thin_indices(len(d), MAX_POINTS)
    folds_ = (run.result or {}).get("folds") or []
    stats = {"agent": _summ(net, pos, cost, dates)}
    for k in ("buy_hold", "momentum"):
        if k in series:
            stats[k] = _summ(series[k], np.ones(len(d)) if k == "buy_hold" else np.sign(pos) * 0.0, np.zeros(len(d)), dates)
    r_a = pd.Series(net, index=dates)
    monthly = (1.0 + r_a).groupby([dates.year, dates.month]).prod() - 1.0
    changes = np.abs(np.diff(np.r_[0.0, pos]))
    holding = []
    start = 0
    for i in range(1, len(pos) + 1):
        if i == len(pos) or pos[i] != pos[start]:
            if pos[start] != 0:
                holding.append(i - start)
            start = i
    return {"available": True, "dates": [iso(t) for t in dates[idx]], "idx": idx.tolist(), "n": len(d), "notes": run.notes,
            "curves": {k: v[idx] for k, v in curves.items()}, "drawdown": {k: v[idx] for k, v in dd.items()},
            "rolling_sharpe": {k: v[idx] for k, v in roll.items()}, "position": pos[idx], "stats": stats,
            "months": [{"y": int(y), "m": int(m), "r": float(v)} for (y, m), v in monthly.items()],
            "folds": [{"fold": f.get("fold"), "start": f.get("test_start"), "end": f.get("test_end")} for f in folds_],
            "exposure": {"mean_abs": float(np.abs(pos).mean()), "share_long": float((pos > 0.05).mean()), "share_short": float((pos < -0.05).mean()),
                         "share_flat": float((np.abs(pos) <= 0.05).mean()), "turnover_per_year": float(changes.sum() / max(len(pos) / 252, 1e-9)),
                         "n_changes": int((changes > 1e-9).sum()), "mean_holding": float(np.mean(holding)) if holding else None,
                         "cost_total": float(cost.sum())}}


def returns(run: RLRun) -> dict:
    """Distribution des rendements quotidiens nets (histogramme, asymétrie, kurtosis, pire jour) et position moyenne selon le signe
    du rendement de la veille de l'actif (l'agent suit-il la tendance ou la contre-t-il ?)."""
    d = run.daily()
    if d is None or d.empty:
        return {"available": False, "reason": "no_daily"}
    net = d["net"].to_numpy(dtype=float)
    lim = float(np.quantile(np.abs(net), 0.995)) or 0.01
    h = sc.histogram(np.clip(net, -lim, lim), 41, -lim, lim)
    out = {"available": True, "hist": h, "mean": float(net.mean()), "std": float(net.std(ddof=1)) if len(net) > 1 else None,
           "skew": float(pd.Series(net).skew()), "kurtosis": float(pd.Series(net).kurt()), "worst": float(net.min()),
           "best": float(net.max()), "p_win": float((net > 0).mean()), "n": len(net), "clip": lim}
    if "buy_hold" in d and "position" in d:
        bh = d["buy_hold"].to_numpy(dtype=float)
        pos = d["position"].to_numpy(dtype=float)
        prev = np.r_[np.nan, bh[:-1]]
        out["position_after"] = {"up_day": float(np.nanmean(pos[prev > 0])) if (prev > 0).any() else None,
                                 "down_day": float(np.nanmean(pos[prev < 0])) if (prev < 0).any() else None}
        out["corr_position_asset"] = sc.clean(np.corrcoef(pos, bh)[0, 1]) if np.std(pos) > 0 and np.std(bh) > 0 else None
    return out


def stats(run: RLRun) -> dict:
    res = run.result or {}
    return {"available": run.ready, "stats": res.get("stats"), "seeds": res.get("seeds") or [], "baselines": res.get("baselines"),
            "strategy": res.get("strategy"), "n_trials": (res.get("stats") or {}).get("n_trials")}


def features(run: RLRun) -> dict:
    res = run.result or {}
    usage = res.get("feature_usage") or []
    n_folds = res.get("n_folds") or max((u[1] for u in usage), default=0)
    from patrick.analysis.sec_meta import feature_family
    items = [{"feature": u[0], "folds": u[1], "family": feature_family(u[0])} for u in usage]
    fam: dict[str, int] = {}
    for it in items:
        fam[it["family"]] = fam.get(it["family"], 0) + it["folds"]
    tot = sum(fam.values()) or 1
    return {"available": bool(items), "usage": items[:60], "n": len(items), "n_folds": n_folds,
            "families": sorted(({"family": k, "share": v / tot} for k, v in fam.items()), key=lambda r: -r["share"]),
            "pool": res.get("n_features_pool")}


_BUILDERS = {"overview": overview, "folds": folds, "equity": equity, "returns": returns, "stats": stats, "features": features}


def build(conn: sqlite3.Connection, job_id: str, section: str) -> dict | None:
    if section not in _BUILDERS:
        raise KeyError(section)
    run = load_run(conn, job_id)
    if run is None:
        return None
    return sc.jsonable(_BUILDERS[section](run))


def is_rl_job(conn: sqlite3.Connection, job_id: str) -> bool:
    return conn.execute("SELECT 1 FROM job WHERE job_id = ? AND config_json LIKE '%\"kind\":\"rl\"%'", (job_id,)).fetchone() is not None

