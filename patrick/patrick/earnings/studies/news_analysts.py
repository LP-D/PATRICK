"""Sentiment : news, analystes, texte (§3.F).

Règles de fuite d'information :
- les features d'un événement n'utilisent que des news CONNUES strictement avant le début du jour d'annonce (`known_at`, jamais la date
  annoncée de la source) ; les news postérieures à l'annonce ne servent QUE à l'analyse a posteriori (`f_news_post`) et ne
  doivent jamais entrer dans un modèle prédictif ;
- le consensus analyste n'existe qu'en instantané du jour : affichage et mode prospectif (voir `consensus.py`) ;
- seuls les changements de recommandation DATÉS (`upgrades_downgrades`) sont utilisables rétrospectivement, avec la réserve que Yahoo
  peut être incomplet et qu'aucun historique ne garantit l'absence de révision.
"""
from __future__ import annotations

import re
import unicodedata

import numpy as np
import pandas as pd

from patrick.earnings import consensus, store
from patrick.earnings.reliability import partial_pooling
from patrick.earnings.studies.base import (
    Ctx,
    Param,
    insufficient,
    kv,
    note,
    ok,
    rel_for,
    spearman,
    study,
    table,
    unavailable,
)

MIN_ARTICLES = 1
PRE_DAYS = 7
BASE_WINDOWS = 8


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(text).lower()) if unicodedata.category(c) != "Mn")


def _news_frame(ctx: Ctx) -> pd.DataFrame | None:
    """News scorées, rattachées à un titre par lien d'entité OU par le nom de la société dans le titre. Chargées une fois."""
    if "news" in ctx.memo:
        return ctx.memo["news"]
    from patrick.text import service
    from patrick.text import store as tstore
    try:
        items = tstore.load_items(ctx.conn, max_lag_hours=service.MAX_LAG_HOURS)
    except Exception:  # noqa: BLE001 -- base sans magasin de news
        ctx.memo["news"] = None
        return None
    if items.empty:
        ctx.memo["news"] = None
        return None
    score = tstore.load_scores(ctx.conn, service.LEXICON, service.lexicon_version())[["item_id", "score"]]
    nov = tstore.load_scores(ctx.conn, service.NOVELTY, service.VERSION)[["item_id", "score"]].rename(columns={"score": "novelty"})
    links = tstore.load_links(ctx.conn)[["item_id", "symbol"]]
    base = items.merge(score, on="item_id", how="left").merge(nov, on="item_id", how="left")
    linked = base.merge(links, on="item_id")
    by_name = []
    title_fold = base["title"].map(_fold)
    for sym in ctx.full.frame["symbol"].unique():
        ins = ctx.full.instruments.get(sym, {})
        name = _fold(ins.get("longName") or ins.get("shortName") or "")
        name = re.sub(r"\b(inc|corp|corporation|plc|sa|se|ag|nv|ltd|holdings|group|company|co)\b\.?", "", name).strip(" ,.")
        if len(name) < 5:
            continue
        hit = base[title_fold.str.contains(rf"\b{re.escape(name)}\b", regex=True)].copy()
        if len(hit):
            hit["symbol"] = sym
            by_name.append(hit)
    out = pd.concat([linked, *by_name]).drop_duplicates(["item_id", "symbol"])
    ctx.memo["news"] = out[["item_id", "symbol", "known_at", "score", "novelty"]].reset_index(drop=True)
    return ctx.memo["news"]


def _window_stats(part: pd.DataFrame) -> dict:
    s = part["score"].dropna()
    return {"n": len(part), "mean": float(s.mean()) if len(s) else np.nan, "sd": float(s.std(ddof=1)) if len(s) > 1 else np.nan,
            "novel": float((part["novelty"] >= 0.3).mean()) if part["novelty"].notna().any() else np.nan}


def event_news_features(news: pd.DataFrame, symbol: str, ann_date: pd.Timestamp, first_known: pd.Timestamp) -> dict:
    """Features de news d'un événement sur [-7j, -1j] avant le début du jour d'annonce. `first_known` : première news du magasin
    (une fenêtre de référence antérieure n'est valable que si le magasin la couvre)."""
    mine = news[news["symbol"] == symbol]
    t0 = pd.Timestamp(ann_date).tz_localize("UTC") if pd.Timestamp(ann_date).tzinfo is None else pd.Timestamp(ann_date)
    pre = mine[(mine["known_at"] >= t0 - pd.Timedelta(days=PRE_DAYS)) & (mine["known_at"] < t0)]
    cur = _window_stats(pre)
    base_n, base_mean = [], []
    for k in range(1, BASE_WINDOWS + 1):
        lo, hi = t0 - pd.Timedelta(days=PRE_DAYS * (k + 1)), t0 - pd.Timedelta(days=PRE_DAYS * k)
        if lo < first_known:
            break                                                    # fenêtre de référence hors de la couverture du magasin
        w = mine[(mine["known_at"] >= lo) & (mine["known_at"] < hi)]
        base_n.append(len(w))
        if w["score"].notna().any():
            base_mean.append(float(w["score"].mean()))
    out = {"n_art": cur["n"], "sent_mean": cur["mean"], "sent_sd": cur["sd"], "novel_share": cur["novel"],
           "attention_z": np.nan, "sent_surprise": np.nan}
    if len(base_n) >= 4 and np.std(base_n, ddof=1) > 0:
        out["attention_z"] = (cur["n"] - np.mean(base_n)) / np.std(base_n, ddof=1)
    if len(base_mean) >= 3 and np.isfinite(cur["mean"]):
        out["sent_surprise"] = cur["mean"] - float(np.mean(base_mean))
    return out


@study("f_news_sentiment", "F", "Sentiment des news avant l'annonce",
       "Sentiment moyen et dispersion, choc d'attention, surprise de sentiment et nouveauté sur [−7 j, −1 j] ; lien avec la réaction.",
       needs=("news",))
def f_news_sentiment(ctx: Ctx, p: dict) -> dict:
    news = _news_frame(ctx)
    if news is None or news.empty:
        return unavailable("Le magasin de news est vide ou n'a aucune nouvelle rattachée à ces titres. La collecte (`patrick news refresh`) "
                           "construit l'historique point-in-time : les features n'existent que pour les annonces survenues après.", "news")
    first_known = news["known_at"].min()
    df = ctx.df
    recs = []
    for r in df.itertuples():
        f = event_news_features(news, r.symbol, r.ann_date, first_known)
        recs.append({"i": r.i, "car": r.car, "z_abs": r.z_abs, **f})
    feat = pd.DataFrame(recs)
    covered = feat[feat["n_art"] >= MIN_ARTICLES]
    cover_row = [("Événements", len(feat), "int"), ("Avec au moins une news [−7 j, −1 j]", len(covered), "int"),
                 ("Avec choc d'attention calculable", int(feat["attention_z"].notna().sum()), "int"),
                 ("Première news du magasin", str(first_known.date()), "str")]
    if len(covered) < 8:
        return ok([kv("Couverture", cover_row),
                   note("Trop peu d'annonces ont des news avant elles : l'historique de news est plus court que celui des annonces. "
                        "Les features sont calculées pour les nouvelles annonces au fur et à mesure que le magasin s'allonge.", "warning")],
                  len(covered), flags=["historique de news court"])
    rows, pv = [], {}
    for label, col, target in (("Sentiment moyen → sens de la réaction", "sent_mean", "car"),
                               ("Surprise de sentiment → sens de la réaction", "sent_surprise", "car"),
                               ("Choc d'attention → amplitude", "attention_z", "z_abs"),
                               ("Dispersion du sentiment → amplitude", "sent_sd", "z_abs"),
                               ("Part de nouvelles inédites → amplitude", "novel_share", "z_abs")):
        rho, pval, n = spearman(covered[col], covered[target])
        rows.append([label, n, rho, pval])
        pv[f"f.news.{col}"] = pval
    return ok([kv("Couverture", cover_row),
               table("Features de news → réaction (corrélations de Spearman)", ["Relation", "N", "ρ", "p"], rows, ["str", "int", "num3", "p"], n_col=1,
                     note="Surprise de sentiment = sentiment actuel − sa moyenne passée pour ce titre : évite de prendre un titre "
                          "structurellement « positif » pour un signal."),
               note("Chaque feature n'utilise que des news connues avant le début du jour d'annonce.")],
              len(covered), pvalues=pv, rel=rel_for(ctx, ctx.df, "car"))


@study("f_news_lag", "F", "Décalage news → prix",
       "Corrélation croisée entre le sentiment quotidien et le rendement à plusieurs retards : les news précèdent-elles les prix ?",
       needs=("news", "prices"), params=(Param("max_lag", "int", 3, "Retard maximal (jours)", lo=1, hi=10),))
def f_news_lag(ctx: Ctx, p: dict) -> dict:
    news = _news_frame(ctx)
    if news is None or news.empty:
        return unavailable("Magasin de news vide.", "news")
    pairs: dict[int, list] = {k: [] for k in range(-p["max_lag"], p["max_lag"] + 1)}
    used = 0
    for sym in ctx.df["symbol"].unique():
        mine = news[news["symbol"] == sym]
        if mine["known_at"].dt.normalize().nunique() < 30:
            continue
        sp = ctx.prices.prices(sym)
        if sp is None:
            continue
        daily = mine.assign(day=mine["known_at"].dt.tz_convert("UTC").dt.tz_localize(None).dt.normalize()).groupby("day")["score"].mean()
        sent = daily.reindex(sp.idx)
        ret = pd.Series(sp.r, index=sp.idx)
        used += 1
        for k, bucket in pairs.items():
            both = pd.concat([sent.shift(k), ret], axis=1).dropna()                  # k > 0 : sentiment d'il y a k jours
            bucket.extend(both.values.tolist())
    if used == 0:
        return ok([note("Aucun titre n'a assez de jours de news (30 requis) pour une corrélation croisée.", "warning")], 0)
    rows = []
    for k, arr_ in pairs.items():
        a = np.array(arr_)
        rho, pval, n = spearman(a[:, 0], a[:, 1]) if len(a) else (np.nan, np.nan, 0)
        rows.append([f"{k:+d} j", n, rho, pval])
    return ok([table("Corrélation entre sentiment(t − k) et rendement(t)", ["Retard k", "N", "ρ", "p"], rows, ["str", "int", "num3", "p"], n_col=1,
                     note="k > 0 : le sentiment précède le rendement (information exploitable si ρ ≠ 0) ; k ≤ 0 : les news ne font que reprendre "
                          "le mouvement.")], sum(r[1] for r in rows), pvalues={f"f.newslag.{r[0]}": r[3] for r in rows})


@study("f_news_post", "F", "Réaction des news après l'annonce (a posteriori)",
       "Sentiment des news [0 j, +3 j] et réaction. Analyse a posteriori seulement : ne doit jamais entrer dans un modèle prédictif.",
       needs=("news",))
def f_news_post(ctx: Ctx, p: dict) -> dict:
    news = _news_frame(ctx)
    if news is None or news.empty:
        return unavailable("Magasin de news vide.", "news")
    rows = []
    for r in ctx.df.itertuples():
        t0 = pd.Timestamp(r.day0).tz_localize("UTC")
        w = news[(news["symbol"] == r.symbol) & (news["known_at"] >= t0) & (news["known_at"] < t0 + pd.Timedelta(days=4))]
        if len(w):
            rows.append({"sent": w["score"].mean(), "n": len(w), "car": r.car, "z_abs": r.z_abs})
    d = pd.DataFrame(rows)
    if len(d) < 8:
        return ok([note(f"{len(d)} annonce(s) avec des news après coup : trop peu.", "warning")], len(d))
    rho, pval, n = spearman(d["sent"], d["car"])
    rho2, p2, _ = spearman(d["n"], d["z_abs"])
    return ok([table("News après l'annonce", ["Relation", "N", "ρ", "p"],
                     [["Sentiment [0, +3 j] → sens de la réaction", n, rho, pval], ["Nombre de news → amplitude", n, rho2, p2]],
                     ["str", "int", "num3", "p"], n_col=1,
                     note="Les news postérieures reprennent le mouvement : elles expliquent la réaction, elles ne la prédisent pas "
                          "(leur utilisation en prédiction serait une fuite d'information).")],
              n, pvalues={"f.newspost.sent": pval, "f.newspost.count": p2})


# --------------------------------------------------------------------------------------------------------------- analystes

@study("f_analyst_snapshot", "F", "Consensus et révisions (instantané du jour)",
       "Révisions du BPA consensuel (7/30/60/90 jours), dispersion, nombre d'analystes, recommandations, cible de cours.",
       needs=("snapshots",))
def f_analyst_snapshot(ctx: Ctx, p: dict) -> dict:
    snaps = store.snapshots(ctx.conn, kind="consensus")
    wanted = set(ctx.batch_symbols) or set(ctx.df["symbol"].unique())
    last: dict[str, dict] = {}
    for s in snaps:
        if s["symbol"] in wanted:
            last[s["symbol"]] = s
    if not last:
        return unavailable("Aucun instantané de consensus pour ces titres. Yahoo ne donne que le consensus du jour : il est stocké chaque "
                           "jour (bouton « Instantané du jour » ou `patrick earnings snapshot`) pour construire l'historique daté.", "snapshots")
    rows = []
    for sym, s in sorted(last.items()):
        c = consensus.summarize(s["payload"])
        rows.append([sym, s["snap_date"], c["eps_avg"], c["n_analysts"], c["dispersion"], c["rev_7d"], c["rev_30d"], c["rev_60d"], c["rev_90d"],
                     c["net_rev_30d"], c["reco_score"], c["pt_upside"]])
    counts = pd.Series([sum(1 for s in snaps if s["symbol"] == sym) for sym in last]).describe()
    return ok([table("Consensus du dernier instantané (trimestre en cours)",
                     ["Titre", "Date", "BPA moyen", "Analystes", "Dispersion", "Rév. 7 j", "Rév. 30 j", "Rév. 60 j", "Rév. 90 j",
                      "Révisions nettes 30 j", "Score reco.", "Hausse vers la cible"], rows,
                     ["str", "str", "num2", "int", "pct0", "pct", "pct", "pct", "pct", "num2", "num2", "pct"], n_col=3,
                     note="Affichage, pas une variable évaluée : sans historique daté, tout backtest sur ces valeurs serait contaminé par "
                          "l'information future. Dispersion = (haut − bas) / |moyenne| ; score reco. = (achat − vente) / total."),
               kv("Accumulation", [("Instantanés par titre (médiane)", float(counts["50%"]), "num2"),
                                   ("Titres suivis", len(last), "int")])],
              len(last), flags=["affichage seulement"])


@study("f_analyst_bias", "F", "Biais historique du consensus",
       "Taux de dépassement du consensus et amplitude de la surprise par titre, rétrécis vers le secteur.")
def f_analyst_bias(ctx: Ctx, p: dict) -> dict:
    df = ctx.df.dropna(subset=["surprise_pct"])
    if len(df) < 12:
        return insufficient(len(df), 12)
    from scipy import stats
    beats = int((df["surprise_pct"] > 0).sum())
    pb = float(stats.binomtest(beats, len(df), 0.5).pvalue)
    by_sym = {s: g["beat"].to_numpy() for s, g in df.groupby("symbol")}
    prior = {s: g["sector"].iloc[0] for s, g in df.groupby("symbol")}
    pooled = partial_pooling(by_sym, prior)
    rows = [[s, v["n"], v["raw"], v["shrunk"], v["weight"], float(df.loc[df["symbol"] == s, "surprise_pct"].median()) / 100]
            for s, v in sorted(pooled.items(), key=lambda kv_: -kv_[1]["n"])][:60]
    return ok([kv("Ensemble", [("Annonces avec surprise", len(df), "int"), ("Taux de dépassement", beats / len(df), "pct0"),
                               ("p (≠ 50 %)", pb, "p"), ("Surprise médiane", float(df["surprise_pct"].median()) / 100, "pct")]),
               table("Par titre (taux de dépassement brut et rétréci vers le secteur)",
                     ["Titre", "N", "Taux brut", "Taux rétréci", "Poids du titre", "Surprise médiane"], rows,
                     ["str", "int", "pct0", "pct0", "num2", "pct"], n_col=1,
                     note="Les consensus sont structurellement biaisés à la baisse (les directions guident les analystes) : la littérature "
                          "américaine cite environ 70 % de dépassements, à vérifier sur ton échantillon.")],
              len(df), pvalues={"f.bias.beat_rate": pb}, rel=rel_for(ctx, df, "surprise_pct"))


_POS = ("buy", "outperform", "overweight", "positive", "accumulate", "add", "strong buy", "top pick", "conviction")
_NEG = ("sell", "underperform", "underweight", "negative", "reduce", "strong sell")


def _grade_score(text) -> float:
    t = str(text).lower()
    if any(w in t for w in _NEG):
        return -1.0
    if any(w in t for w in _POS):
        return 1.0
    return 0.0 if t and t != "nan" else np.nan


@study("f_analyst_actions", "F", "Changements de recommandation datés",
       "Relèvements/abaissements nets et variation des objectifs de cours dans les 30 jours avant l'annonce (série datée de Yahoo).",
       needs=("analysts",), params=(Param("days", "int", 30, "Fenêtre avant l'annonce (jours)", lo=5, hi=120),), heavy=True)
def f_analyst_actions(ctx: Ctx, p: dict) -> dict:
    df = ctx.df
    recs = []
    for sym, g in df.groupby("symbol"):
        up = ctx.provider.upgrades(sym)
        if up is None or up.empty:
            continue
        up = up.copy()
        up["to"] = up["ToGrade"].map(_grade_score)
        up["from"] = up["FromGrade"].map(_grade_score)
        up["move"] = np.sign(up["to"] - up["from"]).where(up["Action"].isin(["up", "down"]), 0.0)
        up["pt"] = (up["currentPriceTarget"] / up["priorPriceTarget"] - 1).replace([np.inf, -np.inf], np.nan)
        for r in g.itertuples():
            lo = pd.Timestamp(r.ann_date) - pd.Timedelta(days=p["days"])
            w = up[(up.index >= lo) & (up.index < pd.Timestamp(r.ann_date))]
            recs.append({"symbol": sym, "n": len(w), "net": float(w["move"].sum()), "pt_change": float(w["pt"].mean()) if w["pt"].notna().any() else np.nan,
                         "car": r.car, "z_abs": r.z_abs})
    d = pd.DataFrame(recs)
    if d.empty or (d["n"] > 0).sum() < 12:
        return ok([note("Moins de 12 annonces précédées de changements de recommandation datés dans la source : étude non concluante.", "warning")],
                  0 if d.empty else int((d["n"] > 0).sum()), flags=["couverture insuffisante"])
    cov = d[d["n"] > 0]
    rows, pv = [], {}
    for label, col, target in (("Relèvements nets → sens de la réaction", "net", "car"), ("Variation moyenne des objectifs → sens", "pt_change", "car"),
                               ("Nombre d'actions → amplitude", "n", "z_abs")):
        rho, pval, n = spearman(cov[col], cov[target])
        rows.append([label, n, rho, pval])
        pv[f"f.actions.{col}"] = pval
    return ok([table("Actions d'analystes avant l'annonce → réaction", ["Relation", "N", "ρ", "p"], rows, ["str", "int", "num3", "p"], n_col=1,
                     note="Série datée mais non auditée : Yahoo peut être incomplet et ne garantit pas l'absence de révision. "
                          "Les anciennes années sont moins couvertes que les récentes (biais de couverture)."),
               kv("Couverture", [("Annonces", len(d), "int"), ("Avec au moins une action datée", len(cov), "int")])],
              len(cov), pvalues=pv)


@study("f_transcripts", "F", "Texte des conférences téléphoniques",
       "Ton (Loughran-McDonald), hedging, contraste discours préparé / questions-réponses.")
def f_transcripts(ctx: Ctx, p: dict) -> dict:
    return unavailable("Les transcriptions sont majoritairement payantes : aucune source gratuite fiable. Le lexique Loughran-McDonald du projet "
                       "(`patrick/text/lexicon.py`) est prêt à noter un texte dès qu'une source existera.", "transcripts")
