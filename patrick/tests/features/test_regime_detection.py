"""CHANTIER A (feature/regime-detection-hmm) : detection de regime par HMM
causal a nombre d'etats configurable (defaut 3), selectionne par BIC/AIC, et
reduit a 3 labels (calme/normal/stress) via un seuillage configurable
(quantile ou valeur fixe) applique a la probabilite filtree (causale, jamais
lissee) de l'etat de plus haute variance -- meme logique de filtrage que
`features/vol_models.py::hmm_filtered_stress_prob` (forward algorithm en
log-space, pas `predict_proba`/`decode` qui utiliseraient le futur).

Decision de conception (a signaler dans le rapport, pas evidente depuis
l'enonce du chantier) : le nombre d'etats HMM (choisi par BIC/AIC parmi
{2,3,4}) et le mode de seuillage (quantile/fixe) sont rendus orthogonaux --
quel que soit le nombre d'etats retenu par le critere d'information, le
signal continu expose en sortie est TOUJOURS la probabilite filtree de
l'etat de plus haute variance (generalisation de `hmm_filtered_stress_prob`
a n_states quelconque), ensuite binnee en exactement 3 labels via les 2
coupures du mode de seuillage choisi. Cela evite d'avoir a redefinir le
vocabulaire de sortie (calme/normal/stress) a chaque fois que BIC/AIC change
le nombre d'etats internes.

Garde-fou de fragmentation : reutilise directement
`validation/feasibility.py::is_feasible` par regime (le nombre
d'observations portant ce label, traite comme un n_obs a part entiere pour
la formule ~8.33x horizon deja auditee) plutot que de reinventer un second
seuil -- blocage dur (exception), jamais un warning silencieux.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.features.regime_detection import (
    RegimeFragmentationError,
    check_regime_fragmentation,
    detect_regime,
    select_n_states_bic,
)


def _simulated_three_block_returns(seed: int = 7, n_per_block: int = 600) -> pd.Series:
    """3 blocs de volatilite bien separee (calme -> stress -> calme), assez
    longs pour que le signal domine la penalite BIC/AIC. Rendements gaussiens
    centres, ecarts-types tres distincts (x1 / x8 / x1) pour que le
    regime "stress" du bloc central soit sans ambiguite."""
    rng = np.random.default_rng(seed)
    calm1 = rng.normal(0, 0.005, n_per_block)
    stress = rng.normal(0, 0.040, n_per_block)
    calm2 = rng.normal(0, 0.005, n_per_block)
    rets = np.concatenate([calm1, stress, calm2])
    idx = pd.bdate_range("2015-01-01", periods=len(rets))
    price = 100 * np.cumprod(1 + rets)
    return pd.Series(price, index=idx, name="close")


def test_causal_hmm_recovers_the_known_three_block_regimes():
    """Seuillage FIXE (pas quantile) ici : on verifie la recuperation d'une
    verite terrain absolue (bloc stress connu), pas le comportement relatif
    du mode quantile (teste separement) -- avec 2 blocs calmes pour 1 bloc
    stress, un partage en tertiles du mode quantile repartirait la moitie
    des points calmes en "normal", ce qui ne teste pas la meme chose."""
    series = _simulated_three_block_returns()
    result = detect_regime(series, n_states="auto", threshold_mode="fixed",
                            threshold_values=(0.3, 0.7))

    n = len(series) // 3
    # Bouts de bloc (pas les tout premiers points d'un bloc : le filtre
    # causal a besoin de quelques observations pour "voir" le changement de
    # regime -- c'est la nature meme d'un filtre causal, pas un bug).
    calm1_tail = result.regime.iloc[n // 2:n].mode().iloc[0]
    stress_mid = result.regime.iloc[n + n // 3:2 * n - n // 4].mode().iloc[0]
    calm2_tail = result.regime.iloc[2 * n + n // 2:].mode().iloc[0]

    assert stress_mid == "stress"
    assert calm1_tail == "calme"
    assert calm2_tail == "calme"


def test_regime_labels_are_exactly_the_three_expected_values():
    series = _simulated_three_block_returns()
    result = detect_regime(series, n_states="auto", threshold_mode="quantile")
    assert set(result.regime.dropna().unique()) <= {"calme", "normal", "stress"}


def test_causal_filter_is_not_retroactively_changed_by_future_data():
    """Meme garantie que les tests de fuite existants (`test_leakage.py`) :
    tronquer la serie APRES un point donne ne doit rien changer au regime
    filtre A ce point, tant que `fit_end_idx` (et donc les parametres
    appris) est identique dans les deux appels."""
    series = _simulated_three_block_returns()
    fit_end_idx = 900  # dans le bloc stress -- parametres geles avant le 2e calme

    full = detect_regime(series, n_states=3, threshold_mode="quantile",
                          fit_end_idx=fit_end_idx)
    truncated = detect_regime(series.iloc[:1200], n_states=3, threshold_mode="quantile",
                               fit_end_idx=fit_end_idx)

    common = truncated.regime.index
    pd.testing.assert_series_equal(
        full.stress_prob.reindex(common), truncated.stress_prob.reindex(common),
        check_names=False,
    )
    assert (full.regime.reindex(common) == truncated.regime.reindex(common)).all()


def test_fixed_threshold_mode_uses_the_given_cutoffs_not_quantiles():
    """Verification directe et sans ambiguite : en mode fixe, les coupures
    retournees sont EXACTEMENT `threshold_values`, jamais recalculees a
    partir de la distribution -- contrairement au mode quantile ou elles
    sont derivees des donnees (voir test dedie ci-dessous)."""
    series = _simulated_three_block_returns()
    fixed_values = (0.15, 0.85)
    result = detect_regime(series, n_states=3, threshold_mode="fixed",
                            threshold_values=fixed_values)
    assert result.threshold_cutoffs == fixed_values


def test_quantile_threshold_mode_derives_cutoffs_from_the_data():
    series = _simulated_three_block_returns()
    result = detect_regime(series, n_states=3, threshold_mode="quantile",
                            threshold_values=(1 / 3, 2 / 3))
    # Ne peut pas coincider avec des coupures fixes arbitraires -- doit etre
    # derive de la distribution reelle de stress_prob (bornes [0, 1] mais
    # valeurs concretes dependantes des donnees).
    assert result.threshold_cutoffs != (1 / 3, 2 / 3)
    lo, hi = result.threshold_cutoffs
    assert 0.0 <= lo <= hi <= 1.0


def _simulated_three_distinct_variance_levels(seed: int = 11, n_per_block: int = 700) -> pd.Series:
    """3 niveaux de variance REELLEMENT distincts (calme/normal/stress, 3
    etats statistiques differents) -- a distinguer de
    `_simulated_three_block_returns` ci-dessus, qui est calme-stress-calme
    (le meme etat calme revisite deux fois : statistiquement 2 etats, pas
    3). Confondre les deux a d'abord fait echouer ce test (BIC choisissait a
    raison 2 etats sur le scenario calme-stress-calme -- pas un bug de
    l'implementation, une hypothese de test erronee corrigee ici)."""
    rng = np.random.default_rng(seed)
    calm = rng.normal(0, 0.005, n_per_block)
    normal = rng.normal(0, 0.018, n_per_block)
    stress = rng.normal(0, 0.045, n_per_block)
    rets = np.concatenate([calm, normal, stress])
    idx = pd.bdate_range("2015-01-01", periods=len(rets))
    price = 100 * np.cumprod(1 + rets)
    return pd.Series(price, index=idx, name="close")


def test_bic_selects_three_states_on_a_genuine_three_regime_process():
    series = _simulated_three_distinct_variance_levels()
    ret = series.pct_change().dropna()
    x = ret.values.reshape(-1, 1)
    scores = select_n_states_bic(x, candidates=(2, 3, 4), seed=42)
    bics = {k: v["bic"] for k, v in scores.items()}
    assert min(bics, key=bics.get) == 3


def test_select_n_states_bic_reports_all_candidates_with_increasing_params():
    series = _simulated_three_block_returns()
    ret = series.pct_change().dropna()
    x = ret.values.reshape(-1, 1)
    scores = select_n_states_bic(x, candidates=(2, 3, 4), seed=42)
    assert set(scores.keys()) == {2, 3, 4}
    assert scores[2]["n_params"] < scores[3]["n_params"] < scores[4]["n_params"]


def test_fragmentation_guardrail_hard_blocks_on_an_artificially_rare_regime():
    idx = pd.bdate_range("2015-01-01", periods=2000)
    # 1995 jours "calme", 5 jours "stress" -- horizon 10 : bien en-dessous du
    # seuil ~8.33x meme pour l'ensemble complet, a fortiori pour 5 jours.
    labels = ["calme"] * 1995 + ["stress"] * 5
    regime = pd.Series(labels, index=idx)

    with pytest.raises(RegimeFragmentationError):
        check_regime_fragmentation(regime, horizon=10)


def test_fragmentation_guardrail_passes_when_every_regime_has_enough_history():
    idx = pd.bdate_range("2015-01-01", periods=20000)
    labels = ["calme"] * 10000 + ["normal"] * 8000 + ["stress"] * 2000
    regime = pd.Series(labels, index=idx)

    result = check_regime_fragmentation(regime, horizon=10)
    assert all(r.feasible for r in result.values())


def test_detect_regime_rejects_invalid_threshold_mode():
    series = _simulated_three_block_returns()
    with pytest.raises(ValueError):
        detect_regime(series, threshold_mode="not-a-mode")
