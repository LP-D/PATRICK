"""Étude de faisabilité de la cible de volatilité (ADR 0011, point 5.1). Aucun code du pipeline n'est touché.

Étiquette : 1 si log(sigma_futur / sigma_passé) > 0, les deux sur une fenêtre de h séances (sigma = racine de la moyenne des rendements²).
Scores comparés, AUC hors échantillon (réajustement annuel, expansion, trou de h séances) :
  - 'mr'  : aucun modèle, score = -(log sigma_passé - log sigma_252) (retour à la moyenne vers le niveau long) ;
  - 'har' : régression logistique sur les variables HAR (log sigma sur 1, 5, 22, 66 séances, écart au niveau 252 séances).
Usage : python scripts/vol_target_study.py [nombre d'actifs] [fichier CSV]. Lit le cache local ~/.patrick/cache (séries yfinance déjà téléchargées).
Référence de comparaison : l'AUC de la direction du PRIX sur les mêmes séries (étiquette = signe du rendement futur sur h séances, mêmes variables).
"""
import glob
import os
import random
import sys
import warnings

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")
CACHE = os.path.expanduser("~/.patrick/cache")
HORIZONS = (5, 20)
OOS_START = "2012-01-01"
MIN_ROWS = 3000


def load(path):
    df = pd.read_parquet(path)
    s = df.iloc[:, 0].astype(float).dropna()
    s = s[s > 0]
    s.index = pd.to_datetime(s.index)
    return s[~s.index.duplicated()].sort_index()


def rv(r, w):
    return np.sqrt((r ** 2).rolling(w).mean())


def build(close, h):
    r = np.log(close).diff()
    feats = pd.DataFrame({
        "v1": np.log(r.abs() + 1e-6), "v5": np.log(rv(r, 5) + 1e-6), "v22": np.log(rv(r, 22) + 1e-6),
        "v66": np.log(rv(r, 66) + 1e-6), "v252": np.log(rv(r, 252) + 1e-6)})
    feats["gap"] = feats["v22"] - feats["v252"]
    sig_p = rv(r, h)
    sig_f = rv(r, h).shift(-h)
    y_vol = (np.log(sig_f + 1e-9) - np.log(sig_p + 1e-9) > 0).astype(float)
    fut = np.log(close).shift(-h) - np.log(close)
    y_px = (fut > 0).astype(float)
    mr = -(np.log(sig_p + 1e-9) - feats["v252"])
    ok = feats.notna().all(axis=1) & sig_f.notna() & sig_p.notna()
    return feats[ok], y_vol[ok], y_px[ok], mr[ok]


def oos_auc(X, y, h, kind):
    dates = X.index
    scores = pd.Series(np.nan, index=dates)
    for year in sorted({d.year for d in dates if d >= pd.Timestamp(OOS_START)}):
        test = (dates.year == year)
        train_end = pd.Timestamp(f"{year}-01-01")
        train = (dates < train_end) & (np.arange(len(dates)) < np.searchsorted(dates, train_end) - h)
        if train.sum() < 500 or test.sum() < 20 or y[train].nunique() < 2:
            continue
        sc = StandardScaler().fit(X[train])
        m = LogisticRegression(C=0.5, max_iter=300).fit(sc.transform(X[train]), y[train])
        scores[test] = m.decision_function(sc.transform(X[test]))
    ok = scores.notna()
    if ok.sum() < 500 or y[ok].nunique() < 2:
        return np.nan
    return roc_auc_score(y[ok], scores[ok])


def main(n_series=60, seed=3):
    files = sorted(glob.glob(os.path.join(CACHE, "series_*_2000-01-01.parquet")))
    random.Random(seed).shuffle(files)
    rows = []
    for f in files:
        if len(rows) >= n_series * len(HORIZONS):
            break
        name = os.path.basename(f)[len("series_"):-len("_2000-01-01.parquet")]
        try:
            close = load(f)
        except Exception:
            continue
        if len(close) < MIN_ROWS or close.index[-1] < pd.Timestamp("2026-01-01"):
            continue
        for h in HORIZONS:
            X, yv, yp, mr = build(close, h)
            oos = X.index >= pd.Timestamp(OOS_START)
            if oos.sum() < 1000 or yv[oos].nunique() < 2:
                continue
            rows.append({"asset": name, "h": h, "n_oos": int(oos.sum()),
                         "auc_vol_mr": roc_auc_score(yv[oos], mr[oos]),
                         "auc_vol_har": oos_auc(X, yv, h, "har"),
                         "auc_price_har": oos_auc(X, yp, h, "har")})
    df = pd.DataFrame(rows)
    print(f"actifs: {df.asset.nunique()}  lignes: {len(df)}")
    g = df.groupby("h").agg(n=("asset", "count"), mr=("auc_vol_mr", "mean"), har=("auc_vol_har", "mean"),
                            har_p10=("auc_vol_har", lambda s: s.quantile(0.10)), har_p90=("auc_vol_har", lambda s: s.quantile(0.90)),
                            price=("auc_price_har", "mean"), price_p90=("auc_price_har", lambda s: s.quantile(0.90)))
    print(g.round(3).to_string())
    print("part des actifs avec AUC vol HAR > 0.60:", df.groupby("h").apply(lambda d: (d.auc_vol_har > 0.60).mean()).round(2).to_dict())
    print("part des actifs avec AUC prix HAR > 0.55:", df.groupby("h").apply(lambda d: (d.auc_price_har > 0.55).mean()).round(2).to_dict())
    if len(sys.argv) > 2:
        df.to_csv(sys.argv[2], index=False)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 60)
