"""Phase 6.4 (P6.4) -- FDR (Benjamini-Hochberg) à travers les cibles,
`patrick/validation/fdr.py`. Tests explicitement demandés par l'énoncé :
sur des p-values simulées uniformes (vrai null partout), les découvertes
après BH doivent être proches de zéro ; sur un mélange null/alternative,
retrouver la puissance attendue."""
from __future__ import annotations

import numpy as np
import pytest

from patrick.validation.fdr import benjamini_hochberg


def test_empty_input_returns_zero_tested():
    result = benjamini_hochberg({})
    assert result["n_tested"] == 0
    assert result["n_bh_significant"] == 0
    assert result["results"] == {}


def test_nan_p_values_are_excluded():
    result = benjamini_hochberg({"A": 0.01, "B": float("nan"), "C": 0.5})
    assert result["n_tested"] == 2
    assert "B" not in result["results"]


def test_adjusted_p_values_are_monotone_non_decreasing_by_rank():
    p = {f"T{i}": v for i, v in enumerate([0.5, 0.01, 0.3, 0.001, 0.2, 0.04])}
    result = benjamini_hochberg(p)
    by_rank = sorted(result["results"].values(), key=lambda r: r["rank"])
    adj = [r["adjusted_p_value"] for r in by_rank]
    assert adj == sorted(adj), "les p-values ajustées (q-values) doivent être triées croissantes par rang"
    for a in adj:
        assert 0.0 <= a <= 1.0


def test_significant_matches_adjusted_p_value_below_alpha():
    p = {"A": 0.001, "B": 0.02, "C": 0.5, "D": 0.8}
    alpha = 0.10
    result = benjamini_hochberg(p, alpha=alpha)
    for target, r in result["results"].items():
        assert r["significant"] == (r["adjusted_p_value"] <= alpha)


def test_known_textbook_example_matches_hand_computed_bh():
    """Exemple calculé à la main : m=5, alpha=0.05, p-values triées
    [0.01, 0.02, 0.03, 0.04, 0.20]. q_(i) = min_{j>=i}(m/j * p_(j)) :
    q_5 = 5/5*0.20 = 0.20
    q_4 = min(5/4*0.04, 0.20) = min(0.05, 0.20) = 0.05
    q_3 = min(5/3*0.03, 0.05) = min(0.05, 0.05) = 0.05
    q_2 = min(5/2*0.02, 0.05) = min(0.05, 0.05) = 0.05
    q_1 = min(5/1*0.01, 0.05) = min(0.05, 0.05) = 0.05
    -> les 4 premiers significatifs à alpha=0.05 (q<=0.05), le 5e non."""
    p = {"A": 0.01, "B": 0.02, "C": 0.03, "D": 0.04, "E": 0.20}
    result = benjamini_hochberg(p, alpha=0.05)
    for target in ("A", "B", "C", "D"):
        assert result["results"][target]["adjusted_p_value"] == pytest.approx(0.05)
        assert result["results"][target]["significant"]
    assert result["results"]["E"]["adjusted_p_value"] == pytest.approx(0.20)
    assert not result["results"]["E"]["significant"]
    assert result["n_bh_significant"] == 4


def test_uniform_null_everywhere_bh_discoveries_near_zero():
    """Déliverable P6.4 : sur des p-values Uniform(0,1) (vrai null pour
    TOUTES les cibles), le nombre de découvertes BH doit être proche de
    zéro -- sous le null complet, P(au moins une découverte BH) = alpha
    exactement (résultat classique de Benjamini-Hochberg), donc le nombre
    MOYEN de découvertes par tirage doit être proche de alpha (~0.10),
    largement en dessous du nombre de "significatifs" bruts (p<=alpha) qui,
    lui, converge vers m*alpha (~5 sur m=50)."""
    rng = np.random.default_rng(0)
    alpha = 0.10
    m = 50
    n_sim = 300
    bh_discoveries = []
    raw_discoveries = []
    for _ in range(n_sim):
        p_values = {f"target_{i}": v for i, v in enumerate(rng.uniform(0, 1, m))}
        result = benjamini_hochberg(p_values, alpha=alpha)
        bh_discoveries.append(result["n_bh_significant"])
        raw_discoveries.append(result["n_raw_significant"])

    mean_bh = np.mean(bh_discoveries)
    mean_raw = np.mean(raw_discoveries)
    # brut (non corrigé) : converge vers m*alpha = 5 sur ce montage.
    assert mean_raw == pytest.approx(m * alpha, abs=1.5)
    # BH : sous le null complet, P(>=1 découverte) = alpha -> moyenne de
    # découvertes proche de alpha (~0.10), un ordre de grandeur sous mean_raw.
    assert mean_bh < 0.5, f"BH devrait produire ~0 découvertes sous le null complet, obtenu {mean_bh:.3f}"
    assert mean_bh < mean_raw / 5


def test_null_alternative_mixture_recovers_expected_power():
    """Déliverable P6.4 : sur un mélange -- moitié cibles à vrai null
    (p ~ Uniform(0,1)), moitié à vraie alternative (p tiré de Beta(0.5, 8),
    fortement concentré près de 0, simulant un DM significatif réel) -- BH
    doit retrouver une puissance substantielle sur les vraies alternatives
    tout en gardant peu de fausses découvertes parmi les vrais nuls."""
    rng = np.random.default_rng(1)
    alpha = 0.10
    n_null, n_alt = 30, 30
    null_p = rng.uniform(0, 1, n_null)
    alt_p = rng.beta(0.5, 8, n_alt)  # concentré près de 0 (signal réel)

    p_values = {}
    truth = {}
    for i, v in enumerate(null_p):
        p_values[f"null_{i}"] = v
        truth[f"null_{i}"] = False
    for i, v in enumerate(alt_p):
        p_values[f"alt_{i}"] = v
        truth[f"alt_{i}"] = True

    result = benjamini_hochberg(p_values, alpha=alpha)

    true_positives = sum(1 for t, r in result["results"].items()
                          if truth[t] and r["significant"])
    false_positives = sum(1 for t, r in result["results"].items()
                           if not truth[t] and r["significant"])
    power = true_positives / n_alt

    assert power > 0.4, f"puissance trop faible sur les vraies alternatives : {power:.2f}"
    # contrôle FDR : parmi les découvertes, la proportion de fausses
    # découvertes doit rester raisonnablement bornée (pas garanti tirage par
    # tirage, mais ne doit pas exploser).
    n_discoveries = true_positives + false_positives
    if n_discoveries > 0:
        fdr_observed = false_positives / n_discoveries
        assert fdr_observed < 0.5, f"proportion de fausses découvertes trop élevée : {fdr_observed:.2f}"
