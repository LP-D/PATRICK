"""Transmission entre titres et vers l'indice (§3.G), régimes (§3.H), facteurs et structure (§3.I)."""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from patrick.earnings.studies.base import (
    Ctx,
    Param,
    cluster_ols,
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
from patrick.validation.fdr import benjamini_hochberg

log = logging.getLogger(__name__)


# ------------------------------------------------------------------------------------------------------------------ G

@study("g_peer_transmission", "G", "Lecture croisée au sein de la saison",
       "La réaction d'un titre qui publie plus tard, conditionnée à celle des pairs du même secteur qui ont déjà publié.",
       params=(Param("level", "choice", "sector", "Pairs", choices=("sector", "industry")),
               Param("days", "int", 10, "Fenêtre de pairs (jours calendaires)", lo=1, hi=45)))
def g_peer_transmission(ctx: Ctx, p: dict) -> dict:
    full, df = ctx.full.frame, ctx.df
    recs = []
    lvl = p["level"]
    for r in df.itertuples():
        if getattr(r, lvl) in ("—", None):
            continue
        peers = full[(full[lvl] == getattr(r, lvl)) & (full["symbol"] != r.symbol) & (full["day0"] < r.day0)
                     & (full["day0"] >= r.day0 - pd.Timedelta(days=p["days"]))]
        if len(peers):
            recs.append({"z": r.z, "car": r.car, "peer_z": peers["z"].mean(), "peer_car": peers["car"].mean(), "n_peers": len(peers),
                         "week": r.week, "sector": r.sector})
    d = pd.DataFrame(recs).dropna(subset=["z", "peer_z"])
    if len(d) < 20:
        return insufficient(len(d), 20, "événements avec pairs ayant déjà publié")
    rows, pv = [], {}
    for label, y, x in (("Réaction standardisée (z)", "z", "peer_z"), ("CAR brut", "car", "peer_car")):
        res = cluster_ols(d[y], np.column_stack([np.ones(len(d)), d[x]]), d["week"], ["const", "pente"])
        if res["coef"]:
            rows.append([label, res["n"], res["coef"]["pente"], res["t"]["pente"], res["p"]["pente"], res["r2"]])
            pv[f"g.peer.{y}"] = res["p"]["pente"]
    by_sector = [[s, len(g), float(g["peer_z"].corr(g["z"]))] for s, g in d.groupby("sector") if len(g) >= 10]
    blocks = [table("Réaction du titre sur la réaction moyenne des pairs déjà publiés", ["Variable", "N", "Pente", "t (groupé par semaine)", "p", "R²"],
                    rows, ["str", "int", "num3", "num2", "p", "num3"], n_col=1,
                    note="Une pente > 0 : les pairs qui publient avant « informent » ceux qui publient après (ex. Arm et Qualcomm le mercredi "
                         "conditionnés à AMD le mardi). Les chocs de marché communs sont déjà retirés des rendements anormaux.")]
    if by_sector:
        blocks.append(table("Corrélation par secteur", ["Secteur", "N", "Corrélation"], by_sector, ["str", "int", "num2"], n_col=1))
    return ok(blocks, len(d), pvalues=pv, rel=rel_for(ctx, df, "car"))


@study("g_leader_follower", "G", "Leader → suiveurs",
       "Transmission de la réaction du plus gros titre d'un secteur à ses pairs. Le graphe fournisseurs/clients n'existe pas en gratuit : "
       "le leader est le titre de plus grande capitalisation du secteur.",
       params=(Param("days", "int", 10, "Fenêtre après le leader (jours)", lo=1, hi=45),))
def g_leader_follower(ctx: Ctx, p: dict) -> dict:
    full, df = ctx.full.frame, ctx.df
    caps = {s: ctx.full.instruments.get(s, {}).get("marketCap") or 0 for s in full["symbol"].unique()}
    leaders = {}
    for sector, g in full.groupby("sector"):
        syms = g["symbol"].unique()
        if sector != "—" and len(syms) >= 3:
            leaders[sector] = max(syms, key=lambda s: caps.get(s, 0))
    recs = []
    for r in df.itertuples():
        lead = leaders.get(r.sector)
        if lead is None or lead == r.symbol:
            continue
        ev = full[(full["symbol"] == lead) & (full["day0"] < r.day0) & (full["day0"] >= r.day0 - pd.Timedelta(days=p["days"]))]
        if len(ev):
            recs.append({"z": r.z, "lead_z": ev["z"].iloc[-1], "week": r.week, "sector": r.sector})
    d = pd.DataFrame(recs).dropna()
    if len(d) < 15:
        return insufficient(len(d), 15, "suiveurs ayant publié après leur leader")
    res = cluster_ols(d["z"], np.column_stack([np.ones(len(d)), d["lead_z"]]), d["week"], ["const", "pente"])
    return ok([table("Leaders retenus", ["Secteur", "Leader (plus grande capitalisation)"], [[s, v] for s, v in leaders.items()], ["str", "str"]),
               kv("Réaction du suiveur sur celle de son leader", [("Pente", res["coef"]["pente"], "num3"), ("t (groupé par semaine)", res["t"]["pente"], "num2"),
                                                                 ("p", res["p"]["pente"], "p"), ("N", res["n"], "int")]),
               note("Hypothèse plausible dont la force est à mesurer : un petit N ou une pente proche de 0 est un résultat, pas une absence de test.")],
              len(d), pvalues={"g.leader.slope": res["p"]["pente"]})


@study("g_index_impact", "G", "Impact sur l'indice",
       "Contribution des méga-capitalisations au mouvement de l'indice le jour de l'annonce (poids = capitalisation relative dans l'échantillon).",
       needs=("prices",))
def g_index_impact(ctx: Ctx, p: dict) -> dict:
    df = ctx.df[ctx.df["region"] == "US"]
    if len(df) < 10:
        return insufficient(len(df), 10, "annonces américaines")
    bench = ctx.prices.raw("^GSPC")
    if bench is None:
        return unavailable("Prix de l'indice S&P 500 indisponibles.", "prices")
    idx_ret = bench["Close"].pct_change()
    recs = []
    for day0, g in df.groupby("day0"):
        caps = g["mcap"].fillna(0)
        if caps.sum() <= 0 or day0 not in idx_ret.index:
            continue
        w = caps / caps.sum()
        recs.append({"day0": day0, "contribution": float((w * g["car"]).sum()), "index_ret": float(idx_ret.loc[day0]), "n": len(g),
                     "top": g.loc[caps.idxmax(), "symbol"], "week": g["week"].iloc[0]})
    d = pd.DataFrame(recs)
    if len(d) < 10:
        return insufficient(len(d), 10, "jours d'annonce documentés")
    res = cluster_ols(d["index_ret"], np.column_stack([np.ones(len(d)), d["contribution"]]), d["week"], ["const", "pente"])
    rho, _pval, _ = spearman(d["contribution"], d["index_ret"])
    top = d.assign(a=d["contribution"].abs()).sort_values("a", ascending=False).head(10)
    return ok([kv("Rendement de l'indice contre contribution des annonces", [("Jours", len(d), "int"), ("Pente", res["coef"]["pente"], "num3"),
                                                                              ("p", res["p"]["pente"], "p"), ("ρ de Spearman", rho, "num3")]),
               table("Dix plus fortes contributions", ["Jour", "Annonces", "Plus grosse capitalisation", "Contribution (pondérée)", "Indice"],
                     [[str(r.day0.date()), r.n, r.top, r.contribution, r.index_ret] for r in top.itertuples()],
                     ["str", "int", "str", "pct", "pct"]),
               note("Poids = capitalisation relative DANS L'ÉCHANTILLON du jour, pas le poids réel dans l'indice (les poids d'indice ne sont pas "
                    "gratuits) : un indicateur de direction, pas une attribution comptable. Capitalisations actuelles (non point-in-time).")],
              len(d), pvalues={"g.index.slope": res["p"]["pente"]})


@study("g_week_density", "G", "Densité de la semaine de résultats et volatilité de l'indice",
       "Nombre d'annonces de la semaine (rapporté aux titres actifs) contre la volatilité réalisée du S&P 500 et le VIX.", needs=("prices",))
def g_week_density(ctx: Ctx, p: dict) -> dict:
    full = ctx.full.frame
    spx, vix = ctx.prices.raw("^GSPC"), ctx.prices.raw("^VIX")
    if spx is None:
        return unavailable("Prix de l'indice indisponibles.", "prices")
    us = full[full["region"] == "US"]
    weeks = us.groupby("week").agg(n=("symbol", "size"), start=("day0", "min")).reset_index()
    first = us.groupby("symbol")["day0"].min()
    rets = spx["Close"].pct_change()
    recs = []
    for w in weeks.itertuples():
        monday = w.start - pd.Timedelta(days=w.start.weekday())
        active = int((first <= monday).sum())
        seg = rets[(rets.index >= monday) & (rets.index < monday + pd.Timedelta(days=7))].dropna()
        if len(seg) < 3 or active < 5:
            continue
        rec = {"week": w.week, "density": w.n / active, "n": w.n, "rv": float(seg.std(ddof=1) * np.sqrt(252))}
        if vix is not None:
            v = vix["Close"]
            cur = v[(v.index >= monday) & (v.index < monday + pd.Timedelta(days=7))]
            prev = v[v.index < monday]
            if len(cur) and len(prev):
                rec["vix_level"] = float(cur.mean())
                rec["vix_change"] = float(cur.iloc[-1] / prev.iloc[-1] - 1)
        recs.append(rec)
    d = pd.DataFrame(recs)
    if len(d) < 20:
        return insufficient(len(d), 20, "semaines")
    rows, pv = [], {}
    for label, col in (("Volatilité réalisée du S&P 500 (annualisée)", "rv"), ("Niveau moyen du VIX", "vix_level"), ("Variation du VIX sur la semaine", "vix_change")):
        if col in d:
            rho, pval, n = spearman(d["density"], d[col])
            rows.append([label, n, rho, pval])
            pv[f"g.density.{col}"] = pval
    return ok([table("Densité des annonces et indice (corrélation de Spearman sur les semaines)", ["Mesure", "Semaines", "ρ", "p"], rows,
                     ["str", "int", "num3", "p"], n_col=1,
                     note="Densité = annonces de la semaine / titres déjà suivis cette semaine-là (corrige la croissance de l'univers). "
                          "Une saison dense coïncide avec l'actualité macro du trimestre : corrélation, pas causalité.")],
              len(d), pvalues=pv)


# ------------------------------------------------------------------------------------------------------------------ H

def market_state(ctx: Ctx) -> pd.DataFrame:
    """Régime HMM (calme / normal / stress) de l'indice local et tercile du VIX AVANT la réaction, par événement du panel complet."""
    if "market_state" in ctx.memo:
        return ctx.memo["market_state"]
    from patrick.cache_manager import LocalCache
    from patrick.features.regime_detection import detect_regime
    full = ctx.full.frame
    cache = LocalCache()
    labels: dict[str, pd.Series] = {}
    out = pd.DataFrame({"i": full["i"], "regime": np.nan, "vix_level": np.nan, "vix_t": np.nan})
    out["regime"] = out["regime"].astype(object)
    out["vix_t"] = out["vix_t"].astype(object)
    benches = {}
    for sym in full["symbol"].unique():
        benches[sym] = ctx.prices.benchmark(sym)[0]
    for bench in sorted({b for b in benches.values() if b}):
        frame = ctx.prices.raw(bench)
        if frame is None or len(frame) < 300:
            continue
        key = f"earn_regime_{bench.replace('^', 'IDX_').replace('.', '_')}_{frame.index[-1].date()}"
        cached = cache.load_dataframe(key, max_age_days=30)
        if cached is not None and "regime" in cached:
            labels[bench] = cached["regime"].astype(object)
            continue
        try:
            res = detect_regime(frame["Close"], n_states=2)
            ser = res.regime.astype(object)
            labels[bench] = ser
            cache.save_dataframe(key, pd.DataFrame({"regime": ser.astype(str)}), max_age_days=30)
        except Exception as exc:  # noqa: BLE001 -- un HMM qui ne converge pas ne doit pas faire échouer l'étude
            log.info("HMM indisponible pour %s : %s", bench, exc)
            continue
    for k, row in full.iterrows():
        ser = labels.get(benches.get(row["symbol"], ""))
        if ser is not None:
            val = ser.loc[:row["day0"] - pd.Timedelta(days=1)]
            val = val[val.astype(str).isin(["calme", "normal", "stress"])]
            if len(val):
                out.at[k, "regime"] = val.iloc[-1]
    vix = ctx.prices.raw("^VIX")
    if vix is not None and len(vix) > 300:
        v = vix["Close"]
        q33 = v.expanding(min_periods=250).quantile(0.33).shift(1)
        q67 = v.expanding(min_periods=250).quantile(0.67).shift(1)
        for k, row in full.iterrows():
            prev = v[v.index < row["day0"]]
            if len(prev) and np.isfinite(q33.loc[prev.index[-1]]):
                lvl = float(prev.iloc[-1])
                out.at[k, "vix_level"] = lvl
                out.at[k, "vix_t"] = "bas" if lvl <= q33.loc[prev.index[-1]] else "haut" if lvl >= q67.loc[prev.index[-1]] else "moyen"
    ctx.memo["market_state"] = out.set_index("i")
    return ctx.memo["market_state"]


H_STATS = {"z_abs": "Amplitude en σ quotidiens", "abs_car": "|CAR|", "car": "CAR signé", "vol0": "Volume anormal J0", "run_up": "Run-up"}


@study("h_regimes", "H", "Régimes de marché (HMM et VIX)",
       "Les statistiques conditionnées au régime calme / normal / stress et aux terciles du VIX : l'amplitude grandit-elle en stress ?",
       needs=("prices",), heavy=True,
       params=(Param("stat", "choice", "z_abs", "Statistique", choices=tuple(H_STATS)),))
def h_regimes(ctx: Ctx, p: dict) -> dict:
    state = market_state(ctx)
    df = ctx.df.merge(state, left_on="i", right_index=True, how="left", suffixes=("", "_s"))
    if df["regime"].notna().sum() < 12 and df["vix_t"].notna().sum() < 12:
        return unavailable("Régimes indisponibles (prix de l'indice local ou du VIX absents).", "prices")
    blocks, pv_raw = [], {}
    for name, col, order, ref in (("Régime HMM (indice local, avant la réaction)", "regime", ["calme", "normal", "stress"], "calme"),
                                  ("Tercile du VIX (quantiles expansifs, point-in-time)", "vix_t", ["bas", "moyen", "haut"], "bas")):
        sub = df.dropna(subset=[col, p["stat"]])
        if len(sub) < 12:
            continue
        rows = []
        for lvl in order:
            g = sub[sub[col] == lvl]
            if len(g):
                rows.append([lvl, len(g), float(g[p["stat"]].mean()), float(g[p["stat"]].median()), float(g["car"].mean()), float((g["car"] > 0).mean())])
        blocks.append(table(name, ["Niveau", "N", f"{H_STATS[p['stat']]} (moyenne)", "Médiane", "CAR moyen", "P(hausse)"], rows,
                            ["str", "int", "num3" if p["stat"] != "abs_car" else "pct", "num3" if p["stat"] != "abs_car" else "pct", "pct", "pct0"], n_col=1))
        base = sub[sub[col] == ref][p["stat"]]
        for lvl in order:
            if lvl != ref and (sub[col] == lvl).sum() >= 5:
                pv_raw[f"h.{col}.{lvl}_vs_{ref}.{p['stat']}"] = mann_whitney(sub[sub[col] == lvl][p["stat"]], base)
        pv_raw[f"h.{col}.kruskal.{p['stat']}"] = kruskal([sub[sub[col] == lvl][p["stat"]].to_numpy() for lvl in order])
    if not blocks:
        return insufficient(len(df), 12)
    bh = benjamini_hochberg({k: v for k, v in pv_raw.items() if np.isfinite(v)}, alpha=0.10)
    contrast = [[k.replace("h.", ""), v["p_value"], v["adjusted_p_value"], "oui" if v["significant"] else "non"] for k, v in bh["results"].items()]
    blocks.append(table("Tests d'interaction (Mann-Whitney contre la modalité de référence ; correction FDR de Benjamini-Hochberg)",
                        ["Contraste", "p brut", "q (BH, 10 %)", "Survit au FDR"], contrast, ["str", "p", "p", "str"],
                        note="Les paramètres du HMM sont estimés sur tout l'historique (comme la page Synthèse) ; seule la probabilité d'état est "
                             "filtrée de façon causale. Le régime d'un événement est celui connu à la séance précédant la réaction."))
    return ok(blocks, len(df), pvalues=pv_raw, rel=rel_for(ctx, df, p["stat"]))


# ------------------------------------------------------------------------------------------------------------------ I

def _bins(s: pd.Series, labels: list[str]) -> pd.Series:
    s = pd.to_numeric(s, errors="coerce")
    try:
        return pd.qcut(s, len(labels), labels=labels, duplicates="drop")
    except ValueError:
        return pd.Series(np.nan, index=s.index)


@study("i_structure", "I", "Amplitude selon la taille, le bêta, le secteur et le style",
       "Amplitude de la réaction par taille, bêta, momentum, valeur, qualité, secteur, pays et devise.",
       params=(Param("target", "choice", "z_abs", "Mesure d'amplitude", choices=("z_abs", "abs_car")),))
def i_structure(ctx: Ctx, p: dict) -> dict:
    df = ctx.df.copy()
    if len(df) < 20:
        return insufficient(len(df), 20)
    ins = ctx.full.instruments
    df["pb"] = df["symbol"].map(lambda s: ins.get(s, {}).get("priceToBook"))
    df["roe"] = df["symbol"].map(lambda s: ins.get(s, {}).get("returnOnEquity"))
    q5, q3 = ["Q1 (petit)", "Q2", "Q3", "Q4", "Q5 (grand)"], ["bas", "moyen", "haut"]
    df["Taille (volume en valeur, point-in-time)"] = _bins(df["dollar_vol"], q5)
    df["Bêta (point-in-time)"] = _bins(df["beta"], q3)
    df["Momentum [−250, −30] (point-in-time)"] = _bins(df["mom_pre"], q3)
    df["Valeur : P/B (instantané actuel)"] = _bins(df["pb"], q3)
    df["Qualité : ROE (instantané actuel)"] = _bins(df["roe"], q3)
    factors = ["Taille (volume en valeur, point-in-time)", "Bêta (point-in-time)", "Momentum [−250, −30] (point-in-time)",
               "Valeur : P/B (instantané actuel)", "Qualité : ROE (instantané actuel)", "sector", "country", "currency"]
    blocks, pv = [], {}
    for f in factors:
        sub = df.dropna(subset=[f, p["target"]])
        if sub[f].nunique() < 2 or len(sub) < 15:
            continue
        rows = [[str(k), len(g), float(g[p["target"]].mean()), float(g[p["target"]].median())] for k, g in sub.groupby(f, observed=True) if len(g) >= 3]
        if len(rows) < 2:
            continue
        pv[f"i.{f}"] = kruskal([g[p["target"]].to_numpy() for _, g in sub.groupby(f, observed=True)])
        label = f if f not in ("sector", "country", "currency") else {"sector": "Secteur", "country": "Pays (place de cotation)", "currency": "Devise"}[f]
        blocks.append(table(label, ["Modalité", "N", "Moyenne", "Médiane"], rows, ["str", "int", "num3" if p["target"] == "z_abs" else "pct",
                                                                                     "num3" if p["target"] == "z_abs" else "pct"], n_col=1,
                            note=f"Kruskal-Wallis : p = {pv[f'i.{f}']:.3f}" if np.isfinite(pv[f"i.{f}"]) else ""))
    if not blocks:
        return insufficient(len(df), 15)
    blocks.append(note("Valeur et qualité sont des instantanés ACTUELS (Yahoo n'en donne pas l'historique) : lecture indicative pour les annonces "
                       "anciennes. Taille, bêta et momentum sont mesurés avant chaque annonce.", "warning"))
    return ok(blocks, len(df), pvalues=pv, rel=rel_for(ctx, df, p["target"]))


@study("i_currency", "I", "Effet de la devise",
       "Lien entre le mouvement de la devise le jour de la réaction et la réaction d'un titre étranger.", needs=("prices",))
def i_currency(ctx: Ctx, p: dict) -> dict:
    df = ctx.df[ctx.df["currency"] != "USD"]
    if len(df) < 15:
        return insufficient(len(df), 15, "annonces hors dollar")
    rows, recs = [], []
    for ccy, g in df.groupby("currency"):
        fx = ctx.prices.raw(f"{ccy}USD=X")
        if fx is None:
            continue
        ret = fx["Close"].pct_change()
        for r in g.itertuples():
            if r.day0 in ret.index and np.isfinite(ret.loc[r.day0]):
                recs.append({"ccy": ccy, "fx": float(ret.loc[r.day0]), "car": r.car, "abs": r.abs_car})
    d = pd.DataFrame(recs)
    if len(d) < 15:
        return insufficient(len(d), 15, "annonces avec cours de change")
    pv = {}
    for ccy, g in d.groupby("ccy"):
        r1, p1, n = spearman(g["fx"], g["car"])
        r2, p2, _ = spearman(g["fx"].abs(), g["abs"])
        rows.append([ccy, n, r1, p1, r2, p2])
        pv[f"i.fx.{ccy}.sign"], pv[f"i.fx.{ccy}.amp"] = p1, p2
    return ok([table("Devise contre dollar le jour J0 et réaction du titre", ["Devise", "N", "ρ (mouvement du change → sens)", "p",
                                                                                  "ρ (|change| → amplitude)", "p"], rows,
                     ["str", "int", "num3", "p", "num3", "p"], n_col=1,
                     note="Le rendement anormal est en devise locale : un lien avec le change reflète une réaction commune (exportateurs), pas un "
                          "effet de conversion. La conversion apparaît dans la carte « Ligne locale contre ADR » (J).")],
              len(d), pvalues=pv)


@study("i_ipo", "I", "Effet introduction récente",
       "Amplitude des premières annonces après la cotation contre les suivantes (utile pour Figma, Arm, Oklo).",
       params=(Param("first_n", "int", 4, "Nombre de premières annonces", lo=1, hi=8), Param("years", "float", 3.0, "Ancienneté maximale (années)", lo=0.5, hi=10)))
def i_ipo(ctx: Ctx, p: dict) -> dict:
    df = ctx.df.dropna(subset=["z_abs"]).copy()
    if len(df) < 20:
        return insufficient(len(df), 20)
    age = (df["day0"] - df["first_trade"]).dt.days / 365.25
    df["recent"] = (df["event_no"] <= p["first_n"]) & (age.fillna(99) <= p["years"])
    early, later = df[df["recent"]], df[~df["recent"]]
    if len(early) < 5 or len(later) < 5:
        return insufficient(len(early), 5, "premières annonces d'introductions récentes")
    pval = mann_whitney(early["z_abs"], later["z_abs"])
    return ok([table("Premières annonces contre les suivantes", ["Groupe", "N", "Amplitude moyenne (σ)", "Médiane", "|CAR| moyen"],
                     [["Premières annonces (introduction récente)", len(early), float(early["z_abs"].mean()), float(early["z_abs"].median()), float(early["abs_car"].mean())],
                      ["Suivantes", len(later), float(later["z_abs"].mean()), float(later["z_abs"].median()), float(later["abs_car"].mean())]],
                     ["str", "int", "num2", "num2", "pct"], n_col=1, note=f"Mann-Whitney : p = {pval:.3f}. La date de cotation est celle du premier cours Yahoo."),
               ], len(df), pvalues={"i.ipo.mannwhitney": pval}, rel=rel_for(ctx, early, "z_abs"))

