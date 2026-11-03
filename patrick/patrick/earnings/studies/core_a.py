"""Cœur de l'event study (§2) et anatomie de la réaction (§3.A)."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from patrick.earnings import signif
from patrick.earnings.config import PATH_HI, PATH_LO, TESTS
from patrick.earnings.engine import arr, bhar
from patrick.earnings.studies.base import (
    GROUP_BY_CHOICES,
    Ctx,
    Param,
    bars,
    describe,
    fmt_ci,
    groups_of,
    insufficient,
    kruskal,
    line,
    ok,
    prepare,
    rel_for,
    spearman,
    study,
    table,
    wilson,
)


@study("core_event_study", "core", "Event study : CAR par fenêtre, tests de significativité",
       "CAAR du run-up, de la réaction, de la continuation et de la dérive, avec BMP (défaut), Patell, Corrado, signes, "
       "Kolari-Pynnönen et bootstrap par blocs de dates.",
       params=(Param("test", "choice", "bmp", "Test de référence (registre FDR)", choices=TESTS),
               Param("n_boot", "int", 1000, "Tirages du bootstrap", lo=200, hi=5000)))
def core_event_study(ctx: Ctx, p: dict) -> dict:
    df = ctx.df
    if len(df) < 4:
        return insufficient(len(df), 4)
    rows = ctx.panel.payloads()
    cfg = ctx.cfg
    wins = [("Run-up", cfg.run_up), ("Réaction", (0, 0)), ("Réaction", (0, 1)), ("Continuation", cfg.short_post)]
    wins += [("Dérive", (a, b)) for a, b in cfg.drift_windows]
    out_rows, pvalues = [], {}
    for name, (a, b) in wins:
        r = signif.run_tests(rows, a, b, n_boot=p["n_boot"], winsor=cfg.winsorize)
        t = r.get("tests", {})

        def pv(key, t=t):
            return (t.get(key) or {}).get("p")

        ref = pv(p["test"])
        pvalues[f"core.{name}.{a}.{b}.{p['test']}"] = ref
        out_rows.append([f"{name} [{a:+d}, {b:+d}]", r["n"], r.get("caar"), r.get("median_car"), r.get("share_positive"), ref,
                         pv("bmp"), pv("patell"), pv("corrado"), pv("sign"), pv("kp"), pv("bootstrap"), r.get("rbar")])
    z = df["z"].dropna().to_numpy()
    if len(z) >= 4 and z.std(ddof=1) > 0:
        t = z.mean() / (z.std(ddof=1) / np.sqrt(len(z)))
        out_rows.insert(1, ["Réaction (fenêtre auto par événement)", len(z), float(df["car"].mean()), float(df["car"].median()),
                            float((df["car"] > 0).mean()), None, float(2 * stats.t.sf(abs(t), len(z) - 1)), None, None, None, None,
                            None, None])
    cols = ["Fenêtre", "N", "CAAR", "Médiane", "% positifs", f"p ({p['test']})", "p BMP", "p Patell", "p Corrado", "p signes",
            "p KP", "p bootstrap", "r̄ résidus"]
    kinds = ["str", "int", "pct", "pct", "pct0", "p", "p", "p", "p", "p", "p", "p", "num2"]
    blocks = [table("CAAR et significativité par fenêtre", cols, out_rows, kinds, n_col=1,
                    note="Le verdict signé de référence est BMP (robuste à l'augmentation de variance). KP corrige de la corrélation "
                         "entre annonces d'une même semaine ; le bootstrap par blocs de dates en est le contrôle. Un t-test naïf "
                         "n'est pas affiché : il gonfle les statistiques.")]
    bh = []
    for a, b in cfg.drift_windows:
        vals = np.array([bhar(r, a, b) for r in rows])
        tab = pd.DataFrame({"car": vals, "week": df["week"].to_numpy()}).dropna()
        boot = signif.block_bootstrap(tab, 1000) if len(tab) >= 6 else {"p": None}
        bh.append([f"BHAR [{a:+d}, {b:+d}]", len(tab), float(tab["car"].mean()) if len(tab) else None,
                   float(tab["car"].median()) if len(tab) else None, float((tab["car"] > 0).mean()) if len(tab) else None, boot["p"]])
        pvalues[f"core.bhar.{a}.{b}"] = boot["p"]
    if bh:
        blocks.append(table("BHAR (rendement anormal composé)", ["Fenêtre", "N", "Moyenne", "Médiane", "% positifs", "p (blocs)"],
                            bh, ["str", "int", "pct", "pct", "pct0", "p"], n_col=1,
                            note="Le BHAR compose les rendements : il est asymétrique et sensible aux valeurs extrêmes, donc testé par blocs."))
    ar_mat = np.array([arr(r, "ar") for r in rows])
    cum = np.where(np.isfinite(ar_mat), np.cumsum(np.nan_to_num(ar_mat), axis=1), np.nan)
    count = np.isfinite(cum).sum(axis=0)
    with np.errstate(invalid="ignore"):
        mean = np.nanmean(cum, axis=0)
        se = np.nanstd(cum, axis=0, ddof=1) / np.sqrt(np.maximum(count, 1))
    keep = count >= max(4, int(0.5 * len(rows)))
    xs = [d for d, k in zip(range(PATH_LO, PATH_HI + 1), keep) if k]
    blocks.append(line("CAAR moyen cumulé depuis J−10 (événements empilés)", xs,
                       [{"name": "CAAR", "y": [float(m) for m, k in zip(mean, keep) if k]}], "séances relatives à J0", "pct",
                       band={"lo": [float(m - 1.96 * s) for m, s, k in zip(mean, se, keep) if k],
                             "hi": [float(m + 1.96 * s) for m, s, k in zip(mean, se, keep) if k]}))
    u = []
    for a, b in ((0, 0), (0, 1)):
        r = signif.abs_move_test(rows, a, b)
        u.append([f"|CAR| [{a:+d}, {b:+d}]", r["n"], r.get("mean_percentile"), r.get("p_rank"), r.get("mean_z2"), r.get("p_var")])
        pvalues[f"core.abs.rank.{a}.{b}"] = r.get("p_rank")
        pvalues[f"core.abs.var.{a}.{b}"] = r.get("p_var")
    blocks.append(table("Bouge-t-il plus que d'habitude ? (sans le sens)",
                        ["Fenêtre", "N", "Percentile moyen", "p (rang)", "z² moyen", "p (variance)"], u,
                        ["str", "int", "num3", "p", "num2", "p"], n_col=1,
                        note="Le percentile moyen vaut 0,5 sous H0 ; z² moyen vaut 1. Utile quand hausses et baisses s'annulent."))
    flags = []
    if df["uncertain"].mean() > 0.3:
        flags.append("plus de 30 % des événements ont un timing incertain")
    if df["model_used"].ne(cfg.model).any():
        flags.append("certains événements ont un modèle de repli (voir M : ajustements)")
    return ok(blocks, len(df), pvalues=pvalues, rel=rel_for(ctx, df, "car"), flags=flags)


@study("a_reaction_dist", "A", "Distribution des réactions",
       "Moyenne, médiane, écart-type, asymétrie, aplatissement, quantiles ; probabilité de hausse et de gros mouvement.",
       params=(Param("group_by", "choice", "all", "Grouper par", choices=GROUP_BY_CHOICES),))
def a_reaction_dist(ctx: Ctx, p: dict) -> dict:
    df = prepare(ctx, ctx.df, p["group_by"])
    if len(df) < 4:
        return insufficient(len(df), 4)
    rows = []
    for label, g in groups_of(df, p["group_by"]):
        d = describe(g["car"])
        up = int((g["car"] > 0).sum())
        lo, hi = wilson(up, len(g))
        big = float((g["z_abs"] > ctx.cfg.big_move_sigma).mean())
        rows.append([label, d["n"], d.get("mean"), d.get("median"), d.get("sd"), d.get("skew"), d.get("kurt"), d.get("q05"),
                     d.get("q95"), up / len(g), fmt_ci(lo, hi), big, float(g["abs_car"].median())])
    cols = ["Groupe", "N", "Moyenne", "Médiane", "Écart-type", "Asymétrie", "Aplatissement", "q05", "q95", "P(hausse)", "IC 95 %",
            f"P(|CAR|>{ctx.cfg.big_move_sigma:g}σ)", "|CAR| médian"]
    kinds = ["str", "int", "pct", "pct", "pct", "num2", "num2", "pct", "pct", "pct0", "str", "pct0", "pct"]
    pv = {}
    parts = [g["car"].to_numpy() for _, g in groups_of(df, p["group_by"])]
    if len(parts) > 1:
        pv["a.dist.kruskal"] = kruskal(parts)
    return ok([table("Distribution du CAR de réaction", cols, rows, kinds, n_col=1,
                     note="Le CAR est mesuré sur la fenêtre de réaction de chaque événement ([0] si le timing est certain, sinon [0, +1])."),
               bars("Part des |CAR| au-delà de l'écart-type quotidien (σ)", [r[0] for r in rows], [r[11] for r in rows], "pct0")],
              len(df), pvalues=pv, rel=rel_for(ctx, df, "car"))


@study("a_overnight_share", "A", "Overnight contre intraday",
       "Part du mouvement joué à l'ouverture (clôture → ouverture) : rapidité d'incorporation de l'information.",
       params=(Param("group_by", "choice", "all", "Grouper par", choices=GROUP_BY_CHOICES),))
def a_overnight_share(ctx: Ctx, p: dict) -> dict:
    df = prepare(ctx, ctx.df.dropna(subset=["on0", "id0"]), p["group_by"])
    if len(df) < 4:
        return insufficient(len(df), 4)
    rows = []
    for label, g in groups_of(df, p["group_by"]):
        share = (g["on0"].abs() / (g["on0"].abs() + g["id0"].abs())).dropna()
        same = float((np.sign(g["on0"]) == np.sign(g["id0"])).mean())
        rows.append([label, len(g), float(g["on0"].abs().median()), float(g["id0"].abs().median()), float(share.median()),
                     float(g["on0"].abs().sum() / (g["on0"].abs().sum() + g["id0"].abs().sum())), same])
    return ok([table("Décomposition du jour de réaction (rendements bruts)",
                     ["Groupe", "N", "|overnight| médian", "|intraday| médian", "Part overnight (médiane)", "Part overnight (cumulée)",
                      "Même sens"], rows, ["str", "int", "pct", "pct", "pct0", "pct0", "pct0"], n_col=1,
                     note="Overnight = clôture de la veille → ouverture ; intraday = ouverture → clôture. Une part overnight élevée signifie "
                          "que l'information est incorporée dès l'ouverture ; « même sens » mesure la poursuite intraday du gap.")],
              len(df), rel=rel_for(ctx, df, "on0"))


@study("a_continuation", "A", "Continuation ou retournement",
       "Corrélation entre la réaction et le rendement anormal [+2, +5] : le marché sur-réagit-il ?")
def a_continuation(ctx: Ctx, p: dict) -> dict:
    df = ctx.df.dropna(subset=["car", "post_short"])
    if len(df) < 8:
        return insufficient(len(df), 8)
    out, pv = [], {}
    targets = [(f"Continuation [{ctx.cfg.short_post[0]:+d}, {ctx.cfg.short_post[1]:+d}]", "post_short")]
    targets += [(f"Dérive [{a:+d}, {b:+d}]", f"drift_{a}_{b}") for a, b in ctx.cfg.drift_windows]
    for label, col in targets:
        d = df.dropna(subset=[col])
        rho, pval, n = spearman(d["car"], d[col])
        slope = float(np.polyfit(d["car"], d[col], 1)[0]) if len(d) > 3 else np.nan
        out.append([label, n, rho, pval, slope, "retournement" if rho < 0 else "continuation"])
        pv[f"a.cont.{col}"] = pval
    return ok([table("Réaction immédiate → rendement ultérieur", ["Cible", "N", "ρ de Spearman", "p", "Pente", "Lecture"], out,
                     ["str", "int", "num3", "p", "num3", "str"], n_col=1,
                     note="ρ < 0 : retournement (sur-réaction) ; ρ > 0 : continuation (sous-réaction, dérive).")],
              len(df), pvalues=pv, rel=rel_for(ctx, df, "car"))


@study("a_beat_and_drop", "A", "« Beat and drop »",
       "Résultat au-dessus du consensus et titre qui baisse : l'écart entre consensus officiel et attentes implicites.",
       params=(Param("group_by", "choice", "all", "Grouper par", choices=GROUP_BY_CHOICES),))
def a_beat_and_drop(ctx: Ctx, p: dict) -> dict:
    df = prepare(ctx, ctx.df.dropna(subset=["surprise_pct", "car"]), p["group_by"])
    if len(df) < 8:
        return insufficient(len(df), 8)
    rows, pv = [], {}
    for label, g in groups_of(df, p["group_by"]):
        beats, misses = g[g["surprise_pct"] > 0], g[g["surprise_pct"] < 0]
        drop = float((beats["car"] < 0).mean()) if len(beats) else np.nan
        rise = float((misses["car"] > 0).mean()) if len(misses) else np.nan
        rows.append([label, len(g), len(beats) / len(g), drop, len(misses) / len(g), rise])
    beats, rest = df[df["surprise_pct"] > 0], df[df["surprise_pct"] <= 0]
    if len(beats) >= 5 and len(rest) >= 5:
        contingency = [[int((beats["car"] < 0).sum()), int((beats["car"] >= 0).sum())],
                       [int((rest["car"] < 0).sum()), int((rest["car"] >= 0).sum())]]
        pv["a.beatdrop.fisher"] = float(stats.fisher_exact(contingency)[1])
    return ok([table("Dépassement du consensus et sens de la réaction",
                     ["Groupe", "N", "Part de beats", "Beats suivis d'une baisse", "Part de misses", "Misses suivis d'une hausse"], rows,
                     ["str", "int", "pct0", "pct0", "pct0", "pct0"], n_col=1,
                     note="Le test de Fisher compare la fréquence de baisse après un beat à celle observée sans beat. "
                          "Surprise = (BPA publié − estimé) / |estimé| fournie par Yahoo ; le chiffre d'affaires n'a pas d'historique gratuit.")],
              len(df), pvalues=pv, rel=rel_for(ctx, df, "car"))


@study("a_jump_share", "A", "Concentration des sauts",
       "Part de la variance annuelle d'un titre concentrée sur ses jours d'annonce.")
def a_jump_share(ctx: Ctx, p: dict) -> dict:
    df = ctx.df.dropna(subset=["car", "sigma"]).copy()
    if len(df) < 8:
        return insufficient(len(df), 8)
    df["n_days"] = df["react_hi"] - df["react_lo"] + 1
    df["ev_var"] = df["car"] ** 2
    recs = []
    for (symbol, year), g in df.groupby(["symbol", "year"]):
        ev = float(g["ev_var"].sum())
        days = int(g["n_days"].sum())
        normal = float((g["sigma"] ** 2).mean()) * max(252 - days, 1)
        recs.append({"symbol": symbol, "year": year, "share": ev / (ev + normal), "expected": days / 252})
    res = pd.DataFrame(recs)
    by_sym = res.groupby("symbol").agg(share=("share", "mean"), expected=("expected", "mean"), years=("year", "count")).reset_index()
    by_sym["ratio"] = by_sym["share"] / by_sym["expected"]
    table_rows = [[r.symbol, int(r.years), float(r.share), float(r.expected), float(r.ratio)]
                  for r in by_sym.sort_values("share", ascending=False).itertuples()][:40]
    return ok([table("Variance annuelle portée par les jours d'annonce",
                     ["Titre", "Années", "Part observée", "Part si jours ordinaires", "Rapport"], table_rows,
                     ["str", "int", "pct0", "pct0", "num2"], n_col=1,
                     note="Part observée = Σ CAR² des jours de réaction / (Σ CAR² + σ² × jours ordinaires). Un rapport de 6 signifie "
                          "que les jours d'annonce pèsent six fois ce que pèseraient des jours ordinaires.")],
              len(df), rel=rel_for(ctx, df, "car"))
