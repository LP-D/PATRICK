"""Rapport mensuel d'un fonds en PDF (FO14 du 25/11) et stress tests historiques de ses positions ouvertes (FO15).

Le rapport tient sur quelques pages de texte (le moteur PDF sans dépendance `core/text_pdf.py`) : performance du mois et depuis
l'ouverture, frais, attribution du P&L (par modèle, par classe, par sens : `fund.insight.attribution`), ordres du mois, positions
ouvertes en fin de mois et ce qu'elles auraient perdu ou gagné dans les grandes crises passées.

Stress tests : la part risquée ACTUELLE (valeur de chaque position ouverte / valeur nette, signée selon le sens) rejouée sur les fenêtres de
`analysis.portfolio_risk.STRESS_WINDOWS` (bulle internet, crise de 2008, dette européenne, fin 2018, Covid, 2022). Seules les lignes
cotées sur toute la fenêtre comptent ; sous 60 % de couverture la fenêtre est dite insuffisante plutôt que chiffrée.
"""
from __future__ import annotations

import datetime as dt
import sqlite3

from patrick.analysis import portfolio_risk
from patrick.fund import insight, service, store

STRESS_LABELS = {"dotcom": "bulle internet (2000-2002)", "gfc": "crise financière (2007-2009)", "euro_debt": "dette européenne (2011)",
                 "q4_2018": "fin 2018", "covid": "Covid (février-mars 2020)", "bear_2022": "marché baissier de 2022"}


def stress(snapshot: dict, price_of=None) -> list[dict]:
    """Stress tests des positions ouvertes du fonds (voir l'en-tête). `price_of(symbole) -> Series` : cours historiques (cache)."""
    nav = float((snapshot.get("kpis") or {}).get("nav") or 0.0)
    if nav <= 0:
        return []
    weights: dict[str, float] = {}
    for p in snapshot.get("positions") or []:
        if p.get("status") != "open" or not p.get("symbol"):
            continue
        exposure = abs(float(p.get("value_base") or 0.0))
        if exposure < 1e-9:                       # contrat à terme ou CFD : la valeur portée est la marge, l'exposition est le notionnel
            exposure = abs(float(p.get("quantity") or 0.0)) * float(p.get("last_price") or 0.0) * float(p.get("fx_now") or 1.0)
        if exposure < 1e-9:
            continue
        sign = -1.0 if p.get("side") in ("short", "sell") else 1.0
        weights[p["symbol"]] = weights.get(p["symbol"], 0.0) + sign * exposure / nav
    if not weights:
        return []
    if price_of is None:
        from patrick.wealth import prices as wealth_prices
        price_of = wealth_prices.make_provider(allow_network=False)
    series = {s: price_of(s) for s in weights}
    series = {s: v for s, v in series.items() if v is not None and len(v)}
    # `stress_windows` suppose des poids positifs (patrimoine) : la couverture se mesure sur les poids absolus, le rendement garde le sens
    # de chaque position (une position vendeuse gagne quand le cours baisse).
    signed = weights
    out = portfolio_risk.stress_windows(series, {s: abs(w) for s, w in weights.items()})
    gross = sum(abs(w) for w in weights.values())
    for row in out:
        row["label"] = STRESS_LABELS.get(row["key"], row["key"])
        covered = sum(abs(signed[leg["symbol"]]) for leg in row["legs"])
        if row["sufficient"] and covered > 0:
            row["return_total"] = sum(signed[leg["symbol"]] * leg["return"] for leg in row["legs"]) / covered * gross
            row["return_risky"] = row["return_total"] / gross if gross else None
        for leg in row["legs"]:
            leg["weight"] = signed[leg["symbol"]]
    return out


def _pct(x) -> str:
    return "—" if x is None else f"{x * 100:+.2f} %".replace(".", ",")


def _eur(x) -> str:
    return "—" if x is None else f"{x:,.2f} €".replace(",", " ").replace(".", ",")


def _month_return(points: list[dict], month: str) -> tuple[float | None, float | None]:
    """(rendement du mois, valeur de fin de mois) d'après la courbe de valeur nette."""
    before = [p for p in points if p["t"] < f"{month}-01"]
    inside = [p for p in points if p["t"].startswith(month)]
    if not inside:
        return None, None
    start = before[-1]["nav"] if before else inside[0]["nav"]
    end = inside[-1]["nav"]
    return (end / start - 1.0) if start else None, end


def report_lines(conn: sqlite3.Connection, strategy_id: str, month: str, today: dt.date | None = None, price_of=None) -> tuple[str, list[str]]:
    """(titre, lignes) du rapport du mois `AAAA-MM`."""
    strategy = store.get_strategy(conn, strategy_id)
    if strategy is None:
        raise store.FundError("stratégie introuvable")
    snap = service.strategy_snapshot(conn, strategy, today=today)
    k = snap["kpis"]
    month_ret, month_nav = _month_return(snap["series"], month)
    lines = [f"Fonds : {strategy['name']} ({strategy.get('wrapper') or '—'}), ouvert le {strategy.get('opened_on') or '—'}",
             f"Mois : {month}", "",
             "PERFORMANCE",
             f"  Rendement du mois : {_pct(month_ret)} ; valeur nette en fin de mois : {_eur(month_nav)}",
             f"  Depuis l'ouverture : {_pct(k.get('pnl_pct'))} ({_eur(k.get('pnl'))}) ; valeur nette : {_eur(k.get('nav'))}",
             (f"  Volatilité : {_pct(k.get('volatility'))} ; Sharpe : {k.get('sharpe') if k.get('sharpe') is not None else '—'} ; "
              f"perte maximale : {_pct(k.get('max_drawdown'))}"),
             f"  Frais et financement depuis l'ouverture : {_eur(k.get('costs'))}", ""]
    attr = insight.attribution(conn, strategy_id, snap)
    lines.append("ATTRIBUTION DU P&L (depuis l'ouverture)")
    for title, key in (("par modèle", "by_rule"), ("par classe d'actifs", "by_class"), ("par sens", "by_side")):
        rows = attr.get(key) or []
        lines.append(f"  {title} : " + ("; ".join(f"{r['label']} {_eur(r['pnl'])}" for r in rows[:8]) if rows else "—"))
    lines.append("")
    month_orders = [o for o in snap["orders"] if str(o.get("ts") or "")[:7] == month]
    lines.append(f"ORDRES DU MOIS ({len(month_orders)})")
    for o in month_orders[:60]:
        lines.append(f"  {str(o.get('ts'))[:10]} {o.get('action') or ''} {o.get('side') or ''} {o.get('quantity')} {o.get('symbol')} à {o.get('price')}")
    if len(month_orders) > 60:
        lines.append(f"  … et {len(month_orders) - 60} autres")
    lines.append("")
    opened = [p for p in snap["positions"] if p.get("status") == "open"]
    lines.append(f"POSITIONS OUVERTES ({len(opened)})")
    for p in opened[:40]:
        lines.append(f"  {p['symbol']} {p['side']} : valeur {_eur(p.get('value_base'))}, P&L {_eur(p.get('pnl'))}")
    lines.append("")
    lines.append("STRESS TESTS (positions ouvertes rejouées sur les crises passées)")
    for row in stress(snap, price_of=price_of):
        if row["sufficient"]:
            lines.append(f"  {row['label']} : {_pct(row['return_total'])} du fonds (couverture {row['coverage'] * 100:.0f} %)")
        else:
            lines.append(f"  {row['label']} : historique insuffisant (couverture {row['coverage'] * 100:.0f} %)")
    lines += ["", "Chiffres simulés avant toute fiscalité ; une performance passée ne préjuge pas de l'avenir."]
    return f"PATRICK · {strategy['name']} · {month}", lines


def report_pdf(conn: sqlite3.Connection, strategy_id: str, month: str, today: dt.date | None = None, price_of=None) -> bytes:
    from patrick.core.text_pdf import text_to_pdf
    title, lines = report_lines(conn, strategy_id, month, today=today, price_of=price_of)
    return text_to_pdf(title, lines)
