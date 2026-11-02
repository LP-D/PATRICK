"""Monde à pertes égales par construction (2026-11-02) : deux prédicteurs indépendants de même loi, sur une étiquette à 4 classes dont les
valeurs voisines se chevauchent. Ni l'un ni l'autre ne vaut mieux, quoi qu'il arrive : la p-value bilatérale du DM doit rejeter à 5 % environ
5 % du temps.

Pourquoi ce test (KNOWN_ISSUES, « Validité statistique mesurée ») : sur 12 marches aléatoires le DM bilatéral sortait < 5 % dans 3 mondes, toujours
du côté « le modèle fait PIRE que sa baseline ». Deux lectures : (a) le modèle choisi sur du bruit fait réellement moins bien (un vrai écart),
(b) la taille du test est gonflée. Ici la perte espérée est la même par construction, donc seule (b) peut produire des rejets. Mesuré : 4,3 à
5,8 % pour h <= 5 (n / h >= 50 blocs), ~8 % à 15 blocs (h = 30), ce que dit déjà le seuil de 15 blocs. Le 3/12 observé (probabilité de >= 3 rejets
sur 12 à 5,5 % : ~2,7 %) relève donc de (a) et pas d'un défaut du test à h = 5."""
from __future__ import annotations

import numpy as np
import pytest

from patrick.validation.diebold_mariano import diebold_mariano

PROBS = (0.25, 0.25, 0.25, 0.25)


def _equal_loss_world(rng: np.random.Generator, n: int, h: int, sticky: float) -> tuple[np.ndarray, np.ndarray]:
    shocks = rng.standard_normal(n + h)
    ret = np.convolve(shocks, np.ones(h), mode="valid")[:n] if h > 1 else shocks[:n]     # étiquette d'horizon h : h-1 barres communes
    y = np.digitize(ret, np.quantile(ret, np.cumsum(PROBS)[:-1]))
    losses = []
    for _ in range(2):
        pred = rng.choice(4, size=n, p=PROBS)
        if sticky:                                       # un prédicteur qui répète sa classe, comme une persistance : pertes autocorrélées
            for i in range(1, n):
                if rng.random() < sticky:
                    pred[i] = pred[i - 1]
        losses.append((pred != y).astype(float))
    return losses[0], losses[1]


@pytest.mark.parametrize(("n", "h", "sticky"), [(250, 1, 0.0), (250, 1, 0.8), (300, 5, 0.0), (300, 5, 0.8)])
def test_the_two_sided_dm_keeps_its_size_when_both_predictors_have_the_same_expected_loss(n, h, sticky):
    rng = np.random.default_rng(1000 + n + h)
    worlds = 700
    p = np.array([diebold_mariano(*_equal_loss_world(rng, n, h, sticky), h=h)["p_value"] for _ in range(worlds)])
    assert np.isfinite(p).all()
    rate = float((p < 0.05).mean())
    assert 0.02 <= rate <= 0.09, f"taux de rejet à 5 % = {rate:.3f} (attendu ~0,05)"
    # Pas de biais de sens non plus : sous des pertes égales, « pire » et « meilleur » se rejettent à peu près autant.
    worse = float(np.mean([diebold_mariano(*_equal_loss_world(rng, n, h, sticky), h=h)["dm_stat"] > 2 for _ in range(300)]))
    better = float(np.mean([diebold_mariano(*_equal_loss_world(rng, n, h, sticky), h=h)["dm_stat"] < -2 for _ in range(300)]))
    assert abs(worse - better) < 0.06
