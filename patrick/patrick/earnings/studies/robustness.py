"""Robustesse méthodologique (§3.M) : obligatoire avant de croire un résultat des autres cartes.

- placebo : des dates aléatoires pour les MÊMES titres calibrent la taille réelle des tests (un test qui rejette bien plus de 5 % des
  placebos est invalide pour cet échantillon) ;
- sensibilité : le résultat tient-il quand on change la fenêtre d'estimation, le modèle de rendement attendu, la winsorisation ?
- recoupement macro : annonces dont la fenêtre contient un FOMC ou un jour d'emploi américain ;
- ajustements : splits, détachements de dividendes, modèles de repli, timing incertain ou douteux, fenêtres incomplètes, biais de survie.
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
from scipy import stats

from patrick.earnings import engine, schedule, signif
from patrick.earnings.config import EarningsConfig
from patrick.earnings.studies.base import (
    Ctx,
    Param,
    insufficient,
    kv,
    mann_whitney,
    note,
    ok,
    study,
    table,
    unavailable,
)

TEST_LABELS = {"bmp": "BMP", "patell": "Patell", "kp": "Kolari-Pynnönen", "corrado": "Corrado (rangs)", "sign": "Signes généralisé",
               "bootstrap": "Bootstrap par blocs"}


@study("m_placebo", "M", "Événements placebo : taille réelle des tests",
       "Dates aléatoires pour les mêmes titres : un test qui rejette trop souvent des placebos est invalide pour cet échantillon.",
       needs=("prices",), heavy=True,
       params=(Param("draws", "int", 30, "Répétitions", lo=5, hi=200), Param("per_draw", "int", 100, "Événements placebo par répétition", lo=30, hi=400),
               Param("level", "float", 0.05, "Niveau nominal", lo=0.01, hi=0.2),
               Param("win_lo", "int", 0, "Fenêtre testée : début (séances relatives)", lo=-10, hi=59),
               Param("win_hi", "int", 0, "Fenêtre testée : fin", lo=-10, hi=60)))
def m_placebo(ctx: Ctx, p: dict) -> dict:
    df = ctx.full.frame
    if len(df) < 30:
        return insufficient(len(df), 30)
    rng = np.random.default_rng(0)
    symbols = df["symbol"].value_counts()
    prices = {s: ctx.prices.prices(s) for s in symbols.index[:60]}
    prices = {s: sp for s, sp in prices.items() if sp is not None}
    if not prices:
        return unavailable("Aucun cours disponible pour tirer des placebos.", "prices")
    weights = np.array([symbols[s] for s in prices], dtype=float)
    weights /= weights.sum()
    real = {s: set(df.loc[df["symbol"] == s, "day0"]) for s in prices}
    if p["win_lo"] > p["win_hi"]:
        return insufficient(0, 1, "fenêtre valide (début <= fin)")
    cfg = replace(ctx.cfg, model="market")
    rejects = {k: 0 for k in TEST_LABELS}
    valid = {k: 0 for k in TEST_LABELS}
    names = list(prices)
    for _ in range(p["draws"]):
        rows = []
        for _k in range(p["per_draw"]):
            sym = names[rng.choice(len(names), p=weights)]
            sp = prices[sym]
            lo, hi = 300, len(sp.idx) - 70
            if hi <= lo:
                continue
            day = sp.idx[int(rng.integers(lo, hi))]
            if any(abs((day - d).days) < 8 for d in real[sym]):
                continue
            ev, _ = engine.compute_event(sp, symbol=sym, ann_date=day, timing="BMO", uncertain=False, cfg=cfg, other_days=list(real[sym]))
            if ev is not None:
                rows.append(ev)
        if len(rows) < 30:
            continue
        res = signif.run_tests(rows, p["win_lo"], p["win_hi"], n_boot=200)
        for k in TEST_LABELS:
            pval = (res.get("tests", {}).get(k) or {}).get("p")
            if pval is not None:
                valid[k] += 1
                rejects[k] += int(pval < p["level"])
    out, flags = [], []
    for k, label in TEST_LABELS.items():
        n = valid[k]
        if n < 5:
            continue
        rate = rejects[k] / n
        bt = stats.binomtest(rejects[k], n, p["level"]).pvalue
        verdict = "calibré" if bt > 0.05 else ("TROP DE REJETS : invalide" if rate > p["level"] else "conservateur")
        out.append([label, n, rate, p["level"], bt, verdict])
        if rate > 2 * p["level"]:
            flags.append(f"{label} rejette {rate:.0%} des placebos pour un niveau de {p['level']:.0%}")
    if not out:
        return insufficient(0, 5, "répétitions valides")
    return ok([table(f"Taux de rejet sur des événements placebo (fenêtre [{p['win_lo']:+d}, {p['win_hi']:+d}], H0 vraie par construction)",
                     ["Test", "Répétitions", "Taux de rejet", "Niveau nominal", "p (binomial)", "Verdict"], out,
                     ["str", "int", "pct1", "pct0", "p", "str"], n_col=1,
                     note=f"{p['per_draw']} dates aléatoires par répétition, au moins 8 jours de toute vraie annonce du titre, même modèle de marché. "
                          "Le taux doit se rapprocher du niveau nominal ; un taux nettement supérieur invalide le test pour cet échantillon.")],
              p["draws"] * p["per_draw"], flags=flags)


def _recompute(ctx: Ctx, sample: pd.DataFrame, cfg: EarningsConfig) -> list[dict]:
    rows = []
    by_sym = {s: set(g["day0"]) for s, g in ctx.full.frame.groupby("symbol")}
    for r in sample.itertuples():
        sp = ctx.prices.prices(r.symbol, cfg.model)
        if sp is None:
            continue
        ev, _ = engine.compute_event(sp, symbol=r.symbol, ann_date=r.ann_date, timing=r.timing, uncertain=r.uncertain, cfg=cfg,
                                     other_days=list(by_sym.get(r.symbol, ())))
        if ev is not None:
            rows.append(ev)
    return rows


@study("m_sensitivity", "M", "Sensibilité du résultat principal",
       "Le CAAR de réaction tient-il quand on change la fenêtre d'estimation, le modèle de rendement attendu ou la winsorisation ?",
       needs=("prices",), heavy=True, params=(Param("max_events", "int", 250, "Événements recalculés au maximum", lo=40, hi=1500),))
def m_sensitivity(ctx: Ctx, p: dict) -> dict:
    df = ctx.df
    if len(df) < 30:
        return insufficient(len(df), 30)
    sample = df.sample(min(len(df), p["max_events"]), random_state=0)
    base = ctx.cfg
    variants = [("Référence", base, 0.0)]
    variants += [(f"Estimation [{a}, {b}]", replace(base, est_window=(a, b)), 0.0) for a, b in ((-150, -30), (-200, -40), (-120, -20))]
    variants += [(f"Modèle : {m}", replace(base, model=m), 0.0) for m in ("market_adjusted", "sector", "factor") if m != base.model]
    variants += [(f"Winsorisation {w:.0%}", base, w) for w in (0.01, 0.05)]
    out, cars = [], []
    for label, cfg, wins in variants:
        rows = _recompute(ctx, sample, cfg) if label != "Référence" else ctx.panel.payloads(sample)
        if len(rows) < 12:
            continue
        r = signif.run_tests(rows, 0, 1, n_boot=200, winsor=wins)
        used = pd.Series([x["model_used"] for x in rows]).value_counts()
        fallback = int((pd.Series([x["model_used"] for x in rows]) != cfg.model).sum())
        out.append([label, r["n"], r.get("caar"), (r["tests"].get("bmp") or {}).get("p"), (r["tests"].get("kp") or {}).get("p"),
                    f"{int(used.iloc[0])} {used.index[0]}" + (f" ({fallback} en repli)" if fallback else "")])
        cars.append(r.get("caar"))
    if len(out) < 2:
        return insufficient(len(out), 2, "variantes calculables")
    cars = np.array([c for c in cars if c is not None])
    stable = bool(len(cars) and (np.all(cars > 0) or np.all(cars < 0)))
    return ok([table("CAAR [0, +1] selon les choix méthodologiques", ["Variante", "N", "CAAR", "p (BMP)", "p (KP)", "Modèle effectivement utilisé"], out,
                     ["str", "int", "pct", "p", "p", "str"], n_col=1,
                     note="Les variantes de fenêtre et de modèle sont recalculées sur un échantillon tiré au hasard (graine fixe)."),
               kv("Étendue", [("CAAR minimal", float(cars.min()), "pct"), ("CAAR maximal", float(cars.max()), "pct"),
                              ("Signe constant sur toutes les variantes", "oui" if stable else "non", "str")])],
              len(sample), flags=[] if stable else ["le signe du CAAR change selon la méthode"])


@study("m_macro_overlap", "M", "Recoupement avec les événements macro",
       "Annonces dont la fenêtre contient un FOMC ou un jour d'emploi américain : la réaction est-elle contaminée ?")
def m_macro_overlap(ctx: Ctx, p: dict) -> dict:
    df = ctx.df.copy()
    if len(df) < 30:
        return insufficient(len(df), 30)
    macro = schedule.macro_days(df["day0"].min() - pd.Timedelta(days=5), df["day0"].max() + pd.Timedelta(days=5))
    mdays = pd.DatetimeIndex(sorted(macro))
    df["macro"] = [bool(len(mdays) and ((mdays >= d - pd.Timedelta(days=1)) & (mdays <= d + pd.Timedelta(days=1))).any()) for d in df["day0"]]
    hit, clean = df[df["macro"]], df[~df["macro"]]
    if len(hit) < 5 or len(clean) < 5:
        return insufficient(min(len(hit), len(clean)), 5, "annonces de chaque groupe")
    pa = mann_whitney(hit["z_abs"], clean["z_abs"])
    r_all = signif.run_tests(ctx.panel.payloads(df), 0, 1, n_boot=200)
    r_clean = signif.run_tests(ctx.panel.payloads(clean), 0, 1, n_boot=200)
    return ok([table("Annonces avec ou sans jour macro dans [J0−1, J0+1]", ["Groupe", "N", "Amplitude (σ)", "|CAR| moyen", "CAAR [0,+1]"],
                     [["Avec FOMC / emploi", len(hit), float(hit["z_abs"].mean()), float(hit["abs_car"].mean()), float(hit["car01"].mean())],
                      ["Sans", len(clean), float(clean["z_abs"].mean()), float(clean["abs_car"].mean()), float(clean["car01"].mean())]],
                     ["str", "int", "num2", "pct", "pct"], n_col=1, note=f"Mann-Whitney sur l'amplitude : p = {pa:.3f}."),
               kv("CAAR [0,+1] et BMP", [("Échantillon complet", (r_all.get("caar")), "pct"), ("p (BMP)", (r_all["tests"].get("bmp") or {}).get("p"), "p"),
                                         ("Sans jours macro", (r_clean.get("caar")), "pct"), ("p (BMP)", (r_clean["tests"].get("bmp") or {}).get("p"), "p")]),
               note("Jours couverts : décisions du FOMC (liste du module `schedule`, à mettre à jour chaque année) et emploi américain approximé au premier "
                    "vendredi du mois. L'inflation (CPI) n'a pas de calendrier gratuit fiable : non couverte, donc contrôle partiel.", "warning")],
              len(df), pvalues={"m.macro.amplitude": pa})


@study("m_adjustments", "M", "Ajustements, drapeaux et biais de survie",
       "Splits, dividendes, modèles de repli, timing incertain ou douteux, fenêtres incomplètes ; ce que les données gratuites ne voient pas.")
def m_adjustments(ctx: Ctx, p: dict) -> dict:
    df = ctx.df
    if len(df) < 8:
        return insufficient(len(df), 8)
    flags = [("Timing incertain (heure absente, pendant la séance ou repli par place)", df["uncertain"]),
             ("Timing douteux (le plus gros mouvement est sur l'autre jour)", df["timing_suspect"]),
             ("Modèle de repli (facteurs ou secteur indisponibles)", df["model_used"] != ctx.cfg.model),
             ("Split dans la fenêtre [−250, +60] (volumes à lire avec prudence)", df["split_flag"]),
             ("Dividende détaché dans [−10, +60] (cours ajustés : sans effet sur les rendements)", df["ex_div_flag"]),
             ("Fenêtre post-annonce incomplète (< 60 séances écoulées)", df["n_post"] < 60)]
    rows = [[label, int(mask.sum()), float(mask.mean())] for label, mask in flags]
    clean = df[~(df["timing_suspect"] | df["uncertain"])]
    cmp_rows = []
    if len(clean) >= 5 and len(df) > len(clean):
        cmp_rows = [["Tous les événements", len(df), float(df["z_abs"].mean()), float(df["car"].mean())],
                    ["Sans timing incertain ni douteux", len(clean), float(clean["z_abs"].mean()), float(clean["car"].mean())]]
    blocks = [table("Drapeaux sur l'échantillon", ["Drapeau", "Événements", "Part"], rows, ["str", "int", "pct0"], n_col=1)]
    if cmp_rows:
        blocks.append(table("Effet des drapeaux sur les résultats", ["Échantillon", "N", "Amplitude (σ)", "CAR moyen"], cmp_rows, ["str", "int", "num2", "pct"], n_col=1))
    blocks.append(note("Biais de survie : les titres délistés, absorbés ou en faillite disparaissent des données gratuites. Les statistiques décrivent les "
                       "survivants, donc des titres dont l'histoire d'annonces s'est plutôt bien passée. Les cours sont ajustés des splits et des dividendes ; "
                       "les opérations sur titres plus complexes (scissions) ne le sont pas toujours.", "warning"))
    return ok(blocks, len(df))
