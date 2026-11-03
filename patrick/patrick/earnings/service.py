"""Couche de service : ce que les pages web et la ligne de commande appellent.

Flux : texte collé -> `create_batch` (analyse + résolution, rien n'est calculé) -> écran de confirmation éditable ->
`confirm_batch` (alias mémorisés) -> `process_batch` (ingestion, instantanés du jour, lecture des dates) -> `week_rows` (vue semaine).
Chaque fonction prend la connexion et le fournisseur en argument : aucun accès réseau caché, tout se teste avec un faux fournisseur.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from patrick.clock import local_now
from patrick.earnings import (
    consensus,
    engine,
    exchanges,
    parse,
    pipeline,
    resolve,
    schedule,
    store,
)
from patrick.earnings.config import EarningsConfig
from patrick.earnings.panel import Panel, load_panel
from patrick.earnings.reliability import partial_pooling, reliability

DATE_TOLERANCE_DAYS = 7


def create_batch(conn, provider, text: str, anchor: date | None = None, progress=None) -> tuple[int, list[str]]:
    result = parse.parse_newsletter(text, anchor)
    if not result.items:
        return 0, result.warnings
    rows = resolve.resolve_all(conn, result.items, provider, progress)
    return store.create_batch(conn, result.anchor, text, rows), result.warnings


def confirm_batch(conn, batch_id: int, edits: list[dict]) -> dict:
    """Valide les lignes de l'écran de confirmation. `edits` : {item_id, include, symbol, adr_symbol, timing}. Mémorise les alias."""
    items = {i["item_id"]: i for i in store.batch_items(conn, batch_id)}
    kept = rejected = 0
    for e in edits:
        item = items.get(int(e["item_id"]))
        if item is None:
            continue
        if not e.get("include", True) or not (e.get("symbol") or "").strip():
            store.update_item(conn, item["item_id"], status="rejected")
            rejected += 1
            continue
        symbol, adr = e["symbol"].strip(), (e.get("adr_symbol") or "").strip() or None
        timing = (e.get("timing") or "auto").upper()
        resolve.confirm_item(conn, item, symbol, adr)
        store.update_item(conn, item["item_id"], symbol=symbol, adr_symbol=adr, timing_override=None if timing == "AUTO" else timing, status="confirmed")
        kept += 1
    store.set_batch_status(conn, batch_id, "confirmed")
    return {"confirmed": kept, "rejected": rejected}


def _match_calendar(conn, item: dict) -> dict | None:
    """Ligne du calendrier correspondant à la date annoncée par la newsletter : la plus proche à moins de 7 jours."""
    plan = pd.Timestamp(item["plan_date"])
    rows = [c for c in store.calendar_for(conn, item["symbol"]) if abs((pd.Timestamp(c["ann_date"]) - plan).days) <= DATE_TOLERANCE_DAYS]
    return min(rows, key=lambda c: abs((pd.Timestamp(c["ann_date"]) - plan).days)) if rows else None


def reconcile_calendar(conn, batch_id: int) -> list[dict]:
    """Rattache chaque élément confirmé à une annonce du calendrier (Yahoo) ou en crée une à la date de la newsletter ; applique le timing choisi."""
    notes = []
    for item in store.batch_items(conn, batch_id):
        if item["status"] != "confirmed" or not item["symbol"]:
            continue
        match = _match_calendar(conn, item)
        flags = [f for f in item["flags"] if f in ("alias confirmé", "alias semé : à confirmer")]
        if match is None:
            guess = item["timing_override"] or exchanges.heuristic_timing(item["symbol"])
            row = {"symbol": item["symbol"], "ann_date": item["plan_date"], "ann_local_time": "", "timing": guess,
                   "timing_source": "heuristic", "uncertain": 1, "reason": "date de la newsletter, absente du calendrier Yahoo",
                   "eps_estimate": None, "eps_actual": None, "surprise_pct": None, "source": "newsletter"}
            flags.append("date absente du calendrier Yahoo")
        else:
            row = dict(match)
            if match["ann_date"] != item["plan_date"]:
                flags.append(f"Yahoo date l'annonce au {match['ann_date']} (newsletter : {item['plan_date']})")
        if item["timing_override"]:
            row = schedule.user_override(row, item["timing_override"])
        store.upsert_calendar(conn, [row], keep_user=False)
        store.update_item(conn, item["item_id"], flags=flags)
        notes.append({"item_id": item["item_id"], "symbol": item["symbol"], "ann_date": row["ann_date"], "timing": row["timing"]})
    return notes


def process_batch(conn_factory, provider, batch_id: int, cfg: EarningsConfig, progress=None, snapshots: bool = True) -> dict:
    """Ingestion de tous les titres confirmés du lot (ligne locale et ADR), rapprochement des dates, instantanés du jour."""
    conn = conn_factory()
    try:
        items = [i for i in store.batch_items(conn, batch_id) if i["status"] == "confirmed" and i["symbol"]]
        symbols = [s for i in items for s in (i["symbol"], i["adr_symbol"]) if s]
    finally:
        conn.close()
    reports = pipeline.ingest_many(conn_factory, provider, symbols, cfg, progress)
    conn = conn_factory()
    try:
        reconcile_calendar(conn, batch_id)
        # le calendrier vient d'être complété (dates de la newsletter, timing choisi) : recalculer les mesures des titres du lot
        shared = pipeline.SharedData(provider, cfg)
        for sym in dict.fromkeys(i["symbol"] for i in items):
            pipeline.ingest_symbol(conn, provider, sym, cfg, shared, refresh_calendar=False)
        taken = consensus.take_snapshots(conn, provider, list(dict.fromkeys(i["symbol"] for i in items))) if snapshots else {}
        store.set_batch_status(conn, batch_id, "ready")
    finally:
        conn.close()
    return {"reports": reports, "snapshots": taken, "symbols": len(set(symbols))}


# ---------------------------------------------------------------------------------------------------------------- vue semaine

def _hist_stats(frame: pd.DataFrame, cfg: EarningsConfig) -> dict:
    n = len(frame)
    if n == 0:
        return {"n": 0}
    abs_car = frame["abs_car"].dropna()
    q = abs_car.quantile([0.1, 0.5, 0.9]) if len(abs_car) else pd.Series([np.nan] * 3)
    rel = reliability(frame["car"].to_numpy(), n=n, day0=frame["day0"], min_events=cfg.min_events)

    def finite(x):
        return float(x) if np.isfinite(x) else None

    return {"n": n, "mean_abs": float(abs_car.mean()) if len(abs_car) else np.nan, "q10": finite(q.iloc[0]), "median_abs": finite(q.iloc[1]),
            "q90": finite(q.iloc[2]), "p_up": float((frame["car"] > 0).mean()), "last": [float(x) for x in frame.sort_values("day0")["car"].tail(4)],
            "mean_z": float(frame["z_abs"].mean()), "sigma": float(frame.sort_values("day0")["sigma"].iloc[-1]), "reliability": rel,
            "beat_rate": float((frame["surprise_pct"].dropna() > 0).mean()) if frame["surprise_pct"].notna().any() else np.nan}


def week_rows(conn, batch_id: int, cfg: EarningsConfig, panel: Panel | None = None) -> list[dict]:
    """Une ligne par élément confirmé : prochaine annonce, amplitude attendue (rétrécie vers le secteur), drapeaux. Classé par amplitude."""
    panel = panel or load_panel(conn, cfg)
    frame = panel.frame
    snaps = {(s["symbol"], s["kind"]): s for s in store.snapshots(conn)}          # le dernier de chaque (titre, nature)
    by_sym = {s: g for s, g in frame.groupby("symbol")}
    sector_of = {s: g["sector"].iloc[0] for s, g in by_sym.items()}
    pooled = partial_pooling({s: g["abs_car"].to_numpy() for s, g in by_sym.items()}, sector_of)
    out = []
    for item in store.batch_items(conn, batch_id):
        if item["status"] != "confirmed" or not item["symbol"]:
            continue
        sym = item["symbol"]
        cal = _match_calendar(conn, item)
        hist = _hist_stats(by_sym.get(sym, frame.iloc[0:0]), cfg)
        shrunk = pooled.get(sym, {}).get("shrunk")
        raw_mean = hist.get("mean_abs")
        if raw_mean is not None and not np.isfinite(raw_mean):
            raw_mean = None
        flags = []
        if cal is None or cal["uncertain"]:
            flags.append("timing_uncertain")
        if hist["n"] == 0:
            flags.append("no_history")
        elif hist["n"] < cfg.min_events:
            flags.append("n_insufficient")
        if (sym, "consensus") not in snaps:
            flags.append("analyst_missing")
        if any(f in ("nom différent", "ambigu", "introuvable") for f in item["flags"]):
            flags.append("name_check")
        ins = panel.instruments.get(sym) or store.get_instrument(conn, sym) or {}
        straddle = (snaps.get((sym, "options")) or {}).get("payload", {})
        cons = consensus.summarize(snaps[(sym, "consensus")]["payload"]) if (sym, "consensus") in snaps else {}
        out.append({
            "item_id": item["item_id"], "name": item["name"], "day_index": item["day_index"], "plan_date": item["plan_date"], "symbol": sym,
            "adr_symbol": item["adr_symbol"], "ann_date": cal["ann_date"] if cal else item["plan_date"], "timing": cal["timing"] if cal else "UNKNOWN",
            "timing_source": cal["timing_source"] if cal else "", "timing_reason": (cal or {}).get("reason") or "", "eps_estimate": (cal or {}).get("eps_estimate"),
            "sector": ins.get("sector") or "—", "country": exchanges.venue_for(sym).country, "hist": hist, "expected_abs": shrunk if shrunk is not None else raw_mean,
            "expected_raw": raw_mean, "shrink_weight": pooled.get(sym, {}).get("weight"), "implied": straddle.get("straddle_pct"),
            "consensus": cons, "flags": flags,
            "notes": [n for n in item["flags"] if n.startswith(("Yahoo date", "date absente"))],
        })
    return sorted(out, key=lambda r: -(r["expected_abs"] if r["expected_abs"] is not None and np.isfinite(r["expected_abs"]) else -1))


# ------------------------------------------------------------------------------------------------------------------ fiche titre

def title_sheet(conn, symbol: str, cfg: EarningsConfig, panel: Panel | None = None) -> dict:
    panel = panel or load_panel(conn, cfg)
    frame = panel.frame[panel.frame["symbol"] == symbol].sort_values("day0", ascending=False)
    rows_by_ann = {r["ann_date"]: r for r in panel.rows if r["symbol"] == symbol}
    history = []
    for r in frame.itertuples():
        history.append({"ann_date": str(r.ann_date.date()), "day0": str(r.day0.date()), "timing": r.timing, "uncertain": r.uncertain, "car": r.car,
                        "raw": r.raw, "z": r.z, "on0": r.on0, "id0": r.id0, "surprise_pct": r.surprise_pct, "run_up": r.run_up, "vol0": r.vol0,
                        "window": (r.react_lo, r.react_hi), "suspect": r.timing_suspect, "event_key": str(r.ann_date.date())})
    paths = []
    for r in frame.sort_values("day0").itertuples():
        pl = rows_by_ann.get(str(r.ann_date.date()))
        if pl is not None:
            ar = engine.arr(pl, "ar")
            paths.append(np.cumsum(np.nan_to_num(ar)).tolist())
    mean_path = np.nanmean(np.array(paths), axis=0).tolist() if paths else []
    snaps = store.snapshots(conn, symbol)
    ins = panel.instruments.get(symbol) or store.get_instrument(conn, symbol) or {}
    upcoming = [c for c in store.calendar_for(conn, symbol) if c["eps_actual"] is None and c["ann_date"] >= str(local_now().date() - pd.Timedelta(days=1))]
    cons = [s for s in snaps if s["kind"] == "consensus"]
    return {"symbol": symbol, "instrument": ins, "history": history, "stats": _hist_stats(frame, cfg), "upcoming": upcoming,
            "paths": {"x": list(range(engine.REL[0], engine.REL[-1] + 1)), "mean": mean_path, "n": len(paths)},
            "consensus": consensus.summarize(cons[-1]["payload"]) if cons else None, "consensus_date": cons[-1]["snap_date"] if cons else None,
            "n_snapshots": len(snaps), "adr": store.adr_map(conn).get(symbol), "venue": exchanges.venue_for(symbol).key}


def event_detail(conn, symbol: str, ann_date: str, cfg: EarningsConfig, panel: Panel | None = None) -> dict | None:
    panel = panel or load_panel(conn, cfg)
    payload = next((r for r in panel.rows if r["symbol"] == symbol and r["ann_date"] == ann_date), None)
    if payload is None:
        return None
    rel = list(range(engine.REL[0], engine.REL[-1] + 1))
    ar = engine.arr(payload, "ar")
    react = engine.reaction_stats(payload, cfg)
    return {"symbol": symbol, "payload": payload, "rel": rel, "ar": ar.tolist(), "ret": engine.arr(payload, "ret").tolist(),
            "car_path": np.cumsum(np.nan_to_num(ar)).tolist(), "vol_ratio": engine.arr(payload, "vol_ratio").tolist(), "on": engine.arr(payload, "on").tolist(),
            "id": engine.arr(payload, "id").tolist(), "reaction": react, "bhar": {f"{a}_{b}": engine.bhar(payload, a, b) for a, b in cfg.drift_windows},
            "day0": payload["day0"]}
