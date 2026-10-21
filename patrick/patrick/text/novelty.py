"""Score de nouveauté d'une news : 1 − similarité maximale avec les news PARUES AVANT (dans une fenêtre).

Une dépêche reprise dix fois par dix agences n'apporte d'information que la première fois ; sans ce score, le volume
d'articles confond « événement important » et « événement très recopié ».

Point-in-time par construction : seules les news **strictement antérieures** comptent (deux news simultanées ne se voient pas),
et le vectoriseur par hachage n'a aucune statistique de corpus à ajuster (pas d'IDF calculé sur le futur). Le score d'une
news ne change donc jamais quand de nouvelles news arrivent.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import HashingVectorizer

_VEC = HashingVectorizer(n_features=2 ** 18, alternate_sign=False, norm="l2", ngram_range=(1, 2), lowercase=True)


def novelty_scores(texts, times, window_days: float = 7.0, index=None) -> pd.Series:
    texts = list(texts)
    n = len(texts)
    out_index = pd.Index(index) if index is not None else pd.RangeIndex(n)
    if n == 0:
        return pd.Series(dtype=float, index=out_index)
    t = pd.DatetimeIndex(times)
    if t.tz is not None:
        t = t.tz_convert("UTC").tz_localize(None)
    ns = t.as_unit("ns").asi8
    order = np.argsort(ns, kind="stable")
    sorted_ns = ns[order]
    xs = _VEC.transform([texts[i] for i in order]).tocsr()
    window = int(window_days * 86_400 * 1e9)
    scores_sorted = np.ones(n)
    for pos in range(n):
        hi = np.searchsorted(sorted_ns, sorted_ns[pos], side="left")       # strictement antérieures
        lo = np.searchsorted(sorted_ns, sorted_ns[pos] - window, side="left")
        if hi > lo:
            sims = (xs[lo:hi] @ xs[pos].T).toarray()
            scores_sorted[pos] = 1.0 - min(1.0, max(0.0, float(sims.max())))
    scores = np.empty(n)
    scores[order] = scores_sorted
    return pd.Series(scores, index=out_index)
