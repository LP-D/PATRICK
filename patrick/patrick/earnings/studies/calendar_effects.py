"""Calendrier, biais et signaux de timing (§3.J)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from patrick.earnings import engine, exchanges, signif, store
from patrick.earnings.config import EarningsConfig
from patrick.earnings.studies.base import (
    Ctx,
    insufficient,
    kruskal,
    kv,
    mann_whitney,
    note,
    ok,
    rel_for,
    spearman,
    study,
    table,
    unavailable,
)

WEEKDAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


@study("j_calendar_effects", "J", "Jour de la semaine, avant ouverture contre après clôture",
       "L'amplitude et le sens de la réaction selon le jour d'annonce et le moment de la journée.")
def j_calendar_effects(ctx: Ctx, p: dict) -> dict:
    df = ctx.df
    if len(df) < 20:
        return insufficient(len(df), 20)
    pv, blocks = {}, []
    for title, col, labels in (("Jour de l'annonce", "weekday", lambda k: WEEKDAYS[int(k)]), ("Moment de la journée", "timing", str)):
        rows = [[labels(k), len(g), float(g["z_abs"].mean()), float(g["abs_car"].mean()), float(g["car"].mean()), float((g["car"] > 0).mean())]
                for k, g in df.groupby(col) if len(g) >= 3]
        if len(rows) >= 2:
            blocks.append(table(title, ["Modalité", "N", "Amplitude (σ)", "|CAR| moyen", "CAR moyen", "P(hausse)"], rows,
                                ["str", "int", "num2", "pct", "pct", "pct0"], n_col=1))
            pv[f"j.calendar.{col}.amplitude"] = kruskal([g["z_abs"].to_numpy() for _, g in df.groupby(col)])
            pv[f"j.calendar.{col}.sign"] = kruskal([g["car"].to_numpy() for _, g in df.groupby(col)])
    if not blocks:
        return insufficient(len(df), 20)
    blocks.append(note("BMO = avant l'ouverture, AMC = après la clôture. Une publication « pendant la séance » ou à l'heure inconnue est mesurée sur "
                       "[0, +1] et mélange les deux effets.", "info"))
    return ok(blocks, len(df), pvalues=pv, rel=rel_for(ctx, df, "z_abs"))


@study("j_season_order", "J", "Premier contre dernier annonceur de la saison",
       "Dans un secteur et un trimestre, les premiers à publier surprennent-ils plus que les derniers ?")
def j_season_order(ctx: Ctx, p: dict) -> dict:
    df = ctx.df.copy()
    df["season"] = df["day0"].dt.year.astype(str) + "T" + df["day0"].dt.quarter.astype(str)
    recs = []
    for (sector, season), g in df.groupby(["sector", "season"]):
        if sector == "—" or len(g) < 3:
            continue
        g = g.sort_values("day0")
        rank = (np.arange(len(g)) + 0.5) / len(g)
        for r, (_, row) in zip(rank, g.iterrows()):
            recs.append({"pos": "premier tiers" if r < 1 / 3 else "dernier tiers" if r > 2 / 3 else "milieu", "z_abs": row["z_abs"], "car": row["car"]})
    d = pd.DataFrame(recs)
    if len(d) < 30:
        return insufficient(len(d), 30, "annonces dans des saisons de 3 titres ou plus")
    rows = [[k, len(g), float(g["z_abs"].mean()), float(g["car"].mean())] for k, g in d.groupby("pos")]
    first, last = d[d["pos"] == "premier tiers"], d[d["pos"] == "dernier tiers"]
    pa, ps = mann_whitney(first["z_abs"], last["z_abs"]), mann_whitney(first["car"], last["car"])
    return ok([table("Position dans la saison (secteur × trimestre)", ["Position", "N", "Amplitude (σ)", "CAR moyen"], rows, ["str", "int", "num2", "pct"], n_col=1,
                     note=f"Premier contre dernier tiers : p (amplitude) = {pa:.3f}, p (sens) = {ps:.3f}. Un premier annonceur porte plus "
                          "d'information sur le secteur, d'où l'hypothèse d'une réaction plus ample.")],
              len(d), pvalues={"j.season.amplitude": pa, "j.season.sign": ps})


@study("j_quarter_annual", "J", "Trimestriel contre annuel",
       "La structure d'information d'une annonce annuelle (exercice clos, prévisions) diffère d'une annonce trimestrielle.")
def j_quarter_annual(ctx: Ctx, p: dict) -> dict:
    df = ctx.df.dropna(subset=["period_end"])
    ann, qtr = df[df["is_annual"]], df[~df["is_annual"]]
    if len(ann) < 5 or len(qtr) < 5:
        return insufficient(min(len(ann), len(qtr)), 5, "annonces de chaque type")
    pa, ps = mann_whitney(ann["z_abs"], qtr["z_abs"]), mann_whitney(ann["car"], qtr["car"])
    return ok([table("Annuel (clôture d'exercice) contre trimestriel", ["Type", "N", "Amplitude (σ)", "|CAR| moyen", "CAR moyen"],
                     [["Annuel", len(ann), float(ann["z_abs"].mean()), float(ann["abs_car"].mean()), float(ann["car"].mean())],
                      ["Trimestriel", len(qtr), float(qtr["z_abs"].mean()), float(qtr["abs_car"].mean()), float(qtr["car"].mean())]],
                     ["str", "int", "num2", "pct", "pct"], n_col=1,
                     note="Annuel = l'annonce commente le trimestre qui clôt l'exercice (mois de clôture tiré de la fiche Yahoo). "
                          f"Mann-Whitney : p (amplitude) = {pa:.3f}, p (sens) = {ps:.3f}.")],
              len(df), pvalues={"j.annual.amplitude": pa, "j.annual.sign": ps}, rel=rel_for(ctx, df, "z_abs"))


@study("j_delay", "J", "Retard par rapport à la date habituelle",
       "Une publication plus tardive que d'habitude annonce-t-elle de mauvaises nouvelles ? (Chambers & Penman, 1984 : à vérifier aujourd'hui)")
def j_delay(ctx: Ctx, p: dict) -> dict:
    df = ctx.df.dropna(subset=["lag_days", "period_end"]).copy()
    df["pq"] = df["period_end"].dt.month
    df["delay"] = np.nan
    for _, g in df.sort_values("day0").groupby(["symbol", "pq"]):
        usual = g["lag_days"].shift(1).expanding(min_periods=2).median()          # délai habituel : annonces passées du même trimestre
        df.loc[g.index, "delay"] = g["lag_days"] - usual
    d = df.dropna(subset=["delay"])
    if len(d) < 20:
        return insufficient(len(d), 20, "annonces avec au moins 2 précédents comparables")
    rho, pval, n = spearman(d["delay"], d["car"])
    q = pd.qcut(d["delay"], 3, labels=["en avance", "à l'heure", "en retard"], duplicates="drop")
    rows = [[str(k), len(g), float(g["delay"].mean()), float(g["car"].mean()), float((g["car"] > 0).mean())] for k, g in d.groupby(q, observed=True)]
    return ok([kv("Retard (jours) contre réaction", [("ρ de Spearman retard → CAR", rho, "num3"), ("p", pval, "p"), ("N", n, "int")]),
               table("Réaction par tercile de retard", ["Groupe", "N", "Retard moyen (jours)", "CAR moyen", "P(hausse)"], rows,
                     ["str", "int", "num2", "pct", "pct0"], n_col=1,
                     note="Retard = délai (jours après la fin de période) moins la médiane PASSÉE du même titre et du même trimestre.")],
              n, pvalues={"j.delay.sign": pval}, rel=rel_for(ctx, d, "delay"))


@study("j_announcement_premium", "J", "Prime d'annonce",
       "Rendement anormal moyen des jours d'annonce (Savor & Wilson) : à tester sur l'échantillon, sans le présumer.")
def j_announcement_premium(ctx: Ctx, p: dict) -> dict:
    df = ctx.df
    if len(df) < 12:
        return insufficient(len(df), 12)
    rows_all = ctx.panel.payloads()
    rows_sure = ctx.panel.payloads(df[~df["uncertain"]])
    out, pv = [], {}
    for label, rows in (("Tous les événements", rows_all), ("Timing certain seulement", rows_sure)):
        for a, b in ((0, 0), (0, 1)):
            r = signif.run_tests(rows, a, b, n_boot=500)
            t = r.get("tests", {})
            out.append([f"{label} · [{a:+d}, {b:+d}]", r["n"], r.get("caar"), (t.get("bmp") or {}).get("p"), (t.get("bootstrap") or {}).get("p")])
            pv[f"j.premium.{label[:4]}.{a}.{b}"] = (t.get("bmp") or {}).get("p")
    by_year = [[int(y), len(g), float(g["ar0"].mean())] for y, g in df.groupby("year") if len(g) >= 5]
    return ok([table("Rendement anormal moyen des jours d'annonce", ["Échantillon", "N", "CAAR", "p (BMP)", "p (blocs)"], out,
                     ["str", "int", "pct", "p", "p"], n_col=1,
                     note="La prime d'annonce est un rendement anormal moyen POSITIF documenté par la littérature, de l'ordre de quelques points de "
                          "base par jour d'annonce : à vérifier ici, pas à présumer. Le modèle de marché retire la part due au marché."),
               table("CAAR [0] par année", ["Année", "N", "AR J0 moyen"], by_year, ["int", "int", "pct"], n_col=1)],
              len(df), pvalues=pv, rel=rel_for(ctx, df, "ar0"))


@study("j_local_adr", "J", "Ligne locale contre ADR",
       "Écart de réaction entre la ligne locale et son ADR (ou ligne liée), décalage horaire et contribution du change.",
       needs=("prices",), heavy=True)
def j_local_adr(ctx: Ctx, p: dict) -> dict:
    pairs = store.adr_map(ctx.conn)
    df = ctx.df[ctx.df["symbol"].isin(pairs)]
    if df.empty:
        return unavailable("Aucun titre de l'échantillon n'a de ligne ADR ou liée renseignée (écran de confirmation de la newsletter).", "adr")
    recs = []
    cfg = EarningsConfig(model="market")
    for sym, g in df.groupby("symbol"):
        adr = pairs[sym]
        sp_adr = ctx.prices.prices(adr, "market")
        if sp_adr is None:
            continue
        venue = exchanges.venue_for(sym)
        cal = {c["ann_date"]: c for c in store.calendar_for(ctx.conn, sym)}
        fx = ctx.prices.raw(f"{venue.currency}USD=X") if venue.currency != "USD" else None
        for r in g.itertuples():
            c = cal.get(str(r.ann_date.date()))
            if c and c["ann_local_time"]:
                ts = pd.Timestamp(f"{c['ann_date']} {c['ann_local_time']}", tz=venue.tz).tz_convert(exchanges.SOURCE_TZ)
                info = exchanges.classify_timing(ts, adr)
                timing, uncertain = info["timing"], info["uncertain"]
                adr_date = info["local_date"]
            else:
                timing, uncertain, adr_date = "UNKNOWN", True, r.ann_date.date()
            ev, _ = engine.compute_event(sp_adr, symbol=adr, ann_date=adr_date, timing=timing, uncertain=uncertain, cfg=cfg)
            if ev is None:
                continue
            a, b = engine.reaction_window(ev, cfg)
            lo, hi = min(r.react_lo, a), max(r.react_hi, b)
            car_adr = engine.window_sum(engine.arr(ev, "ar"), lo, hi)
            local_ar = engine.arr(ctx.panel.rows[int(r.i)], "ar")
            car_loc = engine.window_sum(local_ar, lo, hi)
            fx_ret = np.nan
            if fx is not None and pd.Timestamp(ev["day0"]) in fx.index:
                fx_ret = float(fx["Close"].pct_change().loc[pd.Timestamp(ev["day0"])])
            recs.append({"symbol": sym, "car_loc": car_loc, "car_adr": car_adr, "gap_sessions": (pd.Timestamp(ev["day0"]) - r.day0).days, "fx": fx_ret})
    d = pd.DataFrame(recs).dropna(subset=["car_loc", "car_adr"])
    if len(d) < 8:
        return insufficient(len(d), 8, "annonces avec les deux lignes")
    d["diff"] = d["car_adr"] - d["car_loc"]
    rho, pval, n = spearman(d["car_loc"], d["car_adr"])
    rows = [[s, len(g), float(g["car_loc"].mean()), float(g["car_adr"].mean()), float(g["diff"].abs().mean())] for s, g in d.groupby("symbol")]
    items = [("Paires d'événements", n, "int"), ("Corrélation ligne locale / ADR (Spearman)", rho, "num3"), ("p", pval, "p"),
             ("|écart| moyen", float(d["diff"].abs().mean()), "pct"), ("Décalage médian de J0 (jours)", float(d["gap_sessions"].median()), "num2")]
    fxd = d.dropna(subset=["fx"])
    if len(fxd) >= 8:
        r2, p2, _ = spearman(fxd["fx"], fxd["diff"])
        items += [("Corrélation change → écart ADR − local", r2, "num3"), ("p (change)", p2, "p")]
    return ok([kv("Transmission local / ADR", items),
               table("Par titre", ["Titre", "N", "CAR ligne locale", "CAR ADR", "|écart| moyen"], rows, ["str", "int", "pct", "pct", "pct"], n_col=1),
               note("L'ADR est en dollars : son rendement anormal contre le S&P 500 inclut le change. La réaction primaire se produit sur la ligne "
                    "locale quand la publication précède l'ouverture européenne ; l'ADR n'est que le contrôle.")],
              len(d), pvalues={"j.adr.corr": pval})
