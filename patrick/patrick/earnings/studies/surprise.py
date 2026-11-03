"""Surprise, ERC et dérive post-annonce (§3.D).

Surprise = (BPA publié - BPA estimé) / |BPA estimé|, fournie par Yahoo avec les annonces passées. Le SUE standardise cette surprise par
l'historique PASSÉ du titre (jamais l'événement testé, jamais le futur). Le chiffre d'affaires publié face à l'estimé et la guidance
n'ont pas d'historique gratuit : signalés comme indisponibles, pas inventés.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from patrick.earnings.studies.base import (
    GROUP_BY_CHOICES,
    Ctx,
    Param,
    cluster_ols,
    groups_of,
    insufficient,
    kruskal,
    note,
    ok,
    prepare,
    rel_for,
    study,
    table,
    unavailable,
)


def _winsorize(s: pd.Series, q: float = 0.02) -> pd.Series:
    lo, hi = s.quantile([q, 1 - q])
    return s.clip(lo, hi)


def _sue_seasonal(df: pd.DataFrame) -> pd.Series:
    """SUE à marche aléatoire saisonnière : (BPA - BPA d'il y a 4 annonces) / écart-type des variations PASSÉES (au moins 4)."""
    out = pd.Series(np.nan, index=df.index)
    for _, g in df.sort_values("day0").groupby("symbol"):
        delta = g["eps_actual"] - g["eps_actual"].shift(4)
        sd_prev = delta.shift(1).expanding(min_periods=4).std()
        out.loc[g.index] = (delta / sd_prev).where(sd_prev > 0)
    return out


@study("d_surprise_erc", "D", "Surprise et ERC",
       "Coefficient de réponse aux résultats (earnings response coefficient) : pente du CAR sur la surprise, par groupe.",
       params=(Param("measure", "choice", "pct", "Surprise", choices=("pct", "sue", "sue_seasonal")),
               Param("group_by", "choice", "all", "Grouper par", choices=GROUP_BY_CHOICES)))
def d_surprise_erc(ctx: Ctx, p: dict) -> dict:
    df = prepare(ctx, ctx.df.copy(), p["group_by"])
    df["sue_seasonal"] = _sue_seasonal(df)
    col = {"pct": "surprise_pct", "sue": "sue", "sue_seasonal": "sue_seasonal"}[p["measure"]]
    df = df.dropna(subset=[col, "car"])
    if len(df) < 12:
        return insufficient(len(df), 12)
    scale = 0.01 if p["measure"] == "pct" else 1.0
    df["x"] = _winsorize(df[col]) * scale
    rows, pv = [], {}
    for label, g in groups_of(df, p["group_by"]):
        if len(g) < 10:
            continue
        res = cluster_ols(g["car"], np.column_stack([np.ones(len(g)), g["x"]]), g["week"], ["const", "pente"])
        if res["coef"]:
            rows.append([label, res["n"], res["coef"]["pente"], res["t"]["pente"], res["p"]["pente"], res["r2"]])
            pv[f"d.erc.{p['measure']}.{label}"] = res["p"]["pente"]
    if not rows:
        return insufficient(len(df), 10, "événements par groupe")
    bins = pd.qcut(df["x"], 5, labels=False, duplicates="drop")
    quint = [[f"Q{int(k) + 1}", len(g), float(g["x"].mean()), float(g["car"].mean()), float((g["car"] > 0).mean())]
             for k, g in df.groupby(bins)]
    unit = "en fraction du BPA estimé (0,10 = +10 %)" if p["measure"] == "pct" else "en écarts-types de l'historique du titre"
    return ok([table("ERC : CAR = a + ERC × surprise", ["Groupe", "N", "ERC (pente)", "t (groupé par semaine)", "p", "R²"], rows,
                     ["str", "int", "num3", "num2", "p", "num3"], n_col=1,
                     note=f"Surprise {unit}, rognée à 2 %/98 %. Un ERC > 0 : le marché récompense les surprises positives."),
               table("Réaction moyenne par quintile de surprise", ["Quintile", "N", "Surprise moyenne", "CAR moyen", "P(hausse)"], quint,
                     ["str", "int", "num3", "pct", "pct0"], n_col=1),
               note("Le chiffre d'affaires publié face à l'estimé n'a pas d'historique gratuit : seule la surprise de BPA est étudiée.")],
              len(df), pvalues=pv, rel=rel_for(ctx, df, "car"))


@study("d_sue_pead", "D", "Dérive post-annonce (PEAD) par décile de SUE",
       "CAR après l'annonce selon le décile de surprise standardisée : la dérive existe-t-elle encore dans ton échantillon ?",
       params=(Param("measure", "choice", "sue", "Surprise", choices=("sue", "sue_seasonal")),))
def d_sue_pead(ctx: Ctx, p: dict) -> dict:
    df = ctx.df.copy()
    df["sue_seasonal"] = _sue_seasonal(df)
    col = p["measure"]
    wins = [f"drift_{a}_{b}" for a, b in ctx.cfg.drift_windows]
    df = df.dropna(subset=[col, *wins])
    if len(df) < 30:
        return insufficient(len(df), 30)
    k = 10 if len(df) >= 200 else 5 if len(df) >= 80 else 3
    df["bin"] = pd.qcut(df[col].rank(method="first"), k, labels=False)
    rows, pv = [], {}
    for b, g in df.groupby("bin"):
        rows.append([f"D{int(b) + 1}" if k == 10 else f"Q{int(b) + 1}", len(g), float(g[col].mean()), *[float(g[w].mean()) for w in wins]])
    low, high = df[df["bin"] == 0], df[df["bin"] == k - 1]
    spread = ["Écart haut − bas", len(low) + len(high), float(high[col].mean() - low[col].mean())]
    for w in wins:
        diff = float(high[w].mean() - low[w].mean())
        t = stats.ttest_ind(high[w], low[w], equal_var=False)
        res = cluster_ols(df[w], np.column_stack([np.ones(len(df)), df[col].rank(pct=True)]), df["week"], ["const", "pente"])
        spread.append(diff)
        pv[f"d.pead.spread.{w}"] = float(t.pvalue)
        if res["coef"]:
            pv[f"d.pead.slope.{w}"] = res["p"]["pente"]
    rows.append(spread)
    cols = ["Classe", "N", f"{col} moyen", *[f"CAR [{a:+d}, {b:+d}]" for a, b in ctx.cfg.drift_windows]]
    return ok([table("Dérive après l'annonce par classe de surprise", cols, rows, ["str", "int", "num2", *["pct"] * len(wins)], n_col=1,
                     note="La littérature (Ball-Brown, Bernard-Thomas) documente cette dérive mais la décrit comme très affaiblie, voire disparue, "
                          "dans les grandes capitalisations (par exemple Martineau, 2021) : à vérifier ici, pas à présumer. p calculés : "
                          "écart haut/bas (Welch) et pente sur le rang de surprise (erreurs groupées par semaine) dans le registre FDR.")],
              len(df), pvalues=pv, rel=rel_for(ctx, df, wins[-1]))


@study("d_guidance", "D", "Guidance", "Direction et ampleur de la révision de guidance : souvent plus informative que le chiffre publié.")
def d_guidance(ctx: Ctx, p: dict) -> dict:
    return unavailable("La guidance (prévisions de la direction) n'est pas disponible gratuitement sous forme structurée : elle est dans le "
                       "texte du communiqué ou de l'appel, payant ou à extraire à la main.", "transcripts")


@study("d_sequences", "D", "Séries de dépassements",
       "Séries de beats consécutifs et réaction conditionnelle à la série.")
def d_sequences(ctx: Ctx, p: dict) -> dict:
    df = ctx.df.dropna(subset=["beat", "car"]).copy()
    if len(df) < 20:
        return insufficient(len(df), 20)
    df["serie"] = df["beat_streak"].clip(upper=3).astype(int).map({0: "0 beat avant", 1: "1 beat avant", 2: "2 beats avant", 3: "3 beats ou plus"})
    rows = [[str(k), len(g), float(g["car"].mean()), float((g["car"] > 0).mean()), float(g["z_abs"].mean()), float(g["beat"].mean())]
            for k, g in df.groupby("serie")]
    pv = {"d.sequences.kruskal_car": kruskal([g["car"].to_numpy() for _, g in df.groupby("serie")]),
          "d.sequences.kruskal_amplitude": kruskal([g["z_abs"].to_numpy() for _, g in df.groupby("serie")])}
    return ok([table("Réaction selon le nombre de beats consécutifs précédents", ["Série", "N", "CAR moyen", "P(hausse)", "Amplitude (σ)",
                                                                                   "Beat cette fois"], rows,
                     ["str", "int", "pct", "pct0", "num2", "pct0"], n_col=1,
                     note="Une série de beats habitue le consensus : la surprise suivante vaut moins (hypothèse à tester, pas un fait).")],
              len(df), pvalues=pv, rel=rel_for(ctx, df, "car"))
