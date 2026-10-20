"""Exports de l'analyse d'un run : prédictions et courbes d'équité en CSV (colonnes numériques et dates seulement, jamais de texte libre),
données de toutes les sections pour un rapport HTML autonome."""
from __future__ import annotations

import csv
import io
import sqlite3

import numpy as np

from patrick.analysis import frames, sec_perf
from patrick.analysis import stats_core as sc
from patrick.analysis.context import Ctx
from patrick.analysis.registry import SECTIONS, get_frame


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (float, np.floating)):
        return "" if not np.isfinite(v) else repr(round(float(v), 8))
    return str(v)


def predictions_csv(conn: sqlite3.Connection, run_id: str) -> str | None:
    """Toutes les prédictions stockées de l'essai retenu, avec la classe réelle, la direction, la confiance, P(hausse) et le rendement
    futur réalisé quand le niveau de la cible est connu. `correct` : la direction prédite est la direction réelle."""
    fr = frames.load_frame(conn, run_id)
    if fr is None:
        return None
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["date", "split", "fold", "path", "true_class", "pred_class", "true_up", "pred_up", "confidence", "p_up", "p_up_calibrated",
                "forward_return", "correct"])
    for r in fr.df.sort_values(["ts", "path"], kind="mergesort").itertuples(index=False):
        resolved = r.ut == r.ut
        w.writerow([r.ts.strftime("%Y-%m-%d"), r.split_name, r.fold, r.path, _fmt(r.yt), _fmt(r.yp), _fmt(r.ut), int(bool(r.up)), _fmt(r.conf),
                    _fmt(r.p_up), _fmt(r.p_cal), _fmt(r.ret), (int((r.ut >= 0.5) == bool(r.up)) if resolved else "")])
    return out.getvalue()


def equity_csv(conn: sqlite3.Connection, run_id: str, cost_bps: float = 5.0) -> str | None:
    """Rendements quotidiens bruts, rotation et valeur nette des trois stratégies simulées (long/court, long/à plat, achat-garde)."""
    fr = frames.load_frame(conn, run_id)
    if fr is None or fr.levels is None:
        return None
    d = fr.df[fr.df["split_name"].isin(["test", "holdout", "live"])]
    d = Ctx(conn, fr, {}).one_path(d).sort_values("ts", kind="mergesort")
    strat = sec_perf.build_strategies(fr, d)
    if strat is None:
        return None
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    head = ["date"]
    for s in sec_perf.STRATEGIES:
        head += [f"{s}_gross", f"{s}_turnover", f"{s}_net", f"{s}_equity_net"]
    w.writerow(head)
    nets = {s: sec_perf._net(strat[s], cost_bps) for s in sec_perf.STRATEGIES}
    eqs = {s: sc.equity_from_returns(nets[s].to_numpy()) for s in sec_perf.STRATEGIES}
    for i, t in enumerate(strat["dates"]):
        row = [t.strftime("%Y-%m-%d")]
        for s in sec_perf.STRATEGIES:
            row += [_fmt(strat[s]["gross"].iloc[i]), _fmt(strat[s]["turn"].iloc[i]), _fmt(nets[s].iloc[i]), _fmt(eqs[s][i])]
        w.writerow(row)
    return out.getvalue()


def all_sections(conn: sqlite3.Connection, run_id: str, db_key: str = "") -> dict | None:
    """Données de chaque section (paramètres par défaut) : alimente le rapport HTML autonome. Une section en échec est omise (le rapport
    affiche « indisponible »), les autres restent."""
    fr = get_frame(conn, run_id, None, db_key)
    if fr is None:
        return None
    out = {}
    for name, fn in SECTIONS.items():
        if name == "paths" and not fr.is_cpcv:
            continue
        try:
            out[name] = sc.jsonable(fn(Ctx(conn, fr, {})))
        except Exception:  # noqa: BLE001 -- une section ne doit pas empêcher l'export des autres
            continue
    return out
