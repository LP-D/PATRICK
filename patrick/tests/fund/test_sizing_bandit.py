"""Bandit de dimensionnement (`simulate/sizing_bandit.py`) : apprentissage, causalité, rejeu net de frais, comparaison aux heuristiques. Données synthétiques seulement."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.simulate import sizing_bandit as sb


def _world(n: int = 1400, edge: float = 0.0, seed: int = 0, split_at: int = 1100) -> sb.ModelData:
    """Cours aléatoires ; P(hausse) = 0,5 + signal. Le signal du jour t ne prédit le rendement de t+1 que s'il est FORT (|force| > 0,25) : c'est le monde où dimensionner
    selon la conviction a un sens. `edge` = espérance quotidienne de ce gain, en fraction de la volatilité quotidienne de 1 % (0 = monde nul)."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2018-01-01", periods=n)
    strength = rng.uniform(0.0, 0.4, n) * rng.choice([-1, 1], n)
    ret = rng.standard_normal(n) * 0.01
    ret[1:] += edge * 0.01 * np.sign(strength[:-1]) * (np.abs(strength[:-1]) > 0.25)
    close = pd.Series(100 * np.cumprod(1 + ret), index=dates)
    segments = pd.Series(np.where(np.arange(n) < split_at, "test", "holdout"), index=dates)
    return sb.ModelData("SYN", pd.Series(0.5 + strength, index=dates), segments, close)


def test_linucb_converges_to_the_arm_that_pays():
    rng = np.random.default_rng(1)
    policy = sb.LinUCB(alpha=0.5)
    chosen = []
    for _ in range(600):
        x = np.array([1.0, rng.uniform(0, 1), rng.normal()])
        arm = policy.choose(x)
        policy.update(arm, x, {0: 0.0, 1: 0.2, 2: 0.5, 3: 1.0}[arm] + rng.normal() * 0.1)       # le bras 3 paie le plus
        chosen.append(arm)
    assert np.mean(np.array(chosen[-200:]) == 3) > 0.8


def test_contexts_never_read_the_future():
    data = _world(n=600)
    idx = np.arange(0, 600, 3)
    base = sb.contexts(data.scores.to_numpy()[idx], data.close, idx)
    changed = data.close.copy()
    changed.iloc[400:] *= 1.5 + np.sin(np.arange(200))                # tout ce qui suit le jour 400 change
    after = sb.contexts(data.scores.to_numpy()[idx], changed, idx)
    assert np.allclose(base[idx <= 400], after[idx <= 400])
    assert not np.allclose(base[idx > 410], after[idx > 410])         # et le contexte tardif, lui, bouge bien


def test_the_bandits_positions_do_not_depend_on_later_prices():
    data = _world(n=1300, edge=0.3)
    base = sb.run_bandit(data)
    cut = base.index[len(base) // 2]
    close = data.close.copy()
    close[close.index > cut + pd.Timedelta(days=1)] *= 0.5            # un krach après le milieu du holdout
    other = sb.run_bandit(sb.ModelData("SYN", data.scores, data.segments, close))
    early = base.index[base.index < cut]
    assert np.allclose(base[early], other[early])


def test_positions_are_signed_by_the_score_and_sized_by_the_arms():
    pos = sb.run_bandit(_world(edge=0.3))
    assert set(np.abs(pos.round(6))) <= set(sb.ARMS)
    data = _world(edge=0.3)
    holdout = data.scores[data.segments == "holdout"]
    nonzero = pos != 0
    assert (np.sign(pos[nonzero]) == np.sign(holdout[nonzero.index[nonzero]] - 0.5)).all()


def test_replay_of_a_constant_long_matches_buy_and_hold_minus_the_entry_cost():
    data = _world(n=500, split_at=200)
    holdout = data.scores[data.segments == "holdout"]
    ones = pd.Series(1.0, index=holdout.index)
    r = sb.replay(ones, data.close, cost_bps=0.0)
    ret = data.close.pct_change().loc[holdout.index[0]:].iloc[: r["n_days"]].fillna(0.0)
    # exposition 1 dès le lendemain du premier signal : le rendement du jour du premier signal n'est pas capté
    assert r["mean_exposure"] > 0.9
    assert r["total_return"] == pytest.approx(float((1 + ret.iloc[1:]).prod() - 1), abs=0.02)
    costly = sb.replay(ones, data.close, cost_bps=50.0)
    assert costly["total_return"] < r["total_return"]


def test_when_the_edge_is_real_both_learners_find_it():
    rs = [sb.compare_model(_world(edge=0.3, seed=s)) for s in range(10)]
    assert np.mean([r["kelly_ridge"]["sharpe"] for r in rs]) > 0.5          # mesuré : 0,88 net de 5 pb ; ~0 dans le monde nul
    assert np.mean([r["bandit"]["sharpe"] for r in rs]) > 0.4              # mesuré : 0,74
    # ... sans faire pire que le tout-ou-rien à seuil (ils ne le battent pas non plus de beaucoup : voir la note de faisabilité)
    assert np.mean([r["kelly_ridge"]["sharpe"] - r["threshold"]["sharpe"] for r in rs]) > -0.1


def test_in_a_null_world_the_learners_do_not_manufacture_an_edge():
    results = [sb.compare_model(_world(edge=0.0, seed=100 + s), cost_bps=0.0) for s in range(30)]
    for name in ("bandit", "kelly_ridge"):
        assert abs(np.mean([r[name]["sharpe"] for r in results])) < 0.5      # écart-type d'un Sharpe sur ~300 jours : ~1 ; sur 30 mondes : ~0,2
        assert sb.summarize(results, name)["beats_all"] is False


def test_summarize_reports_the_paired_difference_and_a_verdict():
    def res(b, t, p, k):
        return {"ok": True, "bandit": {"sharpe": b}, "kelly_ridge": {"sharpe": b}, "threshold": {"sharpe": t}, "proportional": {"sharpe": p}, "leverage_half": {"sharpe": k}}
    better = [res(1.0 + 0.01 * i, 0.5, 0.4, 0.6) for i in range(40)]
    out = sb.summarize(better)
    assert out["n_models"] == 40 and out["beats_all"] is True
    assert out["versus"]["threshold"]["mean_diff"] == pytest.approx(0.5 + 0.01 * 19.5, abs=1e-6) and out["versus"]["threshold"]["share_better"] == 1.0
    mixed = [res(0.5 + (0.1 if i % 2 else -0.1), 0.5, 0.5, 0.5) for i in range(40)]
    assert sb.summarize(mixed)["beats_all"] is False
    assert sb.compare_model(_world(n=1105, split_at=1100))["ok"] is False        # holdout de 5 jours : trop court
