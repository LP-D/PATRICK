"""Thèmes (LDA) et plongements (LSA) de news.

Les deux se **ajustent sur un texte d'entraînement** puis transforment sans réajuster : dans un backtest, les ajuster sur
une fenêtre qui contient le futur lui ferait voir du vocabulaire qui n'existait pas encore (« covid », « tarifs »).
Le pipeline doit donc les ré-ajuster pli par pli, comme le reste.

Honnêteté sur les noms : les « plongements » ici sont du LSA (TF-IDF puis SVD tronquée), pas un transformeur. Ils captent
le vocabulaire partagé, pas le sens. BERTopic et les plongements de phrases (modèles neuronaux téléchargés) ne sont pas
installés par défaut ; l'interface ci-dessous (`fit_*` / `transform`) est celle qu'ils devront respecter.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.decomposition import LatentDirichletAllocation, TruncatedSVD
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer


@dataclass
class TopicModel:
    vectorizer: CountVectorizer
    lda: LatentDirichletAllocation

    def transform(self, docs) -> np.ndarray:
        """Répartition des thèmes par document (lignes de somme 1)."""
        return self.lda.transform(self.vectorizer.transform(list(docs)))

    def top_words(self, n: int = 8) -> list[list[str]]:
        vocab = np.array(self.vectorizer.get_feature_names_out())
        return [list(vocab[np.argsort(row)[::-1][:n]]) for row in self.lda.components_]


def fit_topics(docs, n_topics: int = 8, seed: int = 0, max_features: int = 5000) -> TopicModel:
    vec = CountVectorizer(stop_words="english", max_features=max_features)
    counts = vec.fit_transform(list(docs))
    lda = LatentDirichletAllocation(n_components=n_topics, random_state=seed, learning_method="batch", max_iter=30)
    lda.fit(counts)
    return TopicModel(vec, lda)


@dataclass
class LsaEmbedder:
    vectorizer: TfidfVectorizer
    svd: TruncatedSVD

    def transform(self, docs) -> np.ndarray:
        return self.svd.transform(self.vectorizer.transform(list(docs)))


def fit_embedder(docs, n_components: int = 64, seed: int = 0) -> LsaEmbedder:
    vec = TfidfVectorizer(stop_words="english", sublinear_tf=True)
    tfidf = vec.fit_transform(list(docs))
    k = max(1, min(n_components, tfidf.shape[1] - 1, tfidf.shape[0] - 1))
    svd = TruncatedSVD(n_components=k, random_state=seed)
    svd.fit(tfidf)
    return LsaEmbedder(vec, svd)
