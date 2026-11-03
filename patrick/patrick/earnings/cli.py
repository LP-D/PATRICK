"""Commandes `patrick earnings ...` : mêmes fonctions que la page /resultats, depuis le terminal (et la tâche de nuit).

- `parse` : lit une newsletter (fichier ou entrée standard), résout les noms et crée un lot à confirmer ;
- `run` : confirme les lignes proposées (celles qui ont un symbole) et calcule ; équivalent du bouton « Confirmer et calculer » ;
- `snapshot` : instantané du jour du consensus, des vendeurs à découvert et du straddle des titres suivis (étape de nuit) ;
- `studies`, `study`, `ledger` : liste des cartes, calcul d'une carte, verdict FDR ;
- `manual` : dates passées saisies à la main pour un titre sans historique Yahoo.
"""
from __future__ import annotations

import math
import sys
from datetime import date

import typer

from patrick.earnings import consensus, service, store
from patrick.earnings.config import EarningsConfig
from patrick.tracking import db as trackdb

app = typer.Typer(help="Événements de résultats : newsletter, event study, bibliothèque d'études, instantanés quotidiens.")


def _provider():
    from patrick.earnings.provider import YahooProvider
    return YahooProvider()


def _cfg(conn) -> EarningsConfig:
    try:
        return EarningsConfig.from_dict(store.get_state(conn, "config", {})).validate()
    except ValueError:
        return EarningsConfig()


def _plain(value, kind: str) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    if kind == "pct":
        return f"{value * 100:+.2f} %"
    if kind == "pct0":
        return f"{value * 100:.0f} %"
    if kind == "pct1":
        return f"{value * 100:.1f} %"
    if kind in ("num2", "num3"):
        return f"{value:.{2 if kind == 'num2' else 3}f}"
    if kind == "p":
        return "<0.001" if value < 0.001 else f"{value:.3f}"
    if kind == "int":
        return str(int(value))
    return str(value)


def print_result(res: dict) -> None:
    status = res.get("status")
    typer.echo(f"[{status}] N = {res.get('n')}")
    if status != "ok":
        typer.echo(res.get("reason", ""))
        return
    rel = res.get("reliability")
    if rel:
        typer.echo(f"Fiabilité : {rel['level']} ({rel['score']}/100)")
    for flag in res.get("flags", []):
        typer.echo(f"! {flag}")
    for b in res["blocks"]:
        if b["type"] == "table":
            typer.echo(f"\n## {b['title']}")
            typer.echo("| " + " | ".join(b["columns"]) + " |")
            for row in b["rows"]:
                typer.echo("| " + " | ".join(_plain(v, k) for v, k in zip(row, b["kinds"])) + " |")
            if b.get("note"):
                typer.echo(f"({b['note']})")
        elif b["type"] == "kv":
            typer.echo(f"\n## {b['title']}")
            for it in b["items"]:
                typer.echo(f"  {it['label']} : {_plain(it['value'], it['kind'])}")
        elif b["type"] == "note":
            typer.echo(f"\n> {b['text']}")


@app.command("parse")
def parse_cmd(file: str = typer.Argument("-", help="Fichier de la newsletter (« - » = entrée standard)"),
              anchor: str = typer.Option("", "--anchor", help="Lundi de la semaine (AAAA-MM-JJ) ; défaut : lundi de la semaine en cours")) -> None:
    """Analyse la newsletter, résout les noms en lignes de cotation et crée un lot à confirmer."""
    text = sys.stdin.read() if file == "-" else open(file, encoding="utf-8").read()  # noqa: SIM115 -- lecture unique d'un fichier court
    conn = trackdb.connect()
    try:
        batch_id, warnings = service.create_batch(conn, _provider(), text, date.fromisoformat(anchor) if anchor else None)
        for w in warnings:
            typer.echo(f"! {w}")
        if not batch_id:
            raise typer.Exit(1)
        typer.echo(f"Lot {batch_id} créé (semaine du {store.get_batch(conn, batch_id)['anchor_monday']}).")
        for it in store.batch_items(conn, batch_id):
            typer.echo(f"  {it['plan_date']}  {it['name']:24s} -> {it['symbol']!s:12s} ADR/liée : {it['adr_symbol']!s:8s} {'; '.join(it['flags'])}")
        typer.echo(f"Pour confirmer et calculer : patrick earnings run --batch {batch_id}")
    finally:
        conn.close()


@app.command("run")
def run_cmd(batch: int = typer.Option(..., "--batch", help="Numéro du lot")) -> None:
    """Confirme les lignes proposées (celles qui ont un symbole), calcule les mesures et affiche la vue semaine."""
    conn = trackdb.connect()
    try:
        items = store.batch_items(conn, batch)
        if not items:
            typer.echo("Lot inconnu ou vide.")
            raise typer.Exit(1)
        edits = [{"item_id": i["item_id"], "include": bool(i["symbol"]), "symbol": i["symbol"] or "", "adr_symbol": i["adr_symbol"] or "",
                  "timing": i["timing_override"] or "auto"} for i in items]
        typer.echo(service.confirm_batch(conn, batch, edits))
        cfg = _cfg(conn)
    finally:
        conn.close()
    out = service.process_batch(trackdb.connect, _provider(), batch, cfg, progress=lambda d, t, s, e: typer.echo(f"  {d}/{t} {s} ({e:.1f} s)"))
    for r in out["reports"]:
        typer.echo(f"  {r.symbol:11s} annonces {r.n_calendar:3d}  événements {r.n_events:3d}  indice {r.benchmark:9s} {r.errors or ''}")
    conn = trackdb.connect()
    try:
        for row in service.week_rows(conn, batch, cfg):
            h = row["hist"]
            exp = f"{row['expected_abs'] * 100:.2f} %" if row["expected_abs"] is not None else "—"
            typer.echo(f"  {row['ann_date']} {row['timing']:7s} {row['name']:22s} N={h['n']:3d}  amplitude attendue {exp:9s} {', '.join(row['flags'])}")
    finally:
        conn.close()


@app.command("snapshot")
def snapshot_cmd(symbols: str = typer.Option("", "--symbols", help="Symboles séparés par des virgules ; défaut : annonces des 30 prochains jours")) -> None:
    """Instantané du jour (consensus, vendeurs à découvert, straddle de la prochaine annonce). Un instantané déjà pris aujourd'hui est ignoré."""
    conn = trackdb.connect()
    try:
        names = [s.strip() for s in symbols.split(",") if s.strip()] or consensus.tracked_symbols(conn)
        if not names:
            typer.echo("Aucun titre suivi (colle d'abord une newsletter).")
            return
        taken = consensus.take_snapshots(conn, _provider(), names)
        typer.echo(f"{len(names)} titre(s) : {taken['consensus']} consensus, {taken['short']} vendeurs à découvert, {taken['options']} straddles pris.")
    finally:
        conn.close()


@app.command("studies")
def studies_cmd() -> None:
    """Liste des cartes d'étude de la bibliothèque."""
    from patrick.earnings.studies import GROUP_TITLES, REGISTRY
    group = None
    for st in sorted(REGISTRY.values(), key=lambda s: (s.group, s.id)):
        if st.group != group:
            group = st.group
            typer.echo(f"\n{GROUP_TITLES[group]}")
        typer.echo(f"  {st.id:26s} {st.title}{'  [long]' if st.heavy else ''}")


@app.command("study")
def study_cmd(study_id: str = typer.Argument(..., help="Identifiant de la carte (voir `patrick earnings studies`)"),
              scope: str = typer.Option("all", "--scope", help="all, symbol:AAPL, sector:Technology, country:France, batch:12, week:2026-11-02"),
              param: str = typer.Option("", "--param", help="clé=valeur séparés par des virgules, ex. group_by=sector,test=bmp"),
              force: bool = typer.Option(False, "--force", help="Recalcule même si le cache est à jour")) -> None:
    """Calcule (ou relit du cache) une carte d'étude et l'affiche."""
    from patrick.earnings.panel import Scope, load_panel
    from patrick.earnings.studies import REGISTRY, Ctx, run_study
    if study_id not in REGISTRY:
        typer.echo(f"Carte inconnue : {study_id}")
        raise typer.Exit(1)
    params = dict(p.split("=", 1) for p in param.split(",") if "=" in p)
    conn = trackdb.connect()
    try:
        cfg = _cfg(conn)
        sc = Scope.parse(scope)
        full = load_panel(conn, cfg)
        batch_symbols = [i["symbol"] for i in store.batch_items(conn, int(sc.value)) if i["symbol"]] if sc.kind == "batch" else []
        ctx = Ctx(full.with_scope(sc, batch_symbols), full, conn, _provider(), cfg, sc, batch_symbols=batch_symbols)
        print_result(run_study(ctx, study_id, params, force))
    finally:
        conn.close()


@app.command("ledger")
def ledger_cmd(scope: str = typer.Option("all", "--scope"), alpha: float = typer.Option(0.10, "--alpha")) -> None:
    """Verdict FDR de toutes les cartes déjà calculées pour le périmètre."""
    from patrick.earnings.panel import Scope, load_panel
    from patrick.earnings.studies import Ctx, fdr_ledger
    from patrick.earnings.studies.runner import ledger_inputs
    conn = trackdb.connect()
    try:
        cfg = _cfg(conn)
        sc = Scope.parse(scope)
        full = load_panel(conn, cfg)
        ctx = Ctx(full.with_scope(sc), full, conn, _provider(), cfg, sc)
        led = fdr_ledger(ledger_inputs(ctx), alpha)
        typer.echo(f"{led['n_tested']} tests, {led['n_raw']} « significatifs » bruts, {led['n_bh']} survivent à Benjamini-Hochberg ({alpha:.0%}).")
        for r in led["rows"][:40]:
            typer.echo(f"  {r['key'][:70]:70s} p={r['p']:.4f} q={r['q']:.4f} {'SURVIT' if r['survives'] else ''}")
    finally:
        conn.close()


@app.command("manual")
def manual_cmd(symbol: str = typer.Argument(...), file: str = typer.Argument(..., help="Une date par ligne : AAAA-MM-JJ [HH:MM] [BMO|AMC]")) -> None:
    """Ajoute à la main des dates passées d'un titre sans historique Yahoo, puis recalcule ses mesures."""
    from patrick.earnings import pipeline, schedule
    rows = schedule.parse_manual_dates(symbol, open(file, encoding="utf-8").read())  # noqa: SIM115
    conn = trackdb.connect()
    try:
        store.upsert_calendar(conn, rows, keep_user=False)
        rep = pipeline.ingest_symbol(conn, _provider(), symbol, _cfg(conn), refresh_calendar=False)
        typer.echo(f"{len(rows)} date(s) ajoutée(s) ; {rep.n_events} événement(s) mesuré(s). {rep.errors or ''}")
    finally:
        conn.close()

