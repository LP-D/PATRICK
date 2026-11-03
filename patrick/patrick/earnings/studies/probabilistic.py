"""Estimation probabilistique et petit échantillon (§3.L), modèle prédictif en panel (§5) et score composite (§4)."""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from patrick.earnings import composite, model
from patrick.earnings.reliability import partial_pooling, reliability
from patrick.earnings.studies.base import (
    Ctx,
    Param,
    bars,
    insufficient,
    kv,
    line,
    note,
    ok,
    study,
    table,
)

N_MIN_MODEL = 60


def _design(ctx: Ctx, use_regime: bool, need_col: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Panel complet (modèle poolé : jamais restreint à un titre), lignes sans la colonne cible écartées, et leurs variables."""
    df = ctx.full.frame
    regime = None
    if use_regime:
        from patrick.earnings.studies.cross import market_state
        regime = df["i"].map(market_state(ctx)["regime"])
        regime.index = df.index
    feats = model.build_features(df, regime)
    keep = df[need_col].notna()
    return df[keep].reset_index(drop=True), feats[keep].reset_index(drop=True)


def _pinball(y: np.ndarray, q_pred: np.ndarray, tau: float) -> float:
    d = y - q_pred
    return float(np.mean(np.maximum(tau * d, (tau - 1) * d)))


@study("l_quantile", "L", "Régression quantile de la réaction",
       "Quantiles conditionnels de l'amplitude (10 %, 50 %, 90 %) selon les variables, plutôt qu'une seule moyenne ; perte pinball hors échantillon.",
       params=(Param("use_regime", "bool", False, "Inclure le régime HMM (plus lent)"),), heavy=True)
def l_quantile(ctx: Ctx, p: dict) -> dict:
    import statsmodels.api as sm
    warnings.filterwarnings("ignore", message="Maximum number of iterations")        # régression quantile : convergence lente sans conséquence
    df, feats = _design(ctx, p["use_regime"], "z_abs")
    if len(df) < N_MIN_MODEL:
        return insufficient(len(df), N_MIN_MODEL)
    y = model.target_amplitude(df)
    folds = model.walk_forward_folds(df["day0"])
    if not folds:
        return insufficient(len(df), N_MIN_MODEL)
    taus = (0.1, 0.5, 0.9)
    preds = {t: [] for t in taus}
    base = {t: [] for t in taus}
    truth = []
    for train, test in folds:
        tr = train[y.iloc[train].notna().to_numpy()]
        Xtr, Xte = model._impute(feats.iloc[tr][model.AMP_FEATURES], feats.iloc[test][model.AMP_FEATURES])
        Xtr1, Xte1 = sm.add_constant(Xtr, has_constant="add"), sm.add_constant(Xte, has_constant="add")
        for t in taus:
            try:
                fit = sm.QuantReg(y.iloc[tr].to_numpy(), Xtr1).fit(q=t, max_iter=500)
                preds[t].append(Xte1 @ fit.params)
            except Exception:  # noqa: BLE001 -- matrice singulière sur un pli : repli sur le quantile inconditionnel
                preds[t].append(np.full(len(test), np.quantile(y.iloc[tr], t)))
            base[t].append(np.full(len(test), np.quantile(y.iloc[tr], t)))
        truth.append(y.iloc[test].to_numpy())
    truth = np.concatenate(truth)
    keep = np.isfinite(truth)
    rows = []
    for t in taus:
        pm, pb = np.concatenate(preds[t])[keep], np.concatenate(base[t])[keep]
        lm, lb = _pinball(truth[keep], pm, t), _pinball(truth[keep], pb, t)
        rows.append([f"{t:.0%}", int(keep.sum()), float((truth[keep] <= pm).mean()), lm, lb, 1 - lm / lb])
    X, _ = model._impute(feats[model.AMP_FEATURES][y.notna()], feats[model.AMP_FEATURES][y.notna()].iloc[:1])
    coefs = {}
    for t in (0.5, 0.9):
        try:
            fit = sm.QuantReg(y[y.notna()].to_numpy(), sm.add_constant(X, has_constant="add")).fit(q=t, max_iter=500)
            coefs[t] = fit.params[1:]
        except Exception:  # noqa: BLE001
            coefs[t] = np.full(len(model.AMP_FEATURES), np.nan)
    coef_rows = [[f, float(coefs[0.5][i]), float(coefs[0.9][i])] for i, f in enumerate(model.AMP_FEATURES)]
    return ok([table("Quantiles prédits, hors échantillon (walk-forward purgé)", ["Quantile", "N test", "Couverture observée", "Perte pinball (modèle)",
                                                                                   "Perte pinball (inconditionnel)", "Gain relatif"], rows,
                     ["str", "int", "pct0", "num3", "num3", "pct"], n_col=1,
                     note="Couverture observée : part des amplitudes réalisées sous le quantile prédit (devrait valoir le niveau nominal). "
                          "Cible : log(|CAR|/σ + 0,1). Un gain relatif ≤ 0 signifie que les variables n'apportent rien."),
               table("Coefficients (variables standardisées, ajustement sur tout l'historique)", ["Variable", "Médiane (50 %)", "Queue haute (90 %)"],
                     coef_rows, ["str", "num3", "num3"])],
              int(keep.sum()), rel=reliability(n=int(keep.sum()), day0=df["day0"], min_events=ctx.cfg.min_events))


@study("l_conformal", "L", "Intervalles de prédiction conformes",
       "Bornes sur l'amplitude attendue sans hypothèse de loi (conformal prediction), évaluées par la couverture empirique et la perte pinball.",
       params=(Param("level", "float", 0.8, "Niveau nominal de l'intervalle", lo=0.5, hi=0.95),), heavy=True)
def l_conformal(ctx: Ctx, p: dict) -> dict:
    df, feats = _design(ctx, False, "z_abs")
    if len(df) < N_MIN_MODEL:
        return insufficient(len(df), N_MIN_MODEL)
    y = model.target_amplitude(df)
    folds = model.walk_forward_folds(df["day0"])
    if not folds:
        return insufficient(len(df), N_MIN_MODEL)
    alpha = 1 - p["level"]
    lo_all, hi_all, true_all = [], [], []
    for train, test in folds:
        tr = train[y.iloc[train].notna().to_numpy()]
        cut = int(len(tr) * 0.7)
        fit_idx, cal_idx = tr[:cut], tr[cut:]
        if len(cal_idx) < 10:
            continue
        Xf, Xc = model._impute(feats.iloc[fit_idx][model.AMP_FEATURES], feats.iloc[cal_idx][model.AMP_FEATURES])
        _, Xt = model._impute(feats.iloc[fit_idx][model.AMP_FEATURES], feats.iloc[test][model.AMP_FEATURES])
        pred_c, m = model._ridge(Xf, y.iloc[fit_idx].to_numpy(), Xc)
        resid = y.iloc[cal_idx].to_numpy() - pred_c
        k = int(np.ceil((len(resid) + 1) * (1 - alpha)))
        q_up = np.sort(np.abs(resid))[min(k, len(resid)) - 1]
        center = m.predict(Xt)
        lo_all.append(center - q_up)
        hi_all.append(center + q_up)
        true_all.append(y.iloc[test].to_numpy())
    if not true_all:
        return insufficient(len(df), N_MIN_MODEL)
    lo, hi, tru = (np.concatenate(a) for a in (lo_all, hi_all, true_all))
    keep = np.isfinite(tru)
    cover = float(((tru[keep] >= lo[keep]) & (tru[keep] <= hi[keep])).mean())
    pin_lo, pin_hi = _pinball(tru[keep], lo[keep], alpha / 2), _pinball(tru[keep], hi[keep], 1 - alpha / 2)
    z_lo, z_hi = np.exp(lo[keep]) - model.OFFSET, np.exp(hi[keep]) - model.OFFSET
    return ok([kv("Intervalle conforme (conformal split, calibré sur les 30 % les plus récents de chaque entraînement)", [
        ("Niveau nominal", p["level"], "pct0"), ("Couverture empirique hors échantillon", cover, "pct0"), ("N test", int(keep.sum()), "int"),
        ("Largeur médiane (en σ quotidiens)", float(np.median(z_hi - np.maximum(z_lo, 0))), "num2"),
        ("Perte pinball (borne basse)", pin_lo, "num3"), ("Perte pinball (borne haute)", pin_hi, "num3")]),
               note("Garantie de couverture valable sous échangeabilité : les événements d'une même semaine sont corrélés et le régime change, "
                    "donc la couverture réelle peut s'écarter du niveau nominal. Elle est mesurée ici, pas supposée.")],
              int(keep.sum()), rel=reliability(n=int(keep.sum()), day0=df["day0"], min_events=ctx.cfg.min_events))


@study("l_shrinkage", "L", "Rétrécissement bayésien empirique (partial pooling)",
       "Le mouvement absolu moyen d'un titre est ramené vers celui de son secteur, d'autant plus que le titre a peu d'annonces.",
       params=(Param("target", "choice", "abs_car", "Mesure", choices=("abs_car", "z_abs")),))
def l_shrinkage(ctx: Ctx, p: dict) -> dict:
    df = ctx.df.dropna(subset=[p["target"]])
    if len(df) < 20:
        return insufficient(len(df), 20)
    by_sym = {s: g[p["target"]].to_numpy() for s, g in df.groupby("symbol")}
    prior = {s: g["sector"].iloc[0] for s, g in df.groupby("symbol")}
    pooled = partial_pooling(by_sym, prior)
    rows = []
    for s, v in sorted(pooled.items(), key=lambda kv_: -kv_[1]["n"]):
        rel = reliability(by_sym[s], min_events=ctx.cfg.min_events)
        rows.append([s, prior[s], v["n"], v["raw"], v["shrunk"], v["prior"], v["weight"], rel["level"]])
    # contrôle hors échantillon : prévoir le mouvement du prochain événement avec la moyenne brute passée ou la moyenne rétrécie
    full = ctx.full.frame.dropna(subset=["z_abs"])
    g = full.dropna(subset=["hist_mean_abs_z", "sector_hist_abs_z"])
    check = None
    if len(g) >= 40:
        within = float(full.groupby("symbol")["z_abs"].var().mean())
        between = max(float(full.groupby("symbol")["z_abs"].mean().var()) - within / max(full.groupby("symbol").size().mean(), 1), 1e-6)
        k = within / between
        w = g["hist_n"] / (g["hist_n"] + k)
        shrunk = w * g["hist_mean_abs_z"] + (1 - w) * g["sector_hist_abs_z"]
        check = table("Contrôle : prévoir l'amplitude (σ quotidiens) du prochain événement", ["Prédicteur", "N", "Erreur absolue moyenne"],
                      [["Moyenne passée brute du titre", len(g), float((g["z_abs"] - g["hist_mean_abs_z"]).abs().mean())],
                       ["Moyenne passée rétrécie vers le secteur", len(g), float((g["z_abs"] - shrunk).abs().mean())],
                       ["Moyenne passée du secteur", len(g), float((g["z_abs"] - g["sector_hist_abs_z"]).abs().mean())]],
                      ["str", "int", "num3"], n_col=1, note=f"Poids du titre = n / (n + k), k = σ²intra / τ²inter ≈ {k:.1f} (estimé sur l'échantillon).")
    blocks = [table("Moyenne par titre, brute et rétrécie", ["Titre", "Secteur", "N", "Moyenne brute", "Moyenne rétrécie", "Moyenne du secteur", "Poids du titre",
                                                              "Fiabilité"], rows, ["str", "str", "int", "pct" if p["target"] == "abs_car" else "num2",
                                                                                    "pct" if p["target"] == "abs_car" else "num2",
                                                                                    "pct" if p["target"] == "abs_car" else "num2", "num2", "str"], n_col=2,
                    note="Un titre à 4 annonces vaut presque son secteur ; un titre à 40 vaut presque lui-même (poids = τ² / (τ² + σ²/n)).")]
    if check:
        blocks.append(check)
    return ok(blocks, len(df), rel=reliability(df[p["target"]].to_numpy(), day0=df["day0"], min_events=ctx.cfg.min_events))


@study("p_amplitude", "P", "Modèle d'amplitude (panel, walk-forward purgé)",
       "Prédit |CAR| / σ avec un modèle poolé ; face aux baselines (moyenne du titre, du secteur) par MAE, QLIKE, corrélation de rang et Diebold-Mariano.",
       params=(Param("use_regime", "bool", False, "Inclure le régime HMM (plus lent)"),
               Param("purge_days", "int", 10, "Purge avant chaque pli test (jours)", lo=0, hi=60)), heavy=True)
def p_amplitude(ctx: Ctx, p: dict) -> dict:
    df, feats = _design(ctx, p["use_regime"], "z_abs")
    if len(df) < N_MIN_MODEL:
        return insufficient(len(df), N_MIN_MODEL)
    rows, pv, results = [], {}, {}
    for name in model.MODELS:
        res = model.evaluate_amplitude(df, feats, name, purge_days=p["purge_days"])
        if res["status"] != "ok":
            return insufficient(len(df), N_MIN_MODEL)
        results[name] = res
    first = next(iter(results.values()))
    for name, res in results.items():
        for label, m in res["models"].items():
            if label in ("Moyenne passée du titre", "Moyenne passée du secteur") and name != "ridge":
                continue
            dm = m.get("dm_vs_stock") or {}
            rows.append([label if label.startswith("Moyenne") else f"Modèle {label}", res["n"], m["mae"], m["qlike"], m["rho"], dm.get("p")])
            if dm.get("p") is not None:
                pv[f"p.amp.{label}.vs_stock"] = dm["p"]
    imp = model.importance_ridge(df, feats)
    skill = 1 - results["ridge"]["models"]["ridge"]["mae"] / results["ridge"]["models"]["Moyenne passée du titre"]["mae"]
    return ok([table("Prévision de l'amplitude, hors échantillon", ["Modèle", "N test", "MAE (σ quotidiens)", "QLIKE", "ρ de rang", "p (DM contre la moyenne du titre)"],
                     rows, ["str", "int", "num3", "num3", "num3", "p"], n_col=1,
                     note="Plis expansifs par date, événements d'entraînement chevauchant le pli de test retirés (purge). DM < 5 % avec une MAE plus basse : "
                          "le modèle bat la moyenne passée du titre. Le mouvement implicite des options est comparé à ces baselines dans la carte "
                          "« Mouvement implicite contre réalisé » dès que des instantanés sont appariés."),
               kv("Gain du modèle linéaire sur la baseline du titre", [("Réduction de MAE", skill, "pct"), ("Événements du panel", len(df), "int")]),
               bars("Poids du modèle linéaire (variables standardisées)", [f for f, _ in imp], [c for _, c in imp], "num3")],
              first["n"], pvalues=pv, rel=reliability(n=first["n"], day0=df["day0"], min_events=ctx.cfg.min_events))


@study("p_direction", "P", "Modèle de direction (panel, walk-forward purgé)",
       "Probabilité de hausse de la réaction ; AUC, taux de réussite, Brier face à la fréquence passée, calibration. Attente honnête : proche de l'efficience.",
       heavy=True)
def p_direction(ctx: Ctx, p: dict) -> dict:
    df, feats = _design(ctx, False, "car")
    if len(df) < N_MIN_MODEL:
        return insufficient(len(df), N_MIN_MODEL)
    res = model.evaluate_direction(df, feats)
    if res["status"] != "ok":
        return insufficient(len(df), N_MIN_MODEL)
    return ok([kv("Direction de la réaction", [("N test", res["n"], "int"), ("AUC", res["auc"], "num3"), ("Taux de réussite du modèle", res["hit"], "pct0"),
                                               ("Taux de réussite de la baseline (classe majoritaire)", res["hit_base"], "pct0"),
                                               ("Brier (modèle)", res["brier"], "num3"), ("Brier (fréquence passée)", res["brier_base"], "num3"),
                                               ("p (Diebold-Mariano sur le Brier)", res["dm_p"], "p")]),
               line("Diagramme de fiabilité : probabilité prédite contre fréquence observée", [round(c[0], 3) for c in res["calibration"]],
                    [{"name": "observée", "y": [c[1] for c in res["calibration"]]}, {"name": "parfaite", "y": [c[0] for c in res["calibration"]]}],
                    "probabilité prédite (déciles)", "pct0"),
               note("La direction autour des résultats est proche de l'efficience : un AUC voisin de 0,5 est le résultat attendu, un AUC élevé serait "
                    "surprenant et à contrôler contre une fuite d'information avant d'être cru.")],
              res["n"], pvalues={"p.dir.dm_brier": res["dm_p"]}, rel=reliability(n=res["n"], day0=df["day0"], min_events=ctx.cfg.min_events))


@study("p_composite", "P", "Score de sentiment composite (poids appris, décomposé)",
       "Sept composantes (news, surprise de sentiment, attention, révisions, dispersion des analystes, run-up, régime) pondérées par un modèle entraîné.",
       needs=("news", "snapshots"), heavy=True)
def p_composite(ctx: Ctx, p: dict) -> dict:
    fit = composite.fit(ctx)
    if fit["status"] != "ok":
        return insufficient(fit.get("n", 0), N_MIN_MODEL)
    rows = [[c["label"], c["status"], c["coverage"], c["weight"], c["role"]] for c in fit["components"]]
    return ok([table("Composantes du score et poids appris", ["Composante", "Disponibilité", "Couverture de l'historique", "Poids", "Rôle"], rows,
                     ["str", "str", "pct0", "num3", "str"], n_col=None,
                     note="Les poids viennent d'une régression ridge sur la réaction standardisée, jamais fixés à la main. Les composantes analystes sont "
                          "affichées mais pondérées à 0 tant que l'historique daté (instantanés quotidiens) est insuffisant."),
               kv("Fiabilité du score", [("R² hors échantillon (walk-forward)", fit["oos_r2"], "num3"), ("Événements d'entraînement", fit["n"], "int"),
                                         ("Seuil d'événements avec instantané analyste daté", composite.ANALYST_MIN_EVENTS, "int"),
                                         ("Événements avec instantané analyste daté", fit["n_analyst_pit"], "int")]),
               note("Lecture : un R² hors échantillon proche de 0 (ou négatif) signifie que le score n'a pas de pouvoir prédictif démontré. "
                    "Il reste un résumé lisible des composantes, pas un signal.")],
              fit["n"], rel=reliability(n=fit["n"], min_events=ctx.cfg.min_events))
