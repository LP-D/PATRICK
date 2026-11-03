"""Score de sentiment composite (§4) : indicateurs d'abord, score ensuite, et seulement si l'historique le permet.

Sept composantes : sentiment des news, surprise de sentiment, choc d'attention, révisions du consensus, dispersion des analystes, run-up,
régime. Ce sont des INDICATEURS ; le score est la combinaison que choisit un modèle (ridge) entraîné sur l'historique, jamais des poids
écrits à la main. Il se lit toujours décomposé par composante (contribution = poids x valeur standardisée, ce que SHAP donne exactement
pour un modèle linéaire), avec sa fiabilité (R² hors échantillon en walk-forward purgé).

Honnêteté sur les analystes : Yahoo ne donne que le consensus du jour. Tant que moins de `ANALYST_MIN_EVENTS` annonces passées disposent d'un
instantané DATÉ pris avant elles, les composantes analystes sont AFFICHÉES mais pondérées à 0 : un backtest avec le consensus d'aujourd'hui
serait contaminé par l'information future. Mode prospectif : `consensus.take_snapshots` accumule le vrai historique.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from patrick.earnings import consensus, model, store

log = logging.getLogger(__name__)
ANALYST_MIN_EVENTS = 60
MIN_COVERAGE = 0.15
MIN_EVENTS_FIT = 60
COMPONENTS = {
    "news_sent": ("Sentiment des news", "news"),
    "sent_surprise": ("Surprise de sentiment", "news"),
    "attention": ("Choc d'attention", "news"),
    "consensus_rev": ("Révisions du consensus (30 j)", "analyst"),
    "analyst_dispersion": ("Dispersion des analystes", "analyst"),
    "run_up": ("Run-up pré-annonce", "price"),
    "regime": ("Régime de stress", "price"),
}


def analyst_pit(ctx) -> pd.DataFrame:
    """Révisions et dispersion tirées du DERNIER instantané daté pris AVANT chaque annonce passée (index = colonne `i` du panel)."""
    snaps = store.snapshots(ctx.conn, kind="consensus")
    by_sym: dict[str, list] = {}
    for s in snaps:
        by_sym.setdefault(s["symbol"], []).append(s)
    recs = []
    for r in ctx.full.frame.itertuples():
        best = None
        for s in by_sym.get(r.symbol, []):
            if s["snap_date"] < str(r.ann_date.date()) and (best is None or s["snap_date"] > best["snap_date"]):
                best = s
        if best is not None:
            c = consensus.summarize(best["payload"])
            recs.append({"i": r.i, "consensus_rev": c["rev_30d"], "analyst_dispersion": c["dispersion"]})
    return pd.DataFrame(recs, columns=["i", "consensus_rev", "analyst_dispersion"]).set_index("i")


def components_frame(ctx) -> pd.DataFrame:
    """Valeurs brutes des composantes pour chaque événement du panel complet (NaN = non disponible à cette date)."""
    df = ctx.full.frame
    out = pd.DataFrame(index=df["i"])
    out["run_up"] = (df["run_up"] / df["sigma"].where(df["sigma"] > 0)).to_numpy()
    out["regime"] = np.nan
    try:
        from patrick.earnings.studies.cross import market_state
        reg = market_state(ctx)["regime"]
        out["regime"] = (reg == "stress").astype(float).where(reg.notna()).reindex(out.index)
    except Exception as exc:  # noqa: BLE001 -- prix de l'indice absents : composante indisponible
        log.info("régime indisponible pour le score composite : %s", exc)
    from patrick.earnings.studies.news_analysts import _news_frame, event_news_features
    news = _news_frame(ctx)
    for col in ("news_sent", "sent_surprise", "attention"):
        out[col] = np.nan
    if news is not None and not news.empty:
        first = news["known_at"].min()
        feats = {r.i: event_news_features(news, r.symbol, r.ann_date, first) for r in df.itertuples()}
        f = pd.DataFrame.from_dict(feats, orient="index")
        out["news_sent"], out["sent_surprise"], out["attention"] = f["sent_mean"], f["sent_surprise"], f["attention_z"]
    pit = analyst_pit(ctx)
    out["consensus_rev"] = pit["consensus_rev"].reindex(out.index) if len(pit) else np.nan
    out["analyst_dispersion"] = pit["analyst_dispersion"].reindex(out.index) if len(pit) else np.nan
    return out


def fit(ctx) -> dict:
    df = ctx.full.frame
    if len(df) < MIN_EVENTS_FIT:
        return {"status": "insufficient", "n": len(df)}
    comp = components_frame(ctx)
    y = df.set_index("i")["z"].clip(-5, 5)
    n_pit = int(comp["consensus_rev"].notna().sum())
    analyst_ok = n_pit >= ANALYST_MIN_EVENTS
    usable, info = [], []
    for key, (label, kind) in COMPONENTS.items():
        cov = float(comp[key].notna().mean())
        if kind == "analyst" and not analyst_ok:
            info.append({"key": key, "label": label, "status": "affichage seulement (historique daté insuffisant)", "coverage": cov, "weight": 0.0,
                         "role": "Affichage seulement"})
        elif cov < MIN_COVERAGE or comp[key].notna().sum() < 30:
            info.append({"key": key, "label": label, "status": "indisponible (historique trop court)", "coverage": cov, "weight": 0.0, "role": "Indisponible"})
        else:
            usable.append(key)
            info.append({"key": key, "label": label, "status": "disponible", "coverage": cov, "weight": np.nan, "role": "Appris"})
    if not usable:
        return {"status": "insufficient", "n": len(df), "components": info}
    X = comp[usable]
    mu, sd = X.mean(), X.std(ddof=0).replace(0, 1.0)
    Z = ((X - mu) / sd).fillna(0.0)
    from sklearn.linear_model import Ridge
    ok_ = y.notna()
    m = Ridge(alpha=20.0).fit(Z[ok_].to_numpy(), y[ok_].to_numpy())
    weights = dict(zip(usable, m.coef_.tolist()))
    for c in info:
        if c["key"] in weights:
            c["weight"] = weights[c["key"]]
    sse_m = sse_b = 0.0
    n_oos = 0
    zz, yy = Z[ok_].to_numpy(), y[ok_].to_numpy()
    days = df.set_index("i").loc[Z[ok_].index, "day0"].reset_index(drop=True)
    for train, test in model.walk_forward_folds(days):
        r = Ridge(alpha=20.0).fit(zz[train], yy[train])
        pred = r.predict(zz[test])
        sse_m += float(((yy[test] - pred) ** 2).sum())
        sse_b += float(((yy[test] - yy[train].mean()) ** 2).sum())
        n_oos += len(test)
    oos = 1 - sse_m / sse_b if n_oos and sse_b > 0 else np.nan
    return {"status": "ok", "n": int(ok_.sum()), "oos_r2": oos, "components": info, "weights": weights, "mu": mu.to_dict(), "sd": sd.to_dict(),
            "intercept": float(m.intercept_), "n_analyst_pit": n_pit, "usable": usable}


def decompose(fit_result: dict, values: dict[str, float | None]) -> dict:
    """Score d'un événement à partir de valeurs brutes, décomposé : contribution = poids x valeur standardisée (0 si manquante)."""
    contrib = {}
    for key in fit_result.get("usable", []):
        v = values.get(key)
        z = 0.0 if v is None or not np.isfinite(v) else (v - fit_result["mu"][key]) / fit_result["sd"][key]
        contrib[key] = fit_result["weights"][key] * z
    return {"score": float(sum(contrib.values())), "contributions": contrib}
