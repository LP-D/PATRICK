"""Instantané du consensus analystes (Yahoo) -> quelques grandeurs lisibles, et prise d'instantanés quotidiens.

Yahoo ne donne le consensus que tel qu'il est AUJOURD'HUI : aucun historique daté (I/B/E/S, FactSet ou Estimize le vendent). Un signal
analyste testé sur des annonces passées avec la valeur d'aujourd'hui serait contaminé par l'information future. Deux conséquences :
- mode PROSPECTIF : `take_snapshots` stocke chaque jour, pour les titres suivis, le consensus, les révisions, les recommandations, les
  cibles de cours, les vendeurs à découvert et le straddle de la prochaine annonce (`earn_snapshot`) ; après quelques trimestres,
  ces instantanés deviennent un vrai historique daté, exploitable en backtest ;
- jusqu'à accumulation, le signal analyste est un AFFICHAGE, pas une variable évaluée (`composite.ANALYST_MIN_EVENTS`).
La seule série analyste historique gratuite est `upgrades_downgrades` (changements de recommandation datés) : voir `studies/news_analysts.py`.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from patrick.clock import local_now
from patrick.earnings import store


def _row(records, period: str) -> dict:
    for r in records or []:
        if r.get("period") == period:
            return r
    return {}


def _ratio(a, b):
    return None if not a or not b else a / b - 1


def summarize(payload: dict) -> dict:
    est = _row(payload.get("earnings_estimate"), "0q")
    trend = _row(payload.get("eps_trend"), "0q")
    rev = _row(payload.get("eps_revisions"), "0q")
    reco = _row(payload.get("recommendations"), "0m")
    pt = payload.get("analyst_price_targets") or {}
    avg, low, high = est.get("avg"), est.get("low"), est.get("high")
    up30, down30 = rev.get("upLast30days") or 0, rev.get("downLast30days") or 0
    total = sum((reco.get(k) or 0) for k in ("strongBuy", "buy", "hold", "sell", "strongSell"))
    cur = trend.get("current")
    return {
        "eps_avg": avg, "eps_low": low, "eps_high": high, "n_analysts": est.get("numberOfAnalysts"),
        "dispersion": (high - low) / abs(avg) if (avg and high is not None and low is not None) else None,
        "rev_7d": _ratio(cur, trend.get("7daysAgo")), "rev_30d": _ratio(cur, trend.get("30daysAgo")),
        "rev_60d": _ratio(cur, trend.get("60daysAgo")), "rev_90d": _ratio(cur, trend.get("90daysAgo")),
        "up30": up30, "down30": down30, "net_rev_30d": (up30 - down30) / max(up30 + down30, 1),
        "reco_score": ((reco.get("strongBuy") or 0) + (reco.get("buy") or 0) - (reco.get("sell") or 0) - (reco.get("strongSell") or 0)) / total
        if total else None,
        "reco_n": total, "pt_mean": pt.get("mean"), "pt_current": pt.get("current"),
        "pt_upside": _ratio(pt.get("mean"), pt.get("current")),
    }


def tracked_symbols(conn, days: int = 30) -> list[str]:
    """Titres suivis : ceux qui ont une annonce non encore publiée dans les `days` prochains jours (ou depuis hier)."""
    store.ensure_schema(conn)
    rows = conn.execute("SELECT DISTINCT symbol FROM earn_calendar WHERE ann_date >= date('now', '-1 day') AND ann_date <= date('now', ?) "
                        "AND eps_actual IS NULL ORDER BY symbol", (f"+{int(days)} day",)).fetchall()
    return [r[0] for r in rows]


def next_event(conn, symbol: str, today: date | None = None) -> dict | None:
    """Prochaine annonce connue (BPA publié absent) d'un titre."""
    today = today or local_now().date()
    for row in store.calendar_for(conn, symbol, since=str(today)):
        if row.get("eps_actual") is None:
            return row
    return None


def take_snapshots(conn, provider, symbols: list[str], today: date | None = None, progress=None) -> dict:
    """Un instantané par titre et par jour : consensus, vendeurs à découvert, straddle de la prochaine annonce. Déjà pris = ignoré."""
    today = today or local_now().date()
    taken = {"consensus": 0, "short": 0, "options": 0, "skipped": 0}
    for i, sym in enumerate(dict.fromkeys(symbols)):
        nxt = next_event(conn, sym, today)
        payload = provider.consensus(sym)
        if any(payload.values()):
            payload["next_ann_date"] = nxt["ann_date"] if nxt else None
            taken["consensus"] += int(store.put_snapshot(conn, sym, "consensus", payload, today))
        else:
            taken["skipped"] += 1
        info = provider.info(sym)
        if info.get("shortPercentOfFloat") is not None or info.get("sharesShort") is not None:
            taken["short"] += int(store.put_snapshot(conn, sym, "short", {
                "percent_float": info.get("shortPercentOfFloat"), "shares_short": info.get("sharesShort"),
                "shares_short_prior": info.get("sharesShortPriorMonth"),
                "date_short_interest": (pd.Timestamp(info["dateShortInterest"], unit="s").strftime("%Y-%m-%d")
                                        if info.get("dateShortInterest") else None)}, today))
        if nxt and pd.Timestamp(nxt["ann_date"]) - pd.Timestamp(today) <= pd.Timedelta(days=21):
            straddle = provider.straddle(sym, pd.Timestamp(nxt["ann_date"]) + timedelta(days=1))
            if straddle:
                taken["options"] += int(store.put_snapshot(conn, sym, "options", {**straddle, "target_ann_date": nxt["ann_date"]}, today))
        if progress:
            progress(i + 1, len(symbols), sym)
    return taken
