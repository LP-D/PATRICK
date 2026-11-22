"""Économétrie d'une série, partie 5 : régimes (Markov-switching de statsmodels, lecture du HMM filtré du projet).

On simule une chaîne de Markov à deux états (calme / stress) dont on connaît les moyennes, les variances et la matrice de transition."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.econometrics import regimes as R
from patrick.econometrics import simulate as SIM


def _two_regimes(n=1200, seed=1, p00=0.98, p11=0.95, calm=(0.05, 0.5), stress=(-0.10, 2.0)):
    rng = np.random.default_rng(seed)
    state = np.zeros(n, dtype=int)
    for t in range(1, n):
        stay = p00 if state[t - 1] == 0 else p11
        state[t] = state[t - 1] if rng.random() < stay else 1 - state[t - 1]
    mu = np.where(state == 0, calm[0], stress[0])
    sd = np.where(state == 0, calm[1], stress[1])
    x = pd.Series(rng.normal(mu, sd) / 100.0, index=SIM.arma(n, seed=0).index)     # rendements décimaux
    return x, pd.Series(state, index=x.index)


def test_markov_switching_recovers_volatilities_durations_and_the_regime_path():
    x, truth = _two_regimes()
    ms = R.markov_switching(x, k_regimes=2)
    calm, stress = ms["regimes"][0], ms["regimes"][1]
    assert ms["converged"] is True and ms["stress_regime"] == 1
    assert calm["vol_daily_pct"] == pytest.approx(0.5, rel=0.25) and stress["vol_daily_pct"] == pytest.approx(2.0, rel=0.25)
    assert calm["p_stay"] == pytest.approx(0.98, abs=0.03) and stress["p_stay"] == pytest.approx(0.95, abs=0.04)
    assert calm["expected_duration"] == pytest.approx(1 / (1 - calm["p_stay"]))
    predicted = (np.array(ms["filtered_stress"]) > 0.5).astype(int)
    assert (predicted == truth.to_numpy()).mean() > 0.85


def test_two_regimes_beat_a_single_regime_on_regime_data_and_not_on_noise():
    x, _ = _two_regimes(seed=2)
    assert R.markov_switching(x)["verdict"] == "regimes_supported"
    verdicts = [R.markov_switching(SIM.arma(800, sigma=1.0, seed=70 + s) / 100.0)["verdict"] for s in range(3)]
    assert verdicts.count("single_regime_enough") >= 2


def test_filtered_and_smoothed_probabilities_are_both_reported_and_differ():
    x, _ = _two_regimes(seed=3)
    ms = R.markov_switching(x)
    assert len(ms["filtered_stress"]) == len(ms["smoothed_stress"]) == len(ms["dates"]) == len(x)
    assert not np.allclose(ms["filtered_stress"], ms["smoothed_stress"])
    assert 0 <= min(ms["filtered_stress"]) and max(ms["filtered_stress"]) <= 1


def test_variance_only_switching_keeps_one_mean():
    x, _ = _two_regimes(seed=4)
    ms = R.markov_switching(x, switching_mean=False)
    assert ms["regimes"][0]["mean_pct"] == pytest.approx(ms["regimes"][1]["mean_pct"])


def test_a_series_that_is_too_short_is_refused():
    with pytest.raises(ValueError, match="minimum"):
        R.markov_switching(pd.Series(np.random.default_rng(0).normal(size=80) / 100))


def test_hmm_reading_reuses_the_causal_filter_of_the_project():
    x, truth = _two_regimes(seed=5)
    hmm = R.hmm_reading(x, candidates=(2, 3))
    assert hmm["n_states"] in (2, 3) and hmm["causal"] is True
    sel = {row["n_states"]: row["bic"] for row in hmm["bic"]}
    assert set(sel) == {2, 3}
    stress = np.array(hmm["stress_prob"])
    assert np.corrcoef(stress, truth.to_numpy())[0, 1] > 0.6
    assert hmm["states"][hmm["stress_state"]]["vol_daily_pct"] == max(s["vol_daily_pct"] for s in hmm["states"])
