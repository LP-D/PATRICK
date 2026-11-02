"""Panel de runs « placebo » : mesure si le signal d'une classe d'actifs repose sur l'information du jour même.

Contexte (analyse du 2026-10-31) : les indices asiatiques affichaient une AUC de direction de 0,59 à 1 jour et de ~0,52 dès 3 jours, sans
colonne coupable (même profil que le change avant la règle d'alignement 2). Tout run walk-forward neuf calcule déjà un placebo (`engine._placebo_lag`,
ADR 0008) : les mêmes réglages sur le holdout avec TOUTES les variables retardées d'un jour de plus ; un signal qui s'effondre repose sur le jour
même. Ici : un petit panel de runs légers (Asie, avec l'Europe et les États-Unis en témoins) pour que ce placebo existe, et son rapport.

Ne remplace aucun run, n'écrit pas dans `champion` : c'est une mesure. Les runs passent par la file ordinaire."""
from __future__ import annotations

import sqlite3

from patrick.config.schema import RunConfig
from patrick.data.session_calendar import classify_asset_class
from patrick.validation.placebo import placebo_verdict

PANELS: dict[str, tuple[str, ...]] = {
    "asia": ("^N225", "^HSI", "^KS11", "^TWII", "^AXJO", "^NSEI", "^BSESN", "^STI"),
    "controls": ("^GSPC", "^FCHI", "^GDAXI"),
}
PANELS["all"] = PANELS["asia"] + PANELS["controls"]
# Les autres classes d'actifs (2026-11-02). Sur la base réelle, 113 runs seulement ont un placebo, presque tous à 10 jours et plus : aucun
# pour les indices de volatilité, un seul pour le change (depuis la règle d'alignement 2), et le signal « jour même » se voit à 1-3 jours.
PANELS.update({
    "fx": ("EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X", "USDCHF=X", "USDCAD=X"),
    "futures": ("GC=F", "SI=F", "HG=F", "CL=F", "BZ=F", "NG=F"),
    "us": ("^DJI", "^IXIC", "^RUT"),
    "europe": ("^FTSE", "^STOXX50E", "^AEX", "^SSMI"),
    "americas": ("^BVSP", "^MXX", "^GSPTSE"),
    "crypto": ("BTC-USD", "ETH-USD"),
    "volatility": ("^VIX", "^VXN"),
})
PANELS["every_class"] = tuple(dict.fromkeys(sum((PANELS[g] for g in (
    "asia", "controls", "fx", "futures", "us", "europe", "americas", "crypto", "volatility")), ())))
PANEL_HORIZONS = (1, 3)                    # 1 jour : là où l'écart est visible ; 3 jours : là où il a disparu
SHORT_HORIZON = 3                          # « court » : l'effet du jour même s'y voit encore
NAME_PREFIX = "placebo"


def panel_targets(group: str) -> list[str]:
    if group not in PANELS:
        raise ValueError(f"panel inconnu : {group!r} ({', '.join(PANELS)})")
    return list(PANELS[group])


def build_config(target: str, name: str, horizons: tuple[int, ...] = PANEL_HORIZONS) -> RunConfig:
    """Run léger (un algorithme, deux tailles de sélection, ni réglage ni stacking) : le but est le placebo, pas le meilleur modèle."""
    from patrick.webapp import forms

    yf_tickers, fred_series = forms.universe_excluding(target)
    return RunConfig.model_validate({
        "name": name,
        "objective": {"target_symbol": target, "horizons": list(horizons)},
        "universe": {"yf_tickers": yf_tickers, "fred_series": fred_series},
        "selection": {"n_features_grid": [5, 8], "screening_mode": "total_window", "screening_finalists_per_group": 2},
        "models": {"algos": ["LightGBM"]},
        "tuning": {"enabled": False},
        "output": {"dir": f"runs/{NAME_PREFIX}/{name}"},
    })


def enqueue(group: str, horizons: tuple[int, ...] = PANEL_HORIZONS, dry_run: bool = False, start_worker: bool = False) -> list[str]:
    """Met en file un run par cible du panel (sauf celles déjà en file ou en cours) ; renvoie les noms. `dry_run` : ne touche à rien.
    Aucun worker n'est lancé par défaut (`start_worker=False`) : un panel de ~20 runs dure des heures, et un worker lancé depuis un
    terminal éphémère ou l'assistant est tué avec lui (runs « orphelins »). Les jobs attendent le prochain worker (`patrick worker`, ou
    la prochaine soumission depuis la page web)."""
    from patrick.tracking import db as trackdb
    from patrick.tracking import jobs as jobs_db
    from patrick.webapp import launch_batches, run_manager

    conn = trackdb.connect()
    try:
        busy = launch_batches.pending_targets(conn, "ml")
    finally:
        conn.close()
    names = []
    conn = trackdb.connect()
    try:
        for target in panel_targets(group):
            if target in busy:
                continue
            name = f"{NAME_PREFIX}_{run_manager.next_run_name(target)}"
            names.append(name)
            if not dry_run:
                jobs_db.enqueue_job(conn, build_config(target, name, horizons).model_dump_json())
    finally:
        conn.close()
    if names and start_worker and not dry_run:
        run_manager.ensure_worker_running()
    return names


def report(conn: sqlite3.Connection, group: str | None = None) -> list[dict]:
    """Une ligne par run ayant un placebo : cible, classe, horizon, AUC réelle / retardée, verdict (`validation/placebo.py`)."""
    wanted = set(panel_targets(group)) if group else None
    runs: dict[str, dict] = {}
    for run_id, target, horizon, variant, metric, value in conn.execute(
            "SELECT p.run_id, r.target, r.horizon, p.variant, p.metric, p.value FROM run_placebo p JOIN run r ON r.run_id = p.run_id"):
        if wanted is not None and target not in wanted:
            continue
        entry = runs.setdefault(run_id, {"run_id": run_id, "target": target, "horizon": horizon, "real": {}, "lag1": {}})
        entry[variant][metric] = value
    rows = []
    for entry in runs.values():
        real, lag = entry["real"].get("AUC_ovr_4cls"), entry["lag1"].get("AUC_ovr_4cls")
        rows.append({**entry, "class": classify_asset_class(entry["target"]), "auc_real": real, "auc_lag1": lag,
                     "drop": None if real is None or lag is None else real - lag,
                     "verdict": placebo_verdict(entry["real"], entry["lag1"])})
    return sorted(rows, key=lambda r: (r["class"], r["target"], r["horizon"]))


def coverage(conn: sqlite3.Connection) -> list[dict]:
    """Par classe d'actifs : runs terminés, runs avec un placebo, et parmi eux ceux d'un horizon court (<= `SHORT_HORIZON`), là où un signal « jour
    même » est visible. Une classe sans placebo court n'a pas été auditée : ses champions ne sont pas à croire sur parole."""
    done: dict[str, int] = {}
    for target, in conn.execute("SELECT target FROM run WHERE status = 'done'"):
        cls = classify_asset_class(target)
        done[cls] = done.get(cls, 0) + 1
    covered: dict[str, int] = {}
    short: dict[str, int] = {}
    for row in report(conn):
        covered[row["class"]] = covered.get(row["class"], 0) + 1
        if row["horizon"] <= SHORT_HORIZON:
            short[row["class"]] = short.get(row["class"], 0) + 1
    return [{"class": cls, "runs": n, "with_placebo": covered.get(cls, 0), "with_short_placebo": short.get(cls, 0)}
            for cls, n in sorted(done.items(), key=lambda kv: -kv[1])]


def summarize(rows: list[dict]) -> list[dict]:
    """Par classe et horizon : runs, AUC réelle et retardée moyennes, part des runs au verdict « jour même »."""
    groups: dict[tuple[str, int], list[dict]] = {}
    for row in rows:
        if row["auc_real"] is not None and row["auc_lag1"] is not None:
            groups.setdefault((row["class"], row["horizon"]), []).append(row)
    return [{"class": cls, "horizon": h, "n": len(items), "auc_real": sum(r["auc_real"] for r in items) / len(items),
             "auc_lag1": sum(r["auc_lag1"] for r in items) / len(items),
             "share_same_day": sum(1 for r in items if r["verdict"] == "same_day") / len(items)}
            for (cls, h), items in sorted(groups.items())]
