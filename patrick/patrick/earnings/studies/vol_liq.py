"""Volatilité autour de l'événement (§3.B), liquidité et microstructure (§3.C), anticipation (§3.E).

Les études d'options (B : mouvement implicite, backtest de straddle) n'ont AUCUN historique gratuit. Elles lisent donc les
instantanés quotidiens (`snapshots.py`, kind `options`) pris avant chaque annonce et les apparient au mouvement réalisé une fois
la réaction passée : vides aujourd'hui, utilisables après quelques trimestres d'accumulation, et le disent.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from patrick.earnings import store
from patrick.earnings.config import PATH_LO
from patrick.earnings.engine import arr, rel_index
from patrick.earnings.studies.base import (
    Ctx,
    Param,
    cluster_ols,
    insufficient,
    kv,
    line,
    note,
    ok,
    rel_for,
    spearman,
    study,
    table,
    unavailable,
)


def _wilcoxon(x) -> float:
    a = np.asarray(x, dtype=float)
    a = a[np.isfinite(a)]
    a = a[a != 0]
    if len(a) < 6:
        return np.nan
    return float(stats.wilcoxon(a).pvalue)


def _mean_path(rows: list[dict], key: str, transform=None) -> np.ndarray:
    mat = np.array([arr(r, key) for r in rows])
    if transform:
        mat = transform(mat, rows)
    with np.errstate(invalid="ignore"):
        return np.nanmean(mat, axis=0)


# ------------------------------------------------------------------------------------------------------------- B : volatilité

@study("b_vol_prepost", "B", "Volatilité réalisée avant et après",
       "Montée avant l'annonce, chute après : l'analogue réalisé du « vol crush » (chute de la volatilité implicite).",
       needs=("prices",))
def b_vol_prepost(ctx: Ctx, p: dict) -> dict:
    df = ctx.df
    rows = ctx.panel.payloads()
    if len(rows) < 8:
        return insufficient(len(rows), 8)
    rv = np.array([arr(r, "rv") for r in rows])
    est = np.array([r["rv_est"] for r in rows], dtype=float)[:, None]
    with np.errstate(invalid="ignore", divide="ignore"):
        rel_vol = np.sqrt(rv / est)
    mean_path = np.nanmean(rel_vol, axis=0)
    days = list(range(PATH_LO, 21))
    wins = [("Avant [−5, −1]", -5, -1), ("Réaction [0, +1]", 0, 1), ("Après [+2, +5]", 2, 5), ("Retour [+6, +20]", 6, 20)]
    out = []
    for name, a, b in wins:
        seg = rel_vol[:, rel_index(a):rel_index(b) + 1]
        out.append([name, int(np.isfinite(seg).any(axis=1).sum()), float(np.nanmean(seg)), float(np.nanmedian(seg))])
    pre = np.nanmean(rel_vol[:, rel_index(-5):rel_index(-1) + 1], axis=1)
    post = np.nanmean(rel_vol[:, rel_index(2):rel_index(5) + 1], axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        crush = np.log(post / pre)
    pv = _wilcoxon(crush)
    ratio = float(np.nanmedian(post / pre))
    return ok([table("Volatilité de Parkinson relative à la fenêtre d'estimation (1 = habituelle)",
                     ["Période", "N", "Moyenne", "Médiane"], out, ["str", "int", "num2", "num2"], n_col=1),
               kv("Chute après annonce", [("Médiane de (vol [+2,+5] / vol [−5,−1])", ratio, "num2"),
                                          ("p (Wilcoxon sur le log du rapport)", pv, "p")]),
               line("Volatilité relative autour de J0", days, [{"name": "σ relative", "y": [float(v) for v in mean_path[:len(days)]]}],
                    "séances relatives à J0", "num2")],
              len(rows), pvalues={"b.volprepost.wilcoxon": pv}, rel=rel_for(ctx, df, "car"))


@study("b_har_event", "B", "HAR-RV avec variable d'annonce",
       "Régression de la volatilité réalisée sur ses moyennes passées (jour, semaine, mois) plus des indicatrices d'événement.",
       needs=("prices",), heavy=True,
       params=(Param("max_symbols", "int", 30, "Titres au maximum", lo=3, hi=200),
               Param("years", "int", 6, "Années d'historique", lo=1, hi=20)))
def b_har_event(ctx: Ctx, p: dict) -> dict:
    df = ctx.df
    symbols = list(df["symbol"].value_counts().index[: p["max_symbols"]])
    ys, xs, cl = [], [], []
    for sym in symbols:
        sp = ctx.prices.prices(sym)
        if sp is None:
            continue
        rv = pd.Series(sp.rv, index=sp.idx)
        rv = rv.where(rv > 1e-10)
        lrv = np.log(rv)
        d1 = lrv.shift(1)
        d5 = np.log(rv.rolling(5, min_periods=4).mean().shift(1))
        d22 = np.log(rv.rolling(22, min_periods=15).mean().shift(1))
        pos = pd.Series(np.arange(len(sp.idx)), index=sp.idx)
        dummies = {k: np.zeros(len(sp.idx)) for k in ("pre", "react", "post")}
        for d0 in df.loc[df["symbol"] == sym, "day0"]:
            if d0 not in pos.index:
                continue
            i0 = int(pos[d0])
            dummies["pre"][max(i0 - 3, 0):i0] = 1
            dummies["react"][i0:i0 + 2] = 1
            dummies["post"][i0 + 2:i0 + 6] = 1
        cutoff = sp.idx[-1] - pd.Timedelta(days=365 * p["years"])
        frame = pd.DataFrame({"y": lrv, "d1": d1, "d5": d5, "d22": d22, **{k: v for k, v in dummies.items()}}, index=sp.idx)
        frame = frame[frame.index >= cutoff].dropna()
        ys.append(frame["y"].to_numpy())
        xs.append(frame[["d1", "d5", "d22", "pre", "react", "post"]].to_numpy())
        cl.extend([sym] * len(frame))
    if not ys:
        return unavailable("aucun cours disponible pour estimer la volatilité réalisée", "prices")
    y, X = np.concatenate(ys), np.vstack(xs)
    res = cluster_ols(y, np.column_stack([np.ones(len(y)), X]), cl, ["const", "jour (t−1)", "semaine", "mois", "avant [−3,−1]",
                                                                       "réaction [0,+1]", "après [+2,+5]"])
    if not res["coef"]:
        return insufficient(res["n"], 50, "observations")
    rows = [[k, res["coef"][k], res["t"][k], res["p"][k], (float(np.exp(res["coef"][k]) - 1) if "[" in k else None)]
            for k in res["coef"]]
    pv = {f"b.har.{k}": res["p"][k] for k in ("avant [−3,−1]", "réaction [0,+1]", "après [+2,+5]")}
    return ok([table("HAR-RV : log de la variance de Parkinson", ["Terme", "Coefficient", "t (groupé par titre)", "p", "Effet sur la variance"],
                     rows, ["str", "num3", "num2", "p", "pct"]),
               kv("Ajustement", [("R²", res["r2"], "num3"), ("Observations", res["n"], "int"), ("Titres", len(symbols), "int")]),
               note("Variance journalière estimée par l'amplitude haut-bas (Parkinson), pas par des données intrajournalières. "
                    "L'effet « réaction » donne de combien la variance d'un jour d'annonce dépasse ce que prédit le HAR seul.")],
              len(y), pvalues=pv, rel=rel_for(ctx, df, "car"))


def _matched_option_pairs(ctx: Ctx) -> pd.DataFrame:
    snaps = store.snapshots(ctx.conn, kind="options")
    df = ctx.df
    recs = []
    for s in snaps:
        pl = s["payload"]
        ann = pl.get("target_ann_date")
        if not ann or not pl.get("straddle_pct"):
            continue
        hit = df[(df["symbol"] == s["symbol"]) & (df["ann_date"] == pd.Timestamp(ann))]
        if hit.empty or s["snap_date"] >= str(hit["day0"].iloc[0].date()):
            continue                                           # instantané postérieur à la réaction : inutilisable
        recs.append({"symbol": s["symbol"], "ann_date": ann, "snap_date": s["snap_date"], "implied": float(pl["straddle_pct"]),
                     "realized": float(abs(hit["raw"].iloc[0])), "day0": hit["day0"].iloc[0]})
    out = pd.DataFrame(recs, columns=["symbol", "ann_date", "snap_date", "implied", "realized", "day0"])
    return out.sort_values("snap_date").drop_duplicates(["symbol", "ann_date"], keep="last") if len(out) else out


@study("b_implied_realized", "B", "Mouvement implicite contre réalisé",
       "Straddle ATM / cours (mouvement absolu attendu) face au mouvement réalisé ; prime de risque de volatilité d'événement.",
       needs=("snapshots",))
def b_implied_realized(ctx: Ctx, p: dict) -> dict:
    n_snap = store.snapshot_counts(ctx.conn).get("options", 0)
    pairs = _matched_option_pairs(ctx)
    if len(pairs) < 8:
        return unavailable(f"Pas d'options historiques gratuites : l'instantané de chaîne d'options est pris chaque jour avant l'annonce "
                           f"puis apparié au mouvement réalisé. Accumulation en cours : {n_snap} instantané(s), {len(pairs)} apparié(s), "
                           "8 requis.", "snapshots")
    pairs["ratio"] = pairs["realized"] / pairs["implied"]
    pairs["vrp"] = pairs["implied"] - pairs["realized"]
    hist = ctx.full.frame[["symbol", "ann_date", "hist_mean_abs_car"]].assign(ann_date=lambda d: d["ann_date"].astype(str))
    pairs = pairs.assign(ann_date=pairs["ann_date"].astype(str)).merge(hist, on=["symbol", "ann_date"], how="left")
    both = pairs.dropna(subset=["hist_mean_abs_car"])
    baselines = None
    if len(both) >= 8:
        baselines = table("Prévoir le mouvement absolu réalisé (baselines du modèle d'amplitude)", ["Prédicteur", "N", "Erreur absolue moyenne"],
                          [["Mouvement implicite (straddle ATM)", len(both), float((both["realized"] - both["implied"]).abs().mean())],
                           ["Moyenne passée du titre", len(both), float((both["realized"] - both["hist_mean_abs_car"]).abs().mean())]],
                          ["str", "int", "pct"], n_col=1,
                          note="Le mouvement implicite est la baseline que le modèle d'amplitude doit battre dès que les instantanés sont assez nombreux.")
    rows = [[s, len(g), float(g["implied"].mean()), float(g["realized"].mean()), float(g["ratio"].median()), float(g["vrp"].mean())]
            for s, g in pairs.groupby("symbol")]
    pv = _wilcoxon(pairs["vrp"])
    return ok([kv("Ensemble", [("Événements appariés", len(pairs), "int"), ("Mouvement implicite moyen", pairs["implied"].mean(), "pct"),
                               ("Mouvement réalisé moyen", pairs["realized"].mean(), "pct"),
                               ("Rapport réalisé / implicite (médiane)", pairs["ratio"].median(), "num2"),
                               ("Prime de risque de volatilité (implicite − réalisé)", pairs["vrp"].mean(), "pct"),
                               ("p (Wilcoxon, prime ≠ 0)", pv, "p")]),
               table("Par titre", ["Titre", "N", "Implicite", "Réalisé", "Réalisé / implicite", "Prime"], rows,
                     ["str", "int", "pct", "pct", "num2", "pct"], n_col=1),
               *([baselines] if baselines else []),
               note("Le straddle inclut les jours entre l'annonce et l'échéance : il surestime le mouvement attendu de l'annonce seule.")],
              len(pairs), pvalues={"b.implied.vrp": pv}, rel=rel_for(ctx, ctx.df, "car"))


@study("b_straddle_backtest", "B", "Backtest de straddle (avant l'annonce)",
       "Long ou short du straddle ATM acheté la veille : rentabilité nette du mouvement implicite (approximation par le mouvement réalisé).",
       needs=("snapshots",),
       params=(Param("cost_pct", "float", 5.0, "Coût aller-retour (% du straddle)", lo=0, hi=50),))
def b_straddle_backtest(ctx: Ctx, p: dict) -> dict:
    pairs = _matched_option_pairs(ctx)
    if len(pairs) < 20:
        return unavailable(f"Exige des options historiques (payantes). Mode prospectif : {len(pairs)} événement(s) apparié(s) sur 20 requis.",
                           "snapshots")
    cost = p["cost_pct"] / 100.0
    long_ret = (pairs["realized"] - pairs["implied"]) / pairs["implied"] - cost
    short_ret = (pairs["implied"] - pairs["realized"]) / pairs["implied"] - cost
    from patrick.validation.dsr import deflated_sharpe_ratio
    rows = []
    for name, r in (("Long straddle", long_ret), ("Short straddle", short_ret)):
        d = deflated_sharpe_ratio(r.to_numpy(), n_trials=2, periods_per_year=max(int(len(r) / max((pairs["day0"].max() - pairs["day0"].min()).days / 365.25, 0.25)), 1))
        rows.append([name, len(r), float(r.mean()), float((r > 0).mean()), d.get("sr_annualized"), d.get("p_value")])
    return ok([table("Rendement net par straddle (en % du prix du straddle)", ["Stratégie", "N", "Moyenne", "Taux de gain", "Sharpe annualisé",
                                                                              "p (DSR, 2 essais)"], rows,
                     ["str", "int", "pct", "pct0", "num2", "p"], n_col=1,
                     note="Approximation : le gain est (mouvement réalisé − prix du straddle), sans theta ni écart de volatilité implicite entre J−1 et J.")],
              len(pairs), pvalues={"b.straddle.short": rows[1][5]})


# ---------------------------------------------------------------------------------------------------------- C : liquidité

@study("c_abnormal_volume", "C", "Volume anormal et rotation",
       "Volume rapporté à sa moyenne sur la fenêtre d'estimation, jour par jour autour de J0.", needs=("prices",))
def c_abnormal_volume(ctx: Ctx, p: dict) -> dict:
    df = ctx.df.dropna(subset=["vol0"])
    rows = ctx.panel.payloads(df)
    if len(rows) < 8:
        return insufficient(len(rows), 8)
    mat = np.array([arr(r, "vol_ratio") for r in rows])
    days = list(range(-5, 11))
    out = [[f"J{d:+d}", int(np.isfinite(mat[:, rel_index(d)]).sum()), float(np.nanmean(mat[:, rel_index(d)])),
            float(np.nanmedian(mat[:, rel_index(d)]))] for d in days]
    with np.errstate(invalid="ignore", divide="ignore"):
        lift = np.log(df["vol0"].to_numpy() / df["vol_pre"].to_numpy())
    pv = _wilcoxon(lift)
    ins = ctx.panel.instruments
    turnover = []
    for r in rows:
        shares = ins.get(r["symbol"], {}).get("sharesOutstanding")
        v0 = arr(r, "vol_ratio")[rel_index(0)]
        if shares and r.get("vol_mean_est") and np.isfinite(v0):
            turnover.append(v0 * r["vol_mean_est"] / shares)
    return ok([table("Volume relatif (1 = moyenne d'estimation)", ["Jour", "N", "Moyenne", "Médiane"], out, ["str", "int", "num2", "num2"], n_col=1),
               line("Volume anormal autour de J0", days, [{"name": "volume relatif", "y": [r[2] for r in out]}], "séances relatives à J0", "num2"),
               kv("Jour de réaction", [("Volume J0 / volume [−5,−1] (médiane)", float(np.nanmedian(df["vol0"] / df["vol_pre"])), "num2"),
                                       ("p (Wilcoxon sur le log)", pv, "p"),
                                       ("Rotation J0 médiane (volume / actions en circulation)", float(np.median(turnover)) if turnover else None, "pct")]),
               note("La rotation utilise le nombre d'actions ACTUEL (Yahoo n'en donne pas l'historique) : approximation pour les annonces anciennes.")],
              len(rows), pvalues={"c.volume.wilcoxon": pv}, rel=rel_for(ctx, df, "vol0"))


def _ratio_study(ctx: Ctx, ev_col: str, pre_col: str, est_col: str, label: str, key: str) -> dict:
    df = ctx.df.dropna(subset=[ev_col, est_col])
    df = df[df[est_col] > 0]
    if len(df) < 8:
        return insufficient(len(df), 8)
    r_ev, r_pre = df[ev_col] / df[est_col], df[pre_col] / df[est_col]
    pv_ev = _wilcoxon(np.log(r_ev.replace(0, np.nan)))
    pv_pre = _wilcoxon(np.log(r_pre.replace(0, np.nan)))
    return ok([table(f"{label} relatif à la fenêtre d'estimation (1 = habituel)", ["Période", "N", "Médiane", "Moyenne", "p (Wilcoxon sur le log)"],
                     [["Avant [−5, −1]", int(r_pre.notna().sum()), float(r_pre.median()), float(r_pre.mean()), pv_pre],
                      ["Réaction (jours J0 et J+1)", int(r_ev.notna().sum()), float(r_ev.median()), float(r_ev.mean()), pv_ev]],
                     ["str", "int", "num2", "num2", "p"], n_col=1)],
              len(df), pvalues={f"c.{key}.pre": pv_pre, f"c.{key}.event": pv_ev}, rel=rel_for(ctx, df, ev_col))


@study("c_amihud", "C", "Illiquidité d'Amihud", "|rendement| / volume en valeur : dégradation de la liquidité autour de l'annonce.", needs=("prices",))
def c_amihud(ctx: Ctx, p: dict) -> dict:
    return _ratio_study(ctx, "am_ev", "am_pre", "am_est", "Illiquidité d'Amihud", "amihud")


@study("c_corwin_schultz", "C", "Spread de Corwin-Schultz",
       "Spread bid-ask estimé à partir des plus hauts et plus bas journaliers : proxy sans carnet d'ordres.", needs=("prices",))
def c_corwin_schultz(ctx: Ctx, p: dict) -> dict:
    res = _ratio_study(ctx, "cs_ev", "cs_pre", "cs_est", "Spread de Corwin-Schultz", "cs")
    if res["status"] == "ok":
        res["blocks"].append(note("Estimateur biaisé à la baisse sur les titres très liquides (spread proche de 0 : valeurs négatives ramenées à 0)."))
    return res


@study("c_volume_predicts_move", "C", "Le volume d'avant prédit-il l'amplitude ?",
       "Lien entre le volume anormal des 5 séances précédentes et l'amplitude de la réaction.", needs=("prices",))
def c_volume_predicts_move(ctx: Ctx, p: dict) -> dict:
    df = ctx.df.dropna(subset=["vol_pre", "z_abs", "abs_car"])
    if len(df) < 12:
        return insufficient(len(df), 12)
    out, pv = [], {}
    for label, col in (("Amplitude en σ quotidiens (|CAR|/σ)", "z_abs"), ("|CAR|", "abs_car")):
        rho, pval, n = spearman(df["vol_pre"], df[col])
        out.append([label, n, rho, pval])
        pv[f"c.volpred.{col}"] = pval
    sub = df.dropna(subset=["hist_mean_abs_z"])
    extra = None
    if len(sub) >= 20:
        res = cluster_ols(np.log(sub["z_abs"].clip(lower=1e-4)), np.column_stack([np.ones(len(sub)), np.log(sub["vol_pre"].clip(lower=1e-3)),
                                                                                     np.log(sub["hist_mean_abs_z"].clip(lower=1e-4))]),
                          sub["week"], ["const", "log volume pré", "log amplitude historique"])
        if res["coef"]:
            extra = table("Contrôle par l'amplitude historique du titre (log-log, erreurs groupées par semaine)", ["Terme", "Coefficient", "t", "p"],
                          [[k, res["coef"][k], res["t"][k], res["p"][k]] for k in res["coef"]], ["str", "num3", "num2", "p"])
            pv["c.volpred.controlled"] = res["p"]["log volume pré"]
    blocks = [table("Volume pré-annonce → amplitude", ["Cible", "N", "ρ de Spearman", "p"], out, ["str", "int", "num3", "p"], n_col=1)]
    if extra:
        blocks.append(extra)
    return ok(blocks, len(df), pvalues=pv, rel=rel_for(ctx, df, "z_abs"))


# ---------------------------------------------------------------------------------------------------------- E : anticipation

@study("e_runup", "E", "Run-up pré-annonce", "CAR sur la fenêtre de run-up et son pouvoir prédictif sur la réaction.")
def e_runup(ctx: Ctx, p: dict) -> dict:
    df = ctx.df.dropna(subset=["run_up", "car"])
    if len(df) < 12:
        return insufficient(len(df), 12)
    rho, pval, _n = spearman(df["run_up"], df["car"])
    rho_abs, p_abs, _ = spearman(df["run_up"].abs(), df["z_abs"])
    q = pd.qcut(df["run_up"], 4, labels=["Q1 (baisse)", "Q2", "Q3", "Q4 (hausse)"], duplicates="drop")
    rows = [[str(k), len(g), float(g["run_up"].mean()), float(g["car"].mean()), float((g["car"] > 0).mean()), float(g["z_abs"].mean())]
            for k, g in df.groupby(q, observed=True)]
    a, b = ctx.cfg.run_up
    return ok([kv(f"Run-up [{a:+d}, {b:+d}]", [("Run-up moyen", df["run_up"].mean(), "pct"), ("ρ run-up → réaction (sens)", rho, "num3"),
                                               ("p", pval, "p"), ("ρ |run-up| → amplitude", rho_abs, "num3"), ("p", p_abs, "p")]),
               table("Réaction par quartile de run-up", ["Quartile", "N", "Run-up moyen", "Réaction moyenne", "P(hausse)", "Amplitude (σ)"], rows,
                     ["str", "int", "pct", "pct", "pct0", "num2"], n_col=1,
                     note="Un run-up fort signifie en partie des attentes déjà intégrées : une réaction plus faible ou de sens inverse. "
                          "Une fuite d'information donnerait au contraire ρ > 0.")],
              len(df), pvalues={"e.runup.sign": pval, "e.runup.amplitude": p_abs}, rel=rel_for(ctx, df, "run_up"))


@study("e_short_interest", "E", "Vendeurs à découvert avant l'annonce",
       "Part du flottant vendue à découvert et variation, relevées par instantané (Yahoo : valeur du jour, publication différée).",
       needs=("snapshots",))
def e_short_interest(ctx: Ctx, p: dict) -> dict:
    snaps = store.snapshots(ctx.conn, kind="short")
    if not snaps:
        return unavailable("Aucun instantané de vendeurs à découvert. Yahoo ne publie que la valeur du jour, avec un décalage de publication "
                           "(souvent deux semaines) et hors États-Unis très partiellement : l'historique se construit par instantanés quotidiens.",
                           "snapshots")
    by_sym: dict[str, list] = {}
    for s in snaps:
        by_sym.setdefault(s["symbol"], []).append(s)
    rows = []
    for sym, lst in sorted(by_sym.items()):
        last, first = lst[-1]["payload"], lst[0]["payload"]
        pf, pf0 = last.get("percent_float"), first.get("percent_float")
        rows.append([sym, len(lst), pf, (pf - pf0) if (pf is not None and pf0 is not None and len(lst) > 1) else None, last.get("date_short_interest")])
    return ok([table("Vendeurs à découvert (instantanés)", ["Titre", "Instantanés", "% du flottant", "Variation depuis le premier", "Date de publication"],
                     rows, ["str", "int", "pct", "pct", "str"], n_col=1,
                     note="Lien avec la réaction : exploitable quand assez d'annonces auront suivi un instantané (voir la carte « Run-up » pour la méthode).")],
              len(snaps))
