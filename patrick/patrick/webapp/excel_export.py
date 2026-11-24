"""Export Excel en un clic (A25) : dernières prédictions des champions, champions, fonds. Lecture seule, classeur construit en mémoire.

Le classeur est fait pour être retravaillé dans Excel : une feuille par sujet, en-têtes figés, filtres, nombres en vrais nombres (pas en texte),
dates ISO. Aucune donnée personnelle hors des fonds simulés (le patrimoine n'y est jamais).
"""
from __future__ import annotations

import datetime as dt
import io
import sqlite3

_DIRECTION = {0: "baisse forte", 1: "baisse faible", 2: "hausse faible", 3: "hausse forte"}


def _latest_predictions(conn: sqlite3.Connection) -> list[list]:
    rows = []
    champions = conn.execute("SELECT c.target, c.horizon, c.trial_id, t.algo FROM champion c LEFT JOIN trial t ON t.trial_id = c.trial_id "
                             "ORDER BY c.target, c.horizon").fetchall()
    for target, horizon, trial_id, algo in champions:
        last = conn.execute(
            "SELECT ts, y_pred, y_proba, p_up FROM prediction INDEXED BY sqlite_autoindex_prediction_1 "
            "WHERE trial_id = ? AND split = 'live' ORDER BY ts DESC LIMIT 1", (trial_id,)).fetchone()
        if last is None:
            continue
        ts, y_pred, y_proba, p_up = last
        cls = round(y_pred) if y_pred is not None else None
        rows.append([target, int(horizon), str(ts)[:10], _DIRECTION.get(cls, "?"), "hausse" if cls is not None and cls >= 2 else "baisse",
                     y_proba, p_up, algo, int(trial_id)])
    return rows


def _champions(conn: sqlite3.Connection) -> list[list]:
    return [[t, int(h), r, a, str(p)[:19], reason, f1] for t, h, r, a, p, reason, f1 in conn.execute(
        "SELECT c.target, c.horizon, c.run_id, t.algo, c.promoted_at, c.reason, c.holdout_f1_dir FROM champion c "
        "LEFT JOIN trial t ON t.trial_id = c.trial_id ORDER BY c.target, c.horizon")]


def _funds(conn: sqlite3.Connection, today: dt.date) -> list[list]:
    from patrick.fund import service

    rows = []
    for snap in service.overview(conn, today)["strategies"]:
        s, k = snap["strategy"], snap["kpis"]
        rows.append([s["name"], s.get("wrapper"), s.get("category"), k.get("capital"), k.get("nav"), k.get("pnl"), k.get("pnl_pct"),
                     k.get("gross_pnl"), k.get("sharpe"), k.get("max_drawdown"), k.get("n_open_positions")])
    return rows


SHEETS = (
    ("Prédictions", ["Cible", "Horizon (j)", "Date du signal", "Classe", "Sens", "Confiance", "P(hausse)", "Algorithme", "Essai"], _latest_predictions),
    ("Champions", ["Cible", "Horizon (j)", "Run", "Algorithme", "Promu le", "Motif", "F1 directionnel holdout"], _champions),
)


def workbook_bytes(conn: sqlite3.Connection, today: dt.date) -> bytes:
    """Le classeur (.xlsx) complet."""
    import xlsxwriter

    buf = io.BytesIO()
    book = xlsxwriter.Workbook(buf, {"in_memory": True, "nan_inf_to_errors": True})
    head = book.add_format({"bold": True, "bg_color": "#EEEEEE", "border": 1})
    pct = book.add_format({"num_format": "0.00%"})
    eur = book.add_format({"num_format": "#,##0 €"})
    sheets = [*SHEETS, ("Fonds", ["Fonds", "Enveloppe", "Catégorie", "Capital", "Valeur", "P&L", "P&L %", "P&L avant frais", "Sharpe",
                                  "Repli maximal", "Positions ouvertes"], lambda c: _funds(c, today))]
    for title, header, build in sheets:
        ws = book.add_worksheet(title)
        rows = build(conn)
        ws.write_row(0, 0, header, head)
        for i, row in enumerate(rows, start=1):
            ws.write_row(i, 0, [None if v is None else v for v in row])
        ws.freeze_panes(1, 0)
        ws.autofilter(0, 0, max(len(rows), 1), len(header) - 1)
        for j, name in enumerate(header):
            ws.set_column(j, j, max(12, min(40, len(name) + 4)), pct if name.endswith("%") or name == "Repli maximal" else
                          eur if name in ("Capital", "Valeur", "P&L", "P&L avant frais") else None)
    info = book.add_worksheet("À propos")
    info.write_row(0, 0, ["Export PATRICK", dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC")], head)
    info.write(2, 0, "Fonds simulés (capital fictif pour la catégorie quant). Aucune recommandation d'achat ou de vente.")
    book.close()
    return buf.getvalue()
